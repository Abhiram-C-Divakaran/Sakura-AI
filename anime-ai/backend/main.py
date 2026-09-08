from __future__ import annotations
import os
from typing import Optional, Dict, Any, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from database.init_db import init_tables, seed_characters

from config.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="Sakura AI Platform",
    description="A production-grade multimodal assistant and frontier repository-level coding engine.",
    version="1.0.0"
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
import uuid
from fastapi import Request

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

scheduler_service = None

from fastapi.responses import JSONResponse
import sqlalchemy as sa
from database.db import get_db_context

@app.on_event("startup")
async def on_startup():
    """Initializes dev schema or relies on Alembic in production, seeds profiles, and starts background scheduler."""
    global scheduler_service
    is_prod = settings.environment in ["production", "prod"]

    if is_prod:
        if not settings.jwt_secret or len(settings.jwt_secret) < 32:
            raise RuntimeError("Production security error: JWT_SECRET must be at least 32 characters.")
        if not settings.integration_encryption_key:
            raise RuntimeError("Production security error: INTEGRATION_ENCRYPTION_KEY must be configured in production.")
        if settings.jwt_secret == settings.integration_encryption_key:
            raise RuntimeError("Production security error: INTEGRATION_ENCRYPTION_KEY must be independent of JWT_SECRET.")

    try:
        if not is_prod:
            init_tables()
        seed_characters()
        print("Sakura AI Platform: Startup database initialized successfully.")
    except Exception as e:
        print(f"Sakura AI Platform: Startup database error: {e}")
        if is_prod:
            raise RuntimeError(f"Critical production database initialization failed: {e}") from e

    is_test = os.getenv("ENVIRONMENT", "").lower() in ["test", "testing"] or settings.environment in ["test", "testing"]
    if is_test:
        return

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

@app.on_event("shutdown")
async def on_shutdown():
    global scheduler_service
    if scheduler_service:
        await scheduler_service.stop()

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


@app.get("/readiness")
async def readiness_check():
    """Readiness probe: validates primary database, schema tables, secrets, and Redis."""
    is_prod = settings.environment in ["production", "prod"]
    db_ok = False
    tables_ok = False
    redis_ok = False
    errors = []

    # 1. DB connectivity and dynamic migration revision resolution
    expected_migration_head = get_packaged_alembic_head()
    migration_ok = False
    try:
        with get_db_context() as db:
            db.execute(sa.text("SELECT 1"))
            insp = sa.inspect(db.bind)
            required_tables = {
                "users", "conversations", "messages", "background_tasks",
                "scheduled_tasks", "scheduled_task_runs",
                "coding_jobs", "coding_task_events", "websocket_tickets"
            }
            existing_tables = set(insp.get_table_names())
            if required_tables.issubset(existing_tables):
                tables_ok = True
            else:
                missing = required_tables - existing_tables
                errors.append(f"Missing required database tables: {missing}")

            # Validate Alembic schema revision dynamically
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
                        errors.append(f"Database schema migration revision is incompatible (current: {current_revision}, expected: {expected_migration_head}).")
            elif is_prod:
                tables_ok = False
                errors.append("Missing alembic_version table in production.")
            else:
                migration_ok = True

            db_ok = True
    except Exception as e:
        errors.append(f"Database error: {str(e)}")

    # 2. Redis status
    try:
        from realtime.manager import ws_manager
        rt_status = await ws_manager.get_status()
        redis_ok = rt_status.get("redis_connected", False)
    except Exception as e:
        redis_ok = False

    # 3. Security secrets
    secrets_ok = True
    if is_prod:
        if not settings.jwt_secret or len(settings.jwt_secret) < 32:
            secrets_ok = False
            errors.append("Invalid or weak JWT_SECRET in production.")
        if not settings.integration_encryption_key:
            secrets_ok = False
            errors.append("Missing INTEGRATION_ENCRYPTION_KEY in production.")

    # 4. Storage subsystem readiness
    from services.storage import check_storage_readiness
    storage_info = check_storage_readiness(is_production=is_prod)
    storage_ok = storage_info.get("healthy", False)
    if is_prod and not storage_ok:
        errors.append(f"Storage error: {storage_info.get('reason') or 'Storage backend unhealthy'}")

    is_ready = db_ok and tables_ok and secrets_ok and (storage_ok if is_prod else True)
    status_str = "READY" if is_ready else ("DEGRADED" if (db_ok and not is_prod) else "NOT_READY")

    response_payload = {
        "status": status_str,
        "ready": is_ready,
        "database": "CONNECTED" if db_ok else "UNAVAILABLE",
        "schema_migrated": tables_ok,
        "redis": "CONNECTED" if redis_ok else "DEGRADED",
        "storage": storage_info,
        "secrets_configured": secrets_ok,
        "environment": settings.environment,
        "errors": errors
    }

    if not is_ready and is_prod:
        return JSONResponse(status_code=503, content=response_payload)
    return response_payload
