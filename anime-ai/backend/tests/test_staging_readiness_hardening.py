"""
Sakura AI — Staging Readiness & Production Hardening Regression Suite
Validates:
- Phase 2: PostgreSQL URL driver normalization (psycopg2 consistency)
- Phase 3: Sandbox executor /readiness contract (no stale failure cache, POSIX binary probe, Redis gate, diagnostics)
- Phase 4: Durable image generation (no API/library/chat bypass, pipeline enforcement, Redis pop + DB fallback,
           heartbeat renewal, active cancellation, lease-loss fencing, stale recovery)
- Phase 5: Sakura Code immediate assistant message persistence & monotonic SSE replay/reconnect
- Phase 6: OAuth truthfulness, production HTTPS PUBLIC_APP_URL guard, SMTP failure token rollback,
           self-service account deletion (active job cancel, disk/storage/DB cleanup, audit log),
           async user data export (worker execution, ZIP bundle, strict tenant isolation)
- Phase 7: Trusted-proxy CIDR rate limiting (anti-spoofing, fail-closed in prod),
           durable multi-worker per-user quotas across chat/images/coding/uploads/scheduled
- Phase 8: Production environment pre-flight validator (validate_env.py)
"""

import io
import os
import sys
import json
import uuid
import shutil
import asyncio
import zipfile
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"
os.environ["JWT_SECRET"] = "test-secret-key-for-staging-hardening-minimum-32-chars-ok"
os.environ["INTEGRATION_ENCRYPTION_KEY"] = "test_integration_key_32_chars_ok!"
os.environ["SAKURA_SANDBOX_SERVICE_TOKEN"] = "test_sandbox_service_token_staging"
os.environ["SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY"] = "test_capability_signing_key_32chars!"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database.db import Base, engine, get_db_context, normalize_database_url
from database.models import (
    User,
    Conversation,
    Message,
    Document,
    RepositoryWorkspace,
    CodingTask,
    CodingJob,
    CodingTaskEvent,
    BackgroundTask,
    ImageGenerationJob,
    ImageGenerationJobStatus,
    PasswordResetToken,
    UserUsageQuota,
    UserDataExport,
    AccountAuditEvent,
    utc_now,
)
from auth.manager import AuthManager
from services.rate_limit import get_client_ip, enforce_rate_limit, reset_rate_limits
from services.email import get_canonical_public_app_url, is_password_reset_enabled
from services.quotas import enforce_user_quota, get_user_quota_summary
from media.image_worker import (
    ImageJobWorker,
    create_image_generation_job,
    validate_requested_pipeline,
    IMAGE_JOB_QUEUE_NAME,
)
from coding.job_worker import append_coding_task_event
from coding.sandbox_service import app as sandbox_app, _readiness_cache
from tasks.worker import DurableTaskWorker


class TestStagingReadinessHardening(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.sandbox_client = TestClient(sandbox_app)

    def setUp(self):
        reset_rate_limits()
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_staging_test_")
        self.password = "StrongPass123!"
        self.user_a_id, self.user_a_name, self.headers_a = self._create_user("staging_a")
        self.user_b_id, self.user_b_name, self.headers_b = self._create_user("staging_b")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_user(self, prefix: str):
        uid = uuid.uuid4()
        uname = f"{prefix}_{uid.hex[:8]}"
        email = f"{uname}@example.com"
        with get_db_context() as db:
            db.add(
                User(
                    id=uid,
                    username=uname,
                    email=email,
                    hashed_password=AuthManager.hash_password(self.password),
                )
            )
            db.commit()
        token = AuthManager.create_access_token({"sub": uname})
        return uid, uname, {"Authorization": f"Bearer {token}"}

    # ─── Phase 2: PostgreSQL Driver Normalization ─────────────────────────────

    def test_phase2_normalize_database_url_enforces_psycopg2(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@host:5432/db"),
            "postgresql+psycopg2://u:p@host:5432/db",
        )
        self.assertEqual(
            normalize_database_url("postgres://u:p@host:5432/db"),
            "postgresql+psycopg2://u:p@host:5432/db",
        )
        self.assertEqual(
            normalize_database_url("postgresql+psycopg2://u:p@host:5432/db"),
            "postgresql+psycopg2://u:p@host:5432/db",
        )
        self.assertEqual(
            normalize_database_url("sqlite:///./test.db"),
            "sqlite:///./test.db",
        )

    # ─── Phase 3: Sandbox Executor /readiness Contract ────────────────────────

    def test_phase3_sandbox_readiness_does_not_cache_failures_and_reports_diagnostics(self):
        _readiness_cache["last_check"] = 0.0
        _readiness_cache["result"] = None

        with patch.dict(os.environ, {"ENVIRONMENT": "production", "REDIS_URL": "redis://localhost:6379/0", "SAKURA_WORKSPACES_VOLUME": ""}):
            # 1st call: Docker temporarily unavailable -> 503 with diagnostic docker_error
            with patch("coding.sandbox_service.check_docker_status", return_value=(False, "daemon starting")), \
                 patch("coding.sandbox_service.check_redis_status", return_value=(True, None)):
                r1 = self.sandbox_client.get("/readiness")
                self.assertEqual(r1.status_code, 503)
                d1 = r1.json()
                self.assertFalse(d1["ready"])
                self.assertEqual(d1["docker_error"], "daemon starting")
                self.assertTrue(d1["redis_available"])

            # 2nd immediate call: Docker & smoke check healthy -> MUST recover immediately (not cached 503!)
            smoke_ok = SimpleNamespace(
                returncode=0,
                stdout="UID=1001\nBIN:python3=1\nBIN:python=1\nBIN:git=1\nBIN:node=1\nBIN:npm=1\n",
                stderr="",
            )
            inspect_ok = SimpleNamespace(returncode=0, stdout="ok", stderr="")

            def fake_subproc(cmd, *args, **kwargs):
                if "inspect" in cmd:
                    return inspect_ok
                if "run" in cmd:
                    return smoke_ok
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("coding.sandbox_service.check_docker_status", return_value=(True, None)), \
                 patch("coding.sandbox_service.check_redis_status", return_value=(True, None)), \
                 patch("coding.sandbox_service.subprocess.run", side_effect=fake_subproc):
                r2 = self.sandbox_client.get("/readiness")
                self.assertEqual(r2.status_code, 200, r2.text)
                d2 = r2.json()
                self.assertTrue(d2["ready"])
                self.assertTrue(d2["non_root_execution"])
                self.assertTrue(all(d2["binaries"].values()))

    # ─── Phase 4: Durable Image Generation Pipeline & Worker ──────────────────

    def test_phase4_image_endpoints_use_durable_jobs_and_validate_pipeline(self):
        # Unsupported pipeline rejected truthfully with HTTP 400
        bad = self.client.post(
            "/api/v1/images/jobs",
            headers=self.headers_a,
            json={"prompt": "A crisp SVG logo", "requested_pipeline": "vector"},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Unsupported", bad.json()["detail"])

        # Alias normalized truthfully ('photorealistic' -> 'photorealism')
        ok_alias = self.client.post(
            "/api/v1/images/jobs",
            headers=self.headers_a,
            json={"prompt": "Portrait of a violinist", "requested_pipeline": "photorealistic"},
        )
        self.assertEqual(ok_alias.status_code, 202)
        self.assertEqual(ok_alias.json()["requested_pipeline"], "photorealism")

        # POST /images/generate must NOT bypass durable jobs
        gen_resp = self.client.post(
            "/api/v1/images/generate",
            headers=self.headers_a,
            json={"prompt": "Sakura tree at dusk", "requested_pipeline": "anime"},
        )
        self.assertEqual(gen_resp.status_code, 202)
        gen_body = gen_resp.json()
        self.assertEqual(gen_body["status"], "queued")
        self.assertIn("job_id", gen_body)
        self.assertEqual(gen_body["job"]["requested_pipeline"], "anime")

        # POST /library/generate-image must NOT bypass durable jobs
        lib_resp = self.client.post(
            "/api/v1/library/generate-image",
            headers=self.headers_a,
            json={"prompt": "Minimal moonlit shrine"},
        )
        self.assertEqual(lib_resp.status_code, 202)
        self.assertEqual(lib_resp.json()["status"], "queued")
        self.assertIn("job_id", lib_resp.json())

    async def test_phase4_image_worker_redis_pop_heartbeat_cancellation_and_lease_fencing(self):
        # 1. Create a job and verify claim_next_job consumes Redis queue entry (LPOP)
        with get_db_context() as db:
            job, created = create_image_generation_job(
                db=db,
                user_id=self.user_a_id,
                prompt="Heartbeat & cancel test",
                requested_pipeline="anime",
            )
            self.assertTrue(created)
            job_id = job.id

        popped_ids = [str(job_id)]
        worker = ImageJobWorker(worker_id="img_w_hb", lease_duration=2.0, heartbeat_interval=0.08)

        with patch("media.image_worker._pop_redis_image_job", side_effect=lambda: popped_ids.pop(0) if popped_ids else None):
            claimed = worker.claim_next_job()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, job_id)
        self.assertEqual(len(popped_ids), 0, "Redis queue entry must be popped/consumed by worker")

        initial_hb = claimed.heartbeat_at

        # 2. Verify active heartbeat renewal + active cancellation mid-generation
        cancelled_observed = asyncio.Event()

        async def slow_generator(user_id, prompt, params):
            self.assertEqual(params.get("requested_pipeline"), "anime")
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                cancelled_observed.set()
                raise
            return {"id": str(uuid.uuid4()), "provider": "pollinations", "model": "flux"}

        exec_task = asyncio.create_task(worker.execute_job(claimed, generator_fn=slow_generator))
        await asyncio.sleep(0.22)  # allow at least 2 heartbeat renewals

        with get_db_context() as db:
            mid = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
            self.assertGreater(mid.heartbeat_at, initial_hb, "Worker heartbeat must renew during execution")
            # Request cancellation while running
            mid.cancel_requested = True
            db.commit()

        ok = await exec_task
        self.assertFalse(ok)
        self.assertTrue(cancelled_observed.is_set(), "In-flight generation must be actively cancelled")

        with get_db_context() as db:
            done = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
            self.assertEqual(done.status, ImageGenerationJobStatus.CANCELLED)

        # 3. Verify lease loss aborts stale worker with ZERO writes
        with get_db_context() as db:
            job2, _ = create_image_generation_job(db=db, user_id=self.user_a_id, prompt="Lease loss fencing test")
            job2_id = job2.id

        worker_old = ImageJobWorker(worker_id="img_w_old", lease_duration=2.0, heartbeat_interval=0.08)
        with patch("media.image_worker._pop_redis_image_job", return_value=str(job2_id)):
            claimed2 = worker_old.claim_next_job()
        self.assertEqual(claimed2.id, job2_id)

        async def slow_gen_2(user_id, prompt, params):
            await asyncio.sleep(5.0)
            return {"id": str(uuid.uuid4()), "provider": "pollinations", "model": "flux"}

        t2 = asyncio.create_task(worker_old.execute_job(claimed2, generator_fn=slow_gen_2))
        await asyncio.sleep(0.05)

        # Another worker legitimately takes over after recovery
        new_attempt = uuid.uuid4()
        with get_db_context() as db:
            j2 = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job2_id).first()
            j2.worker_id = "img_w_new"
            j2.execution_attempt_id = new_attempt
            j2.status = ImageGenerationJobStatus.RUNNING
            db.commit()

        res2 = await t2
        self.assertFalse(res2)

        with get_db_context() as db:
            after = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job2_id).first()
            self.assertEqual(after.worker_id, "img_w_new")
            self.assertEqual(after.execution_attempt_id, new_attempt)
            self.assertEqual(after.status, ImageGenerationJobStatus.RUNNING, "Stale worker must perform ZERO writes after lease loss")

    # ─── Phase 5: Sakura Code Immediate Persistence & Replay ──────────────────

    def test_phase5_chat_stream_persists_coding_task_immediately_for_refresh_recovery(self):
        ws_dir = os.path.join(self.temp_dir, "ws_phase5")
        os.makedirs(ws_dir, exist_ok=True)
        ws_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        with get_db_context() as db:
            db.add(
                RepositoryWorkspace(
                    id=ws_id,
                    user_id=self.user_a_id,
                    name="sakura-demo-repo",
                    workspace_path=ws_dir,
                    status="READY",
                )
            )
            db.add(
                Conversation(
                    id=conv_id,
                    user_id=self.user_a_id,
                    character_id="sakura",
                    title="Chat with Sakura",
                )
            )
            db.commit()

        stream_resp = self.client.post(
            "/api/v1/chat/stream",
            headers=self.headers_a,
            json={
                "conversation_id": str(conv_id),
                "message": "/code fix the unit test",
                "active_workspace_id": str(ws_id),
            },
        )
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("coding_task_id", stream_resp.text)

        # Simulate page refresh: load persisted conversation messages
        msgs = self.client.get(f"/api/v1/conversations/{conv_id}/messages", headers=self.headers_a).json()
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        self.assertTrue(assistant_msgs)
        meta = assistant_msgs[-1]["metadata"]
        task_id = meta.get("coding_task_id")
        self.assertTrue(task_id)
        self.assertEqual(meta.get("workspace_id"), str(ws_id))
        self.assertIn(task_id, meta.get("events_stream_url", ""))

        # Append sequential events and verify after_sequence replay suppresses duplicates
        with get_db_context() as db:
            job = db.query(CodingJob).filter(CodingJob.task_id == task_id).first()
            job_id = job.id
        append_coding_task_event(task_id=task_id, job_id=job_id, phase="PLANNING", event_type="status", message="Planning")
        append_coding_task_event(task_id=task_id, job_id=job_id, phase="EXECUTING", event_type="tool_start", tool_name="run_tests")
        append_coding_task_event(task_id=task_id, job_id=job_id, phase="COMPLETED_VERIFIED", event_type="status", message="All green")

        ev_all = self.client.get(f"/api/v1/coding/tasks/{task_id}/events?after_sequence=0", headers=self.headers_a).json()
        seqs = [e["sequenceNumber"] for e in ev_all]
        self.assertEqual(seqs, sorted(set(seqs)))
        self.assertGreaterEqual(len(seqs), 3)

        ev_tail = self.client.get(
            f"/api/v1/coding/tasks/{task_id}/events?after_sequence={seqs[1]}",
            headers=self.headers_a,
        ).json()
        self.assertTrue(all(e["sequenceNumber"] > seqs[1] for e in ev_tail))

    # ─── Phase 6: Auth Correctness, Password Reset, Account Delete & Export ───

    def test_phase6_oauth_never_advertised_when_routes_absent_and_prod_reset_url_enforced(self):
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "fake-google-id",
                "GOOGLE_CLIENT_SECRET": "fake-google-secret",
                "GITHUB_CLIENT_ID": "fake-github-id",
                "GITHUB_CLIENT_SECRET": "fake-github-secret",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_FROM_EMAIL": "noreply@example.com",
                "ENVIRONMENT": "production",
                "PUBLIC_APP_URL": "http://localhost:3000",
            },
        ):
            cfg = self.client.get("/api/v1/auth/config").json()
            self.assertFalse(cfg["google_oauth_enabled"], "Must not advertise non-existent Google OAuth login route")
            self.assertFalse(cfg["github_oauth_enabled"], "Must not advertise non-existent GitHub OAuth login route")
            self.assertFalse(cfg["password_reset_enabled"], "Production localhost PUBLIC_APP_URL must disable password reset")
            self.assertIsNone(get_canonical_public_app_url())

            # Requesting reset in prod with localhost URL fails with 503
            r_503 = self.client.post(
                "/api/v1/auth/password-reset/request",
                json={"identifier": self.user_a_name},
            )
            self.assertEqual(r_503.status_code, 503)

        # SMTP send failure rolls back / deletes token so no live orphan token exists
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_FROM_EMAIL": "noreply@example.com",
                "ENVIRONMENT": "production",
                "PUBLIC_APP_URL": "https://sakura.example.com",
            },
        ):
            self.assertTrue(is_password_reset_enabled())
            with patch("services.email.send_password_reset_email", side_effect=RuntimeError("SMTP connection refused")), \
                 patch("services.rate_limit._check_redis_limit", return_value=True):
                r_fail = self.client.post(
                    "/api/v1/auth/password-reset/request",
                    json={"identifier": self.user_a_name},
                )
                self.assertEqual(r_fail.status_code, 503)

        with get_db_context() as db:
            tok_count = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == self.user_a_id).count()
            self.assertEqual(tok_count, 0, "Failed SMTP send must delete newly created PasswordResetToken")

    async def test_phase6_user_data_export_and_account_deletion_lifecycle(self):
        storage_root = os.path.join(self.temp_dir, "storage")
        ws_dir = os.path.join(self.temp_dir, "ws_delete_me")
        os.makedirs(storage_root, exist_ok=True)
        os.makedirs(ws_dir, exist_ok=True)

        with patch.dict(os.environ, {"SAKURA_STORAGE_BACKEND": "local", "SAKURA_STORAGE_ROOT": storage_root}):
            # Seed user A data: conversation, message, file, workspace, queued image job
            conv_id = uuid.uuid4()
            with get_db_context() as db:
                db.add(Conversation(id=conv_id, user_id=self.user_a_id, character_id="sakura", title="Exportable Chat"))
                db.add(Message(id=uuid.uuid4(), conversation_id=conv_id, role="user", content="Remember my sakura notes"))
                db.add(RepositoryWorkspace(id=uuid.uuid4(), user_id=self.user_a_id, name="del-ws", workspace_path=ws_dir, status="READY"))
                create_image_generation_job(db=db, user_id=self.user_a_id, prompt="Pending job to cancel")
                db.commit()

            # 1. Request async user data export
            exp_req = self.client.post("/api/v1/auth/me/export", headers=self.headers_a)
            self.assertEqual(exp_req.status_code, 202, exp_req.text)
            export_id = exp_req.json()["id"]

            # User B must NOT see User A's export
            self.assertEqual(self.client.get(f"/api/v1/auth/me/export/{export_id}", headers=self.headers_b).status_code, 404)

            # Execute via DurableTaskWorker
            worker = DurableTaskWorker(worker_id="export_test_worker")
            claimed = worker.claim_next_task()
            while claimed and claimed.type != "user_data_export":
                claimed = worker.claim_next_task()
            self.assertIsNotNone(claimed, "Expected durable user_data_export BackgroundTask")
            await worker.execute_task(claimed)

            st = self.client.get(f"/api/v1/auth/me/export/{export_id}", headers=self.headers_a).json()
            self.assertEqual(st["status"], "COMPLETED")

            # Download ZIP & verify contents (user data present, NO password hash!)
            dl = self.client.get(f"/api/v1/auth/me/export/{export_id}/download", headers=self.headers_a)
            self.assertEqual(dl.status_code, 200)
            self.assertEqual(
                self.client.get(f"/api/v1/auth/me/export/{export_id}/download", headers=self.headers_b).status_code,
                404,
            )
            with zipfile.ZipFile(io.BytesIO(dl.content), "r") as zf:
                payload = json.loads(zf.read("export.json").decode("utf-8"))
            self.assertEqual(payload["account"]["username"], self.user_a_name)
            self.assertNotIn("hashed_password", payload["account"])
            self.assertTrue(any(c["title"] == "Exportable Chat" for c in payload["conversations"]))

            # 2. Self-service account deletion guards
            bad_confirm = self.client.request(
                "DELETE",
                "/api/v1/auth/me",
                headers=self.headers_a,
                json={"password": self.password, "confirm": "YES"},
            )
            self.assertEqual(bad_confirm.status_code, 400)

            bad_pw = self.client.request(
                "DELETE",
                "/api/v1/auth/me",
                headers=self.headers_a,
                json={"password": "WrongPassword999!", "confirm": "DELETE"},
            )
            self.assertEqual(bad_pw.status_code, 403)

            # Valid deletion succeeds and cleans up DB, disk workspace, storage objects, and logs audit event
            ok_del = self.client.request(
                "DELETE",
                "/api/v1/auth/me",
                headers=self.headers_a,
                json={"password": self.password, "confirm": "DELETE"},
            )
            self.assertEqual(ok_del.status_code, 200, ok_del.text)
            del_body = ok_del.json()
            self.assertEqual(del_body["status"], "deleted")
            self.assertFalse(os.path.exists(ws_dir), "Workspace directory must be removed on account deletion")

            with get_db_context() as db:
                self.assertIsNone(db.query(User).filter(User.id == self.user_a_id).first())
                self.assertEqual(db.query(Conversation).filter(Conversation.user_id == self.user_a_id).count(), 0)
                self.assertEqual(db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == self.user_a_id).count(), 0)
                self.assertIsNotNone(db.query(User).filter(User.id == self.user_b_id).first(), "User B must remain untouched")
                audit = db.query(AccountAuditEvent).filter(
                    AccountAuditEvent.subject_user_id == self.user_a_id,
                    AccountAuditEvent.event_type == "ACCOUNT_DELETED",
                ).first()
                self.assertIsNotNone(audit)
                self.assertGreaterEqual(audit.details_json.get("cancelled_image_jobs", 0), 1)
                self.assertGreaterEqual(audit.details_json.get("storage_objects_deleted", 0), 1)

    # ─── Phase 7: Trusted-Proxy Rate Limiting & Durable Per-User Quotas ───────

    def test_phase7_proxy_aware_ip_extraction_and_prod_fail_closed(self):
        def make_req(peer_ip: str, xff: str = ""):
            headers = {"x-forwarded-for": xff} if xff else {}
            return SimpleNamespace(client=SimpleNamespace(host=peer_ip), headers=headers)

        # 1. Untrusted peer spoofing X-Forwarded-For -> header MUST be ignored
        with patch.dict(os.environ, {"TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            spoofed_req = make_req("203.0.113.55", "198.51.100.1")
            self.assertEqual(get_client_ip(spoofed_req), "203.0.113.55")

            # 2. Trusted proxy forwarding chain with attacker-prepended IP -> walk right-to-left skipping trusted hops
            proxied_req = make_req("10.0.0.5", "1.1.1.1, 198.51.100.77, 10.0.0.9")
            self.assertEqual(get_client_ip(proxied_req), "198.51.100.77")

        # 3. Fail-closed in production when Redis is unavailable on security-sensitive endpoints
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "REDIS_URL": ""}):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                enforce_rate_limit("auth_login_ip", "198.51.100.77", limit=10, window_seconds=60, fail_closed_in_prod=True)
            self.assertEqual(ctx.exception.status_code, 503)

    def test_phase7_durable_per_user_quotas_enforced_across_sessions(self):
        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "2"}):
            # User A consumes 2 image jobs across separate HTTP requests -> 3rd returns HTTP 429
            r1 = self.client.post("/api/v1/images/jobs", headers=self.headers_a, json={"prompt": "Quota test 1"})
            r2 = self.client.post("/api/v1/images/jobs", headers=self.headers_a, json={"prompt": "Quota test 2"})
            r3 = self.client.post("/api/v1/images/jobs", headers=self.headers_a, json={"prompt": "Quota test 3"})
            self.assertEqual(r1.status_code, 202)
            self.assertEqual(r2.status_code, 202)
            self.assertEqual(r3.status_code, 429)

            # User B has an independent quota and succeeds
            rb = self.client.post("/api/v1/images/jobs", headers=self.headers_b, json={"prompt": "User B image"})
            self.assertEqual(rb.status_code, 202)

            # Quota summary endpoint reports exact durable count
            summary = self.client.get("/api/v1/auth/me/quotas", headers=self.headers_a).json()
            self.assertEqual(summary["quotas"]["image_generation"]["used"], 2)
            self.assertEqual(summary["quotas"]["image_generation"]["remaining"], 0)

    # ─── Phase 8: Environment Pre-Flight Validator ────────────────────────────

    def test_phase8_validate_env_script(self):
        ops_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ops", "scripts"))
        sys.path.insert(0, ops_dir)
        import validate_env

        bad_errors, _ = validate_env.validate_environment({"ENVIRONMENT": "production", "DATABASE_URL": "sqlite:///bad.db"})
        self.assertGreater(len(bad_errors), 0)

        good_env = {
            "ENVIRONMENT": "production",
            "POSTGRES_PASSWORD": "S3cure_Pg_Password_98765",
            "DATABASE_URL": "postgresql+psycopg2://sakura:S3cure_Pg_Password_98765@postgres:5432/anime_ai",
            "REDIS_URL": "redis://redis:6379/0",
            "JWT_SECRET": "a" * 40,
            "INTEGRATION_ENCRYPTION_KEY": "b" * 40,
            "SAKURA_SANDBOX_SERVICE_TOKEN": "c" * 32,
            "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY": "d" * 40,
            "SAKURA_EMBEDDED_WORKER": "false",
            "SAKURA_EMBEDDED_SCHEDULER": "false",
            "SAKURA_EMBEDDED_CODING_WORKER": "false",
            "SAKURA_STORAGE_BACKEND": "s3",
            "SAKURA_STORAGE_BUCKET": "sakura-prod-bucket",
            "SAKURA_STORAGE_ACCESS_KEY": "AKIA_REAL_KEY",
            "SAKURA_STORAGE_SECRET_KEY": "SECRET_REAL_KEY",
            "TRUSTED_PROXY_CIDRS": "127.0.0.1/32,10.0.0.0/8",
            "SMTP_HOST": "smtp.mailprovider.net",
            "SMTP_FROM_EMAIL": "noreply@sakura-app.net",
            "PUBLIC_APP_URL": "https://sakura-app.net",
            "GROQ_API_KEY": "gsk_live_key",
        }
        good_errors, _ = validate_env.validate_environment(good_env)
        self.assertEqual(good_errors, [], f"Expected zero validation errors, got: {good_errors}")


if __name__ == "__main__":
    unittest.main()
