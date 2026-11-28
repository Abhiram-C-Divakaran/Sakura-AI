"""
Sakura AI — Fail-Closed Security Regression Suite

Verifies that every security-sensitive operation denies execution rather than
silently falling back to insecure behavior when:
1. Required security configuration / production secrets are missing, default, or weak.
2. Credentials or service tokens are missing or invalid.
3. Required security dependencies (Redis rate-limit / capability nonce store) are unavailable.
4. Unauthorized operations (network exec without capability, replayed/mismatched capability,
   cross-user resource deletion/variation) are attempted.
5. Sandbox setup fails (Docker unavailable, volume unresolvable in clone/exec, invalid runtime).
6. Invalid execution requests (destructive command, traversal, missing/invalid workspace_id) arrive.
7. External sandbox service fails in production (connection error / HTTP 5xx).
"""

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_anime_ai.db")
os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException
from fastapi.testclient import TestClient

from auth.manager import AuthManager
from coding.capabilities import (
    CapabilityError,
    CapabilityMismatchError,
    CapabilityReplayError,
    CapabilityScopeError,
    clear_consumed_capabilities,
    consume_nonce,
    get_capability_signing_key,
    mint_sandbox_capability,
    verify_and_consume_capability,
)
from coding.sandbox import (
    RemoteHttpSandboxRuntime,
    SandboxManager,
    SandboxUnavailableError,
)
from coding.sandbox_service import app as sandbox_app
from config.settings import KNOWN_DEV_SECRETS, Settings
from database.db import Base, engine, get_db_context
from database.models import (
    BackgroundTask,
    Conversation,
    Document,
    GeneratedImage,
    RepositoryWorkspace,
    ScheduledTask,
    ScheduledTaskRun,
    User,
    utc_now,
)
from main import app as main_app
from services.rate_limit import enforce_rate_limit
from tasks.task_manager import execute_scheduled_task_job


def _make_user(db, prefix="fc_sec"):
    uid = uuid.uuid4()
    u = User(
        id=uid,
        username=f"{prefix}_{uid.hex[:8]}@example.com",
        email=f"{prefix}_{uid.hex[:8]}@example.com",
        hashed_password=AuthManager.hash_password("StrongPass123!"),
        created_at=utc_now(),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestFailClosedSecurityRegression(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.sandbox_client = TestClient(sandbox_app)
        cls.api_client = TestClient(main_app)

    def setUp(self):
        clear_consumed_capabilities()
        self.tmp_dir = tempfile.mkdtemp(prefix="sakura_fail_closed_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Missing / default / weak security configuration
    def test_settings_production_guards_reject_default_or_missing_capability_key_and_service_token(self):
        base_valid = {
            "ENVIRONMENT": "production",
            "JWT_SECRET": "a" * 40,
            "INTEGRATION_ENCRYPTION_KEY": "b" * 40,
            "SAKURA_SANDBOX_SERVICE_TOKEN": "c" * 32,
            "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY": "d" * 40,
        }
        # Baseline passes
        Settings(**base_valid).validate_production_guards()

        # Default hardcoded dev capability signing key MUST fail closed!
        with self.assertRaises(RuntimeError):
            bad_default = dict(base_valid)
            bad_default["SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY"] = "sakura_dev_capability_signing_key_32_chars_ok!"
            Settings(**bad_default).validate_production_guards()

        # Empty capability signing key MUST fail closed!
        with self.assertRaises(RuntimeError):
            bad_empty_cap = dict(base_valid)
            bad_empty_cap["SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY"] = ""
            Settings(**bad_empty_cap).validate_production_guards()

        # Missing sandbox service token MUST fail closed!
        with self.assertRaises(RuntimeError):
            bad_missing_tok = dict(base_valid)
            bad_missing_tok["SAKURA_SANDBOX_SERVICE_TOKEN"] = ""
            Settings(**bad_missing_tok).validate_production_guards()

        # Reused secret (cap key == jwt secret) MUST fail closed!
        with self.assertRaises(RuntimeError):
            bad_reuse = dict(base_valid)
            bad_reuse["SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY"] = base_valid["JWT_SECRET"]
            Settings(**bad_reuse).validate_production_guards()

    def test_capability_signing_key_fails_closed_in_production_for_missing_default_or_short(self):
        for bad_val in ("", "short_key_123", next(iter(KNOWN_DEV_SECRETS)), "sakura_dev_capability_signing_key_32_chars_ok!"):
            with patch.dict(
                os.environ,
                {"ENVIRONMENT": "production", "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY": bad_val},
                clear=False,
            ):
                with self.assertRaises(RuntimeError, msg=f"Production MUST reject signing key {bad_val!r}"):
                    get_capability_signing_key()

    def test_sandbox_readiness_fails_closed_in_production_when_secrets_missing(self):
        import coding.sandbox_service as ss
        ss._readiness_cache["last_check"] = 0.0
        ss._readiness_cache["result"] = None

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_SERVICE_TOKEN": "",
                "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY": "",
                "SAKURA_WORKSPACES_VOLUME": "",
            },
            clear=False,
        ):
            with patch("coding.sandbox_service.check_docker_status", return_value=(True, None)):
                with patch("coding.sandbox_service.check_redis_status", return_value=(True, None)):
                    res = self.sandbox_client.get("/readiness")
                    self.assertEqual(res.status_code, 503)
                    body = res.json()
                    self.assertFalse(body["ready"])
                    self.assertFalse(body["service_token_configured"])
                    self.assertFalse(body["capability_signing_key_configured"])

    # 2. Missing / invalid credentials
    async def test_remote_runtime_fails_closed_in_production_without_service_token(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "SAKURA_SANDBOX_SERVICE_TOKEN": ""}):
            rt = RemoteHttpSandboxRuntime(
                workspace_root=self.tmp_dir,
                service_url="http://127.0.0.1:9999",
                service_token="",
                workspace_id=str(uuid.uuid4()),
            )
            with self.assertRaises(SandboxUnavailableError):
                await rt.run_command("echo hi")
            with self.assertRaises(SandboxUnavailableError):
                await rt.clone_repository("https://github.com/octocat/Hello-World.git", "main", "cap")

    def test_sandbox_service_fails_closed_on_missing_server_token_in_production(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "SAKURA_SANDBOX_SERVICE_TOKEN": ""}):
            with patch("coding.sandbox_service.SERVICE_TOKEN", ""):
                resp = self.sandbox_client.post(
                    "/execute",
                    json={"command": "echo hi", "workspace_id": str(uuid.uuid4())},
                    headers={"X-Sandbox-Token": "any"},
                )
                self.assertEqual(resp.status_code, 500)

    # 3. Unavailable required security dependencies (Redis)
    def test_production_rate_limit_and_capability_nonce_fail_closed_when_redis_unavailable(self):
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "REDIS_URL": "redis://127.0.0.1:1/0",
                "SAKURA_DISABLE_RATE_LIMITS": "false",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as rl_ctx:
                enforce_rate_limit("auth_login", "1.2.3.4", limit=5, window_seconds=60, fail_closed_in_prod=True)
            self.assertEqual(rl_ctx.exception.status_code, 503)

            consumed = consume_nonce(uuid.uuid4().hex, expires_at=9999999999.0)
            self.assertFalse(consumed, "Production nonce store MUST fail closed when Redis is unreachable!")

    # 4. Unauthorized operations
    def test_capability_replay_wrong_workspace_wrong_command_and_wrong_scope_denied(self):
        ws_a = str(uuid.uuid4())
        ws_b = str(uuid.uuid4())
        key = "x" * 40
        tok = mint_sandbox_capability(
            workspace_id=ws_a,
            command="pip install pytest",
            scope="network_exec",
            ttl_seconds=60,
            secret_key=key,
        )
        # Wrong scope
        with self.assertRaises(CapabilityScopeError):
            verify_and_consume_capability(tok, expected_scope="repository_clone", expected_workspace_id=ws_a, expected_command="pip install pytest", secret_key=key)
        # Wrong workspace
        with self.assertRaises(CapabilityMismatchError):
            verify_and_consume_capability(tok, expected_scope="network_exec", expected_workspace_id=ws_b, expected_command="pip install pytest", secret_key=key)
        # Wrong command
        with self.assertRaises(CapabilityMismatchError):
            verify_and_consume_capability(tok, expected_scope="network_exec", expected_workspace_id=ws_a, expected_command="curl https://evil.example", secret_key=key)
        # First valid consumption succeeds
        with patch("coding.capabilities._consume_nonce_redis", return_value=None):
            verify_and_consume_capability(tok, expected_scope="network_exec", expected_workspace_id=ws_a, expected_command="pip install pytest", secret_key=key)
            # Replay MUST fail closed
            with self.assertRaises(CapabilityReplayError):
                verify_and_consume_capability(tok, expected_scope="network_exec", expected_workspace_id=ws_a, expected_command="pip install pytest", secret_key=key)

    def test_cross_user_document_delete_and_image_variation_are_denied(self):
        with get_db_context() as db:
            user_a = _make_user(db, "owner_a")
            user_b = _make_user(db, "intruder_b")
            doc_id = uuid.uuid4()
            img_id = uuid.uuid4()
            db.add(Document(id=doc_id, user_id=user_a.id, filename="priv.txt", mime_type="text/plain", storage_path="/tmp/priv.txt"))
            db.add(Document(id=img_id, user_id=user_a.id, filename="priv.png", mime_type="image/png", storage_path="/tmp/priv.png"))
            db.add(
                GeneratedImage(
                    id=img_id,
                    user_id=user_a.id,
                    document_id=img_id,
                    prompt="Private artwork",
                    enhanced_prompt="Private artwork",
                    aspect_ratio="1:1",
                    width=1024,
                    height=1024,
                    model="flux",
                    storage_path="/tmp/priv.png",
                    image_url=f"/api/v1/library/files/{img_id}/download",
                )
            )
            db.commit()
            tok_b = AuthManager.create_access_token({"sub": user_b.username})

        hdr_b = {"Authorization": f"Bearer {tok_b}"}
        r_del = self.api_client.delete(f"/api/v1/library/files/{doc_id}", headers=hdr_b)
        self.assertEqual(r_del.status_code, 404)

        r_var = self.api_client.post(
            "/api/v1/images/variation",
            headers=hdr_b,
            json={"parent_image_id": str(img_id), "count": 2, "idempotency_key": f"xuser-{uuid.uuid4().hex[:8]}"},
        )
        self.assertEqual(r_var.status_code, 404)

    # 5. Sandbox setup failures & invalid runtime names
    def test_invalid_sandbox_runtime_name_fails_closed(self):
        for bad_rt in ("local", "dockr", "remtoe", "unsafe_host"):
            with patch.dict(os.environ, {"ENVIRONMENT": "development", "SAKURA_SANDBOX_RUNTIME": bad_rt}):
                with self.assertRaises(SandboxUnavailableError, msg=f"Invalid runtime {bad_rt!r} must fail closed"):
                    SandboxManager.get_runtime(self.tmp_dir)

    def test_clone_repository_fails_closed_when_volume_unresolved_in_production(self):
        ws_id = str(uuid.uuid4())
        tok = "prod_clone_svc_token_1234567890"
        cap_key = "k" * 40
        repo_url = "https://github.com/octocat/Hello-World.git"
        clone_cmd = ["git", "clone", "--depth", "1", "--branch", "main", repo_url, "."]
        cap = mint_sandbox_capability(
            workspace_id=ws_id,
            command=clone_cmd,
            scope="repository_clone",
            repository_url=repo_url,
            branch="main",
            secret_key=cap_key,
        )
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_SERVICE_TOKEN": tok,
                "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY": cap_key,
                "SAKURA_WORKSPACES_VOLUME": "sakura_workspaces",
            },
            clear=False,
        ):
            with patch("coding.sandbox_service.WORKSPACE_ROOT", self.tmp_dir):
                with patch("coding.sandbox_service.check_docker_operational", return_value=True):
                    with patch("coding.sandbox_service.get_volume_host_mountpoint", return_value=None):
                        with patch("coding.capabilities._consume_nonce_redis", return_value=True):
                            resp = self.sandbox_client.post(
                                f"/workspaces/{ws_id}/clone",
                                headers={"X-Sandbox-Token": tok},
                                json={"repository_url": repo_url, "branch": "main", "capability_token": cap},
                            )
                            self.assertEqual(resp.status_code, 200)
                            body = resp.json()
                            self.assertFalse(body["success"])
                            self.assertTrue(body.get("isolation_unavailable"))
                            self.assertIn("Volume resolution failure", body["stderr"])

    # 6. Invalid execution requests
    def test_sandbox_execute_blocks_missing_workspace_id_and_invalid_uuid_in_production(self):
        tok = "prod_exec_svc_token_1234567890"
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "SAKURA_SANDBOX_SERVICE_TOKEN": tok}):
            r_no_ws = self.sandbox_client.post(
                "/execute",
                headers={"X-Sandbox-Token": tok},
                json={"command": "echo hi"},
            )
            self.assertEqual(r_no_ws.status_code, 200)
            self.assertFalse(r_no_ws.json()["success"])
            self.assertTrue(r_no_ws.json()["blocked"])

            r_bad_uuid = self.sandbox_client.post(
                "/execute",
                headers={"X-Sandbox-Token": tok},
                json={"command": "echo hi", "workspace_id": "../../etc"},
            )
            self.assertEqual(r_bad_uuid.status_code, 200)
            self.assertFalse(r_bad_uuid.json()["success"])
            self.assertTrue(r_bad_uuid.json()["blocked"])

    # 7. External service failure in production
    async def test_remote_runtime_external_service_failure_fails_closed_in_production(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            rt = RemoteHttpSandboxRuntime(
                workspace_root=self.tmp_dir,
                service_url="http://127.0.0.1:1",
                service_token="valid_prod_token_1234567890",
                workspace_id=str(uuid.uuid4()),
            )
            with self.assertRaises(SandboxUnavailableError):
                await rt.run_command("echo hi", timeout_seconds=1)
            with self.assertRaises(SandboxUnavailableError):
                await rt.clone_repository("https://github.com/octocat/Hello-World.git", "main", "cap", timeout_seconds=1)

    # 8. Cross-user scheduled task execution & internal task type forging denied
    async def test_cross_user_scheduled_task_execution_and_internal_task_submission_denied(self):
        with get_db_context() as db:
            user_a = _make_user(db, "sched_owner_a")
            user_b = _make_user(db, "sched_intruder_b")
            st = ScheduledTask(
                id=uuid.uuid4(),
                user_id=user_a.id,
                title="Private Owner Report",
                prompt="Summarize confidential Q4 revenue numbers",
                schedule="every day at 9am",
                enabled=True,
                created_at=utc_now(),
            )
            db.add(st)
            db.flush()
            run = ScheduledTaskRun(
                id=uuid.uuid4(),
                task_id=st.id,
                status="QUEUED",
                scheduled_for=utc_now(),
            )
            db.add(run)
            bg_b = BackgroundTask(
                id=uuid.uuid4(),
                user_id=user_b.id,
                type="scheduled_run",
                title="Forged cross-user run",
                status="Queued",
                payload={"scheduled_task_id": str(st.id), "run_id": str(run.id)},
                created_at=utc_now(),
            )
            db.add(bg_b)
            db.commit()
            user_b_id = user_b.id
            st_id = st.id
            run_id = run.id
            bg_b_id = bg_b.id
            tok_b = AuthManager.create_access_token({"sub": user_b.username})

        hdr_b = {"Authorization": f"Bearer {tok_b}"}
        # HTTP API MUST reject internal-only task types
        for forbidden_type in ("scheduled_run", "document_index", "user_data_export", "arbitrary_unknown"):
            resp = self.api_client.post(
                "/api/v1/tasks",
                headers=hdr_b,
                json={
                    "type": forbidden_type,
                    "title": "Forged task",
                    "payload": {"scheduled_task_id": str(st_id), "run_id": str(run_id)},
                },
            )
            self.assertEqual(resp.status_code, 400, f"POST /api/v1/tasks MUST reject {forbidden_type!r}")

        # Even if a cross-user BackgroundTask exists in DB, execute_scheduled_task_job MUST fail closed
        class _FailIfCalledRouter:
            called = False

            def get_provider(self, *_args, **_kwargs):
                self.called = True
                raise AssertionError("LLM provider must never be called for unauthorized scheduled task")

        fake_router = _FailIfCalledRouter()
        await execute_scheduled_task_job(
            bg_b_id,
            user_b_id,
            {"scheduled_task_id": str(st_id), "run_id": str(run_id)},
            fake_router,
        )
        self.assertFalse(fake_router.called)

        with get_db_context() as db:
            run_after = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.id == run_id).first()
            bg_after = db.query(BackgroundTask).filter(BackgroundTask.id == bg_b_id).first()
            self.assertEqual(run_after.status, "QUEUED")
            self.assertIsNone(run_after.output)
            self.assertEqual(bg_after.status, "Failed")
            self.assertIn("access denied", (bg_after.error or "").lower())

    # 9. /chat/stream coding route uses atomic quota enforcement inside create_and_enqueue_coding_job
    def test_chat_stream_coding_route_enforces_quota_atomically(self):
        with get_db_context() as db:
            user = _make_user(db, "chat_code_quota")
            conv = Conversation(
                id=uuid.uuid4(),
                user_id=user.id,
                title="Coding Quota Test",
                created_at=utc_now(),
            )
            ws = RepositoryWorkspace(
                id=uuid.uuid4(),
                user_id=user.id,
                name="demo-repo",
                repository_url="https://github.com/octocat/Hello-World.git",
                active_branch="main",
                workspace_path=os.path.join(self.tmp_dir, "demo-repo"),
                status="READY",
                created_at=utc_now(),
            )
            os.makedirs(ws.workspace_path, exist_ok=True)
            db.add(conv)
            db.add(ws)
            db.commit()
            conv_id = str(conv.id)
            tok = AuthManager.create_access_token({"sub": user.username})

        captured = {}
        quota_resources = []

        def _fake_create_and_enqueue(**kwargs):
            captured.update(kwargs)
            raise HTTPException(status_code=429, detail="Daily quota exceeded for coding_task")

        def _spy_enforce_quota(_db, _uid, resource, *args, **kwargs):
            quota_resources.append(resource)
            if resource == "coding_task":
                raise AssertionError("Must not pre-charge coding_task quota outside create_and_enqueue_coding_job")

        with patch("coding.job_worker.create_and_enqueue_coding_job", side_effect=_fake_create_and_enqueue):
            with patch("services.quotas.enforce_user_quota", side_effect=_spy_enforce_quota):
                res = self.api_client.post(
                    "/api/v1/chat/stream",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={
                        "conversation_id": conv_id,
                        "message": "/code fix the unit test",
                        "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                    },
                )
                self.assertEqual(res.status_code, 429)
                self.assertTrue(captured.get("enforce_quota"), "chat/stream must pass enforce_quota=True")
                self.assertNotIn("coding_task", quota_resources)

    # 10. Audio transcribe rejects oversized uploads (HTTP 413) & unsafe extensions (HTTP 400)
    def test_audio_transcribe_enforces_size_limit_and_extension_allowlist(self):
        from io import BytesIO
        with get_db_context() as db:
            user = _make_user(db, "audio_sec")
            tok = AuthManager.create_access_token({"sub": user.username})
        hdr = {"Authorization": f"Bearer {tok}"}

        # Path-traversal / non-audio extension MUST be rejected with HTTP 400
        for bad_name in ("evil.py", "payload.sh", "clip.wav/../../escape.txt"):
            r_bad = self.api_client.post(
                "/api/v1/audio/transcribe",
                headers=hdr,
                files={"file": (bad_name, BytesIO(b"RIFF....WAVE"), "audio/wav")},
            )
            self.assertEqual(r_bad.status_code, 400, f"Unsafe filename {bad_name!r} must be rejected")

        # Oversized audio upload MUST be rejected with HTTP 413 via streaming cap
        with patch("api.audio.MAX_AUDIO_UPLOAD_BYTES", 64):
            r_big = self.api_client.post(
                "/api/v1/audio/transcribe",
                headers=hdr,
                files={"file": ("voice.webm", BytesIO(b"A" * 128), "audio/webm")},
            )
            self.assertEqual(r_big.status_code, 413)

    # 11. Manual scheduled task trigger enforces daily scheduled_job quota
    def test_manual_scheduled_task_run_enforces_daily_quota(self):
        with get_db_context() as db:
            user = _make_user(db, "sched_quota")
            st = ScheduledTask(
                id=uuid.uuid4(),
                user_id=user.id,
                title="Quota Checked Task",
                prompt="Generate daily summary",
                schedule="every day at 9am",
                enabled=True,
                created_at=utc_now(),
            )
            db.add(st)
            db.commit()
            st_id = str(st.id)
            tok = AuthManager.create_access_token({"sub": user.username})
        hdr = {"Authorization": f"Bearer {tok}"}

        with patch.dict(os.environ, {"SAKURA_QUOTA_SCHEDULED_DAILY": "1"}, clear=False):
            r1 = self.api_client.post(f"/api/v1/scheduled/{st_id}/run", headers=hdr)
            self.assertEqual(r1.status_code, 202)
            r2 = self.api_client.post(f"/api/v1/scheduled/{st_id}/run", headers=hdr)
            self.assertEqual(r2.status_code, 429)

    # 12. Chat agent reads attached document previews via StorageBackend (S3-safe, no local-path assumption)
    async def test_chat_agent_loads_attachment_from_storage_backend(self):
        from llm.agent import Agent
        from llm.router import LLMRouter

        with get_db_context() as db:
            user = _make_user(db, "s3_attach")
            doc_id = uuid.uuid4()
            storage_key = f"users/{user.id}/documents/{doc_id}/brief.txt"
            doc = Document(
                id=doc_id,
                user_id=user.id,
                filename="brief.txt",
                mime_type="text/plain",
                storage_backend="s3",
                storage_key=storage_key,
                storage_path=storage_key,  # Intentionally non-existent on local disk
            )
            db.add(doc)
            db.commit()

            class _FakeS3Backend:
                def exists(self, key):
                    return key == storage_key

                def get_bytes(self, key):
                    assert key == storage_key
                    return b"S3_CONFIDENTIAL_PROJECT_NOTES_12345"

            captured_messages = []

            class _FakeProvider:
                async def tool_turn(self, messages, **_kwargs):
                    captured_messages.extend(messages)
                    return {"content": "ok", "tool_calls": []}

                async def stream_generate(self, **_kwargs):
                    yield "ok"

            fake_router = LLMRouter()
            with patch("services.storage.get_storage_backend", return_value=_FakeS3Backend()):
                with patch.object(fake_router, "get_provider", return_value=("fake", _FakeProvider())):
                    loop = Agent(
                        db=db,
                        user_id=user.id,
                        llm_router=fake_router,
                        system_prompt="You are Sakura.",
                        history=[],
                        attachments=[{"id": str(doc_id), "filename": "brief.txt"}],
                    )
                    tokens = []
                    async for chunk in loop.run_stream("Summarize my attachment"):
                        tokens.append(chunk)

            self.assertTrue(captured_messages, "Expected system prompt sent to provider")
            self.assertIn("S3_CONFIDENTIAL_PROJECT_NOTES_12345", captured_messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
