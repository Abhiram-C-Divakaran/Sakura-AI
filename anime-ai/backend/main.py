from __future__ import annotations
import os
import time
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import httpx
import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router, startup_event as routes_startup, shutdown_event as routes_shutdown
from database.init_db import init_tables, seed_characters
from database.db import get_db_context
from config.settings import get_settings, KNOWN_DEV_SECRETS

settings = get_settings()

scheduler_service = None
_embedded_coding_worker = None
_embedded_coding_worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Authoritative FastAPI application lifespan:
    - Enforces production security guards on startup
    - Initializes dev schema & idempotent character seeding
    - Starts optional managed background scheduler or single embedded dev coding worker
    - Cleanly shuts down all managed tasks
    """
    global scheduler_service, _embedded_coding_worker, _embedded_coding_worker_task

    is_prod = settings.environment in ["production", "prod"]
    is_test = os.getenv("ENVIRONMENT", "").lower() in ["test", "testing"] or settings.environment in ["test", "testing"]

    if is_prod:
        settings.validate_production_guards()

    try:
        if not is_prod:
            init_tables()
        seed_characters()
        print("Sakura AI Platform: Startup database initialized successfully.")
    except Exception as e:
        print(f"Sakura AI Platform: Startup database error: {e}")
        if is_prod:
            raise RuntimeError(f"Critical production database initialization failed: {e}") from e

    if not is_test:
        await routes_startup()

        embedded_scheduler = os.getenv("SAKURA_EMBEDDED_SCHEDULER", "false").lower() == "true"
        if embedded_scheduler:
            try:
                from tasks.scheduler import TaskSchedulerService
                scheduler_service = TaskSchedulerService(poll_interval_seconds=60)
                await scheduler_service.start()
                print("Sakura AI Platform: Embedded task scheduler service started.")
            except Exception as e:
                print(f"Sakura AI Platform: Task scheduler start error: {e}")
        else:
            print("Sakura AI Platform: Embedded scheduler disabled (standalone scheduler service expected).")

        # Optional single managed embedded coding worker for local development ONLY.
        # Never spawn per-request unclaimed workers; in production run standalone `python -m coding.job_worker`.
        embedded_coding_worker = (
            not is_prod and os.getenv("SAKURA_EMBEDDED_CODING_WORKER", "false").lower() == "true"
        )
        if embedded_coding_worker:
            from coding.job_worker import CodingJobWorker
            _embedded_coding_worker = CodingJobWorker(worker_id=f"embedded_dev_coding_worker_{os.getpid()}")
            _embedded_coding_worker_task = asyncio.create_task(_embedded_coding_worker.run())
            print("Sakura AI Platform: Single managed embedded development coding worker started.")

    try:
        yield
    finally:
        if _embedded_coding_worker is not None:
            _embedded_coding_worker.stop()
        if _embedded_coding_worker_task is not None:
            _embedded_coding_worker_task.cancel()
            try:
                await _embedded_coding_worker_task
            except asyncio.CancelledError:
                pass
            _embedded_coding_worker_task = None
            _embedded_coding_worker = None

        if scheduler_service is not None:
            await scheduler_service.stop()
            scheduler_service = None

        if not is_test:
            await routes_shutdown()


app = FastAPI(
    title="Sakura AI Platform",
    description="A production-grade multimodal assistant and frontier repository-level coding engine.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_and_latency(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    if "/system/status" in request.url.path or "/ws" in request.url.path:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    start_time = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start_time) * 1000

    response.headers["X-Request-ID"] = request_id
    from api.routes import LATENCY_SAMPLES
    LATENCY_SAMPLES.append(latency_ms)
    if len(LATENCY_SAMPLES) > 50:
        LATENCY_SAMPLES.pop(0)

    return response


# Include core router
app.include_router(router)


@app.get("/health")
def health_check():
    """Liveness probe: returns 200 if backend process is running."""
    return {"status": "online", "system": "Sakura AI Core", "version": "1.0.0"}


def get_packaged_alembic_head() -> Optional[str]:
    """Dynamically resolves the expected head migration revision from Alembic script directory."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ini_path = os.path.join(base_dir, "alembic.ini")
        if os.path.exists(ini_path):
            cfg = Config(ini_path)
            script_dir = ScriptDirectory.from_config(cfg)
            return script_dir.get_current_head()
    except Exception as e:
        print(f"Failed to dynamically resolve Alembic migration head: {e}")
    return None


async def _probe_sandbox_executor_readiness() -> Dict[str, Any]:
    """Non-blocking readiness probe against the dedicated remote sandbox executor service."""
    executor_url = os.getenv("SAKURA_SANDBOX_EXECUTOR_URL", settings.sakura_sandbox_executor_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            res = await client.get(f"{executor_url}/readiness")
            data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            ready = res.status_code == 200 and bool(data.get("ready", False))
            return {
                "reachable": True,
                "ready": ready,
                "status_code": res.status_code,
                "docker_available": bool(data.get("docker_available", False)),
                "image_available": bool(data.get("image_available", False)),
                "container_can_start": bool(data.get("container_can_start", False)),
                "non_root_execution": bool(data.get("non_root_execution", False)),
                "workspace_volume_available": bool(data.get("workspace_volume_available", False)),
                "image": data.get("image"),
            }
    except Exception:
        return {
            "reachable": False,
            "ready": False,
            "status_code": None,
            "docker_available": False,
            "image_available": False,
            "container_can_start": False,
            "non_root_execution": False,
            "workspace_volume_available": False,
            "image": None,
        }


@app.get("/readiness")
async def readiness_check():
    """
    Truthful readiness probe validating all required production dependencies without exposing secrets:
    - PostgreSQL / database connectivity & required schema tables + Alembic revision
    - Redis connectivity (required in production)
    - Security secrets & independent capability signing key
    - Storage backend connectivity (non-blocking)
    - Remote sandbox executor readiness & required runtime image
    """
    env_now = os.getenv("ENVIRONMENT", settings.environment).strip().lower()
    is_prod = env_now in ["production", "prod"]

    db_ok = False
    tables_ok = False
    migration_ok = False
    redis_ok = False
    errors: List[str] = []
    degraded_capabilities: List[str] = []

    # 1. DB connectivity, required tables, and Alembic revision
    expected_migration_head = get_packaged_alembic_head()
    current_revision = None
    try:
        with get_db_context() as db:
            db.execute(sa.text("SELECT 1"))
            insp = sa.inspect(db.bind)
            required_tables = {
                "users", "conversations", "messages", "documents", "document_chunks",
                "generated_images", "image_generation_jobs", "storage_deletion_outbox",
                "background_tasks", "scheduled_tasks", "scheduled_task_runs",
                "coding_tasks", "coding_jobs", "coding_task_events",
                "sandbox_network_authorizations", "websocket_tickets", "password_reset_tokens",
            }
            existing_tables = set(insp.get_table_names())
            if required_tables.issubset(existing_tables):
                tables_ok = True
            else:
                missing = sorted(required_tables - existing_tables)
                errors.append(f"Missing required database tables: {missing}")

            if "alembic_version" in existing_tables:
                res = db.execute(sa.text("SELECT version_num FROM alembic_version")).fetchone()
                current_revision = res[0] if res else None
                if expected_migration_head and current_revision == expected_migration_head:
                    migration_ok = True
                elif not is_prod and current_revision:
                    migration_ok = True
                else:
                    if is_prod:
                        tables_ok = False
                    errors.append(
                        f"Database schema migration revision mismatch (current: {current_revision}, expected: {expected_migration_head})."
                    )
            elif is_prod:
                tables_ok = False
                errors.append("Missing alembic_version table in production.")
            else:
                migration_ok = True

            db_ok = True
    except Exception as e:
        errors.append(f"Database connectivity error: {type(e).__name__}")

    # 2. Redis availability
    try:
        from realtime.manager import ws_manager
        rt_status = await ws_manager.get_status()
        redis_ok = bool(rt_status.get("redis_connected", False))
        if not redis_ok:
            # Direct ping fallback in case ws_manager was not initialized (e.g. test client)
            def _ping_redis() -> bool:
                client = None
                try:
                    import redis
                    redis_url = os.getenv("REDIS_URL", settings.redis_url)
                    client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
                    return bool(client.ping())
                except Exception:
                    return False
                finally:
                    if client is not None:
                        try:
                            client.close()
                        except Exception:
                            pass
            redis_ok = await asyncio.to_thread(_ping_redis)
    except Exception:
        redis_ok = False

    if not redis_ok:
        degraded_capabilities.append("distributed_realtime_and_nonce_store")
        if is_prod:
            errors.append("Redis is unavailable (required in production for realtime, queues, and nonce replay protection).")

    # 3. Security secrets & independent capability signing key (never emit values)
    jwt_secret = os.getenv("JWT_SECRET", settings.jwt_secret or "").strip()
    integ_key = os.getenv("INTEGRATION_ENCRYPTION_KEY", settings.integration_encryption_key or "").strip()
    svc_token = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", settings.sakura_sandbox_service_token or "").strip()
    cap_key = os.getenv("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY", settings.sakura_sandbox_capability_signing_key or "").strip()

    secrets_ok = True
    capability_key_ok = bool(cap_key and len(cap_key) >= 32)
    if is_prod:
        if not jwt_secret or len(jwt_secret) < 32 or jwt_secret in KNOWN_DEV_SECRETS:
            secrets_ok = False
            errors.append("JWT_SECRET is missing, weak, or uses a development default.")
        if not integ_key or len(integ_key) < 32 or integ_key in KNOWN_DEV_SECRETS or integ_key == jwt_secret:
            secrets_ok = False
            errors.append("INTEGRATION_ENCRYPTION_KEY is missing, weak, or not independent of JWT_SECRET.")
        if not svc_token:
            secrets_ok = False
            errors.append("SAKURA_SANDBOX_SERVICE_TOKEN is required in production.")
        if not cap_key or len(cap_key) < 32 or cap_key in KNOWN_DEV_SECRETS or cap_key in {jwt_secret, integ_key, svc_token}:
            capability_key_ok = False
            secrets_ok = False
            errors.append("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY must be an independent >=32-char secret in production.")

    # 4. Storage subsystem readiness (non-blocking)
    from services.storage import check_storage_readiness
    storage_info = await asyncio.to_thread(check_storage_readiness, is_production=is_prod)
    storage_ok = bool(storage_info.get("healthy", False))
    if not storage_ok:
        degraded_capabilities.append("object_storage")
        if is_prod:
            errors.append(f"Storage error: {storage_info.get('reason') or 'Storage backend unhealthy'}")

    # 5. Sandbox executor & runtime image readiness (non-blocking)
    sandbox_info = await _probe_sandbox_executor_readiness()
    sandbox_ok = bool(sandbox_info.get("ready", False))
    if not sandbox_ok:
        degraded_capabilities.append("sakura_code_container_sandbox")
        if is_prod:
            errors.append("Sandbox executor service or required runtime image is not ready.")

    if is_prod:
        is_ready = (
            db_ok
            and tables_ok
            and migration_ok
            and secrets_ok
            and capability_key_ok
            and storage_ok
            and redis_ok
            and sandbox_ok
        )
        status_str = "READY" if is_ready else "NOT_READY"
    else:
        core_ready = db_ok and tables_ok and secrets_ok and capability_key_ok
        all_optional_ready = redis_ok and storage_ok and sandbox_ok
        is_ready = core_ready
        if not core_ready:
            status_str = "NOT_READY"
        elif not all_optional_ready:
            status_str = "DEGRADED"
        else:
            status_str = "READY"

    response_payload = {
        "status": status_str,
        "ready": is_ready,
        "database": "CONNECTED" if db_ok else "UNAVAILABLE",
        "schema_migrated": tables_ok and migration_ok,
        "schema_revision": current_revision,
        "redis": "CONNECTED" if redis_ok else "UNAVAILABLE",
        "storage": storage_info,
        "sandbox_executor": sandbox_info,
        "capability_signing_key_configured": capability_key_ok,
        "secrets_configured": secrets_ok,
        "degraded_capabilities": degraded_capabilities,
        "environment": env_now,
        "errors": errors,
    }

    if not is_ready and is_prod:
        return JSONResponse(status_code=503, content=response_payload)
    return response_payload
