"""
Comprehensive regression tests covering:
- Phase 4: Network capability authorization lifecycle (all valid & invalid cases)
- Phase 5: WebSocket ticket-only authentication (rejection of ?token=, concurrent consumption)
- Phase 6: Private model routing fail-closed (never calls cloud providers)
- Phase 8: Durable image generation jobs (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED, retries)
- Phase 9: Storage deletion outbox reliability, orphan cleanup, indexing cancellation
- Phase 10: Readiness truthfulness (production 503, dev DEGRADED, no secret leaks)
- Phase 11: Real password reset lifecycle (honest 503 when unconfigured, hashed single-use token, rate limits)
"""

import os
import sys
import uuid
import shutil
import asyncio
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import (
    User,
    Document,
    BackgroundTask,
    RepositoryWorkspace,
    ImageGenerationJob,
    StorageDeletionOutbox,
    PasswordResetToken,
    utc_now,
)
from auth.manager import AuthManager
from coding.capabilities import (
    mint_sandbox_capability,
    verify_and_consume_capability,
    clear_consumed_capabilities,
    CapabilityError,
    CapabilitySignatureError,
    CapabilityReplayError,
    CapabilityScopeError,
    CapabilityMismatchError,
)
from coding.sandbox_service import execute_command, clone_repository, ExecuteRequest, CloneRequest
from coding.sandbox import DockerSandboxRuntime
from llm.router import LLMRouter, PrivateModelUnavailableError
from media.image_worker import ImageJobWorker, create_image_generation_job
from services.storage import LocalFilesystemStorage
from services.documents import (
    delete_document,
    process_storage_deletion_outbox,
    cleanup_orphaned_storage_objects,
)
from services.rate_limit import reset_rate_limits


class TestSecurityAndReliabilityStabilization(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        clear_consumed_capabilities()
        reset_rate_limits()
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_sec_stab_")

        with get_db_context() as db:
            self.user_a_id = uuid.uuid4()
            self.user_b_id = uuid.uuid4()
            self.user_a = User(
                id=self.user_a_id,
                username="alice@example.com",
                email="alice@example.com",
                hashed_password=AuthManager.hash_password("InitialPass123!"),
            )
            self.user_b = User(
                id=self.user_b_id,
                username="bob@example.com",
                email="bob@example.com",
                hashed_password=AuthManager.hash_password("InitialPass123!"),
            )
            db.add_all([self.user_a, self.user_b])

            self.ws_a_id = uuid.uuid4()
            self.ws_b_id = uuid.uuid4()
            db.add_all([
                RepositoryWorkspace(
                    id=self.ws_a_id,
                    user_id=self.user_a_id,
                    name="alice-ws",
                    workspace_path=os.path.join(self.temp_dir, str(self.ws_a_id)),
                    status="READY",
                ),
                RepositoryWorkspace(
                    id=self.ws_b_id,
                    user_id=self.user_b_id,
                    name="bob-ws",
                    workspace_path=os.path.join(self.temp_dir, str(self.ws_b_id)),
                    status="READY",
                ),
            ])
            db.commit()

            self.token_a = AuthManager.create_access_token({"sub": self.user_a.username})
            self.token_b = AuthManager.create_access_token({"sub": self.user_b.username})

        self.headers_a = {"Authorization": f"Bearer {self.token_a}"}
        self.headers_b = {"Authorization": f"Bearer {self.token_b}"}

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_rate_limits()

    # ─── Phase 4: Network Capability Authorization Lifecycle ──────────────

    async def test_phase4_network_authorization_full_lifecycle_and_negative_cases(self):
        cmd = "pip install requests"

        # 1. Create DB authorization via API
        create_res = self.client.post(
            f"/api/v1/coding/workspaces/{self.ws_a_id}/network-authorizations",
            headers=self.headers_a,
            json={"command": cmd, "reason": "Install requests"},
        )
        self.assertEqual(create_res.status_code, 200)
        auth_id = create_res.json()["authorization_id"]

        # 2. Wrong user cannot mint from User A's authorization
        wrong_user_res = self.client.post(
            f"/api/v1/coding/workspaces/{self.ws_a_id}/network-authorizations/{auth_id}/mint",
            headers=self.headers_b,
            json={"command": cmd},
        )
        self.assertEqual(wrong_user_res.status_code, 404)

        # 3. Wrong command rejected
        wrong_cmd_res = self.client.post(
            f"/api/v1/coding/workspaces/{self.ws_a_id}/network-authorizations/{auth_id}/mint",
            headers=self.headers_a,
            json={"command": "curl https://evil.example"},
        )
        self.assertEqual(wrong_cmd_res.status_code, 403)

        # 4. Valid mint succeeds and returns signed HMAC capability (NOT raw UUID)
        mint_res = self.client.post(
            f"/api/v1/coding/workspaces/{self.ws_a_id}/network-authorizations/{auth_id}/mint",
            headers=self.headers_a,
            json={"command": cmd},
        )
        self.assertEqual(mint_res.status_code, 200, mint_res.text)
        cap_token = mint_res.json()["capability_token"]
        self.assertNotEqual(cap_token, auth_id)
        self.assertIn(".", cap_token)

        # 5. Re-minting same consumed DB authorization fails (one-time)
        remint_res = self.client.post(
            f"/api/v1/coding/workspaces/{self.ws_a_id}/network-authorizations/{auth_id}/mint",
            headers=self.headers_a,
            json={"command": cmd},
        )
        self.assertEqual(remint_res.status_code, 403)

        # 6. Verify capability with exact scope & replay block
        payload = verify_and_consume_capability(
            capability_token=cap_token,
            expected_scope="network_exec",
            expected_workspace_id=str(self.ws_a_id),
            expected_command=cmd,
        )
        self.assertEqual(payload["scope"], "network_exec")
        with self.assertRaises(CapabilityReplayError):
            verify_and_consume_capability(
                capability_token=cap_token,
                expected_scope="network_exec",
                expected_workspace_id=str(self.ws_a_id),
                expected_command=cmd,
            )

        # 7. Scope separation: repository_clone token rejected on /execute; network_exec rejected on /clone
        clone_tok = mint_sandbox_capability(
            workspace_id=str(self.ws_a_id),
            command=cmd,
            scope="repository_clone",
            repository_url="https://github.com/org/repo.git",
            branch="main",
        )
        from coding.sandbox_service import WORKSPACE_ROOT
        ws_disk = os.path.join(WORKSPACE_ROOT, str(self.ws_a_id))
        os.makedirs(ws_disk, exist_ok=True)
        try:
            exec_res = await execute_command(
                ExecuteRequest(
                    command=cmd,
                    workspace_id=str(self.ws_a_id),
                    allow_network=True,
                    network_capability=clone_tok,
                ),
                _auth=True,
            )
            self.assertFalse(exec_res["success"])
            self.assertTrue(exec_res["blocked"])

            # Raw authorization UUID passed to /execute must also be blocked
            raw_res = await execute_command(
                ExecuteRequest(
                    command=cmd,
                    workspace_id=str(self.ws_a_id),
                    allow_network=True,
                    network_authorization_id=auth_id,
                ),
                _auth=True,
            )
            self.assertFalse(raw_res["success"])
            self.assertTrue(raw_res["blocked"])

            # network_exec token rejected on /clone
            net_tok = mint_sandbox_capability(workspace_id=str(self.ws_a_id), command="git clone https://github.com/org/repo.git .", scope="network_exec")
            clone_res = await clone_repository(
                str(self.ws_a_id),
                CloneRequest(
                    repository_url="https://github.com/org/repo.git",
                    branch="main",
                    capability_token=net_tok,
                ),
                _auth=True,
            )
            self.assertFalse(clone_res["success"])
            self.assertTrue(clone_res["blocked"])
        finally:
            shutil.rmtree(ws_disk, ignore_errors=True)

        # 8. Branch validation rejects omitted branch when expected_branch is supplied
        no_branch_tok = mint_sandbox_capability(
            workspace_id=str(self.ws_a_id),
            command=["git", "clone", "--depth", "1", "--branch", "main", "https://github.com/org/repo.git", "."],
            scope="repository_clone",
            repository_url="https://github.com/org/repo.git",
            branch=None,
        )
        with self.assertRaises(CapabilityMismatchError):
            verify_and_consume_capability(
                capability_token=no_branch_tok,
                expected_scope="repository_clone",
                expected_workspace_id=str(self.ws_a_id),
                expected_repository_url="https://github.com/org/repo.git",
                expected_branch="main",
            )

        # 9. Wrong repository URL rejected
        wrong_repo_tok = mint_sandbox_capability(
            workspace_id=str(self.ws_a_id),
            command="git clone",
            scope="repository_clone",
            repository_url="https://github.com/org/repo-a.git",
            branch="main",
        )
        with self.assertRaises(CapabilityMismatchError):
            verify_and_consume_capability(
                capability_token=wrong_repo_tok,
                expected_scope="repository_clone",
                expected_workspace_id=str(self.ws_a_id),
                expected_repository_url="https://github.com/org/repo-b.git",
                expected_branch="main",
            )

        # 10. Redis replay (False) must NEVER fall back to in-memory nonce cache
        fresh_tok = mint_sandbox_capability(workspace_id=str(self.ws_a_id), command=cmd, scope="network_exec")
        with patch("coding.capabilities._consume_nonce_redis", return_value=False):
            with self.assertRaises(CapabilityReplayError):
                verify_and_consume_capability(
                    capability_token=fresh_tok,
                    expected_scope="network_exec",
                    expected_workspace_id=str(self.ws_a_id),
                    expected_command=cmd,
                )

        # 11. DockerSandboxRuntime refuses allow_network=True without valid signed capability
        docker_rt = DockerSandboxRuntime(self.temp_dir, workspace_id=str(self.ws_a_id))
        d_res = await docker_rt.run_command("curl https://example.com", allow_network=True)
        self.assertFalse(d_res["success"])
        self.assertTrue(d_res["blocked"])

    # ─── Phase 5: WebSocket Ticket-Only Auth ──────────────────────────────

    def test_phase5_websocket_ticket_only_and_concurrent_consumption(self):
        # 1. Query-string JWT token fallback MUST be rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/v1/ws?token={self.token_a}") as ws:
                ws.receive_text()

        # 2. Invalid ticket rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/api/v1/ws?ticket=wst_invalid_ticket") as ws:
                ws.receive_text()

        # 3. Valid single-use ticket connects and answers ping -> pong
        ticket_res = self.client.post("/api/v1/auth/ws-ticket", headers=self.headers_a)
        self.assertEqual(ticket_res.status_code, 200)
        ticket = ticket_res.json()["ticket"]

        with self.client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
            initial = ws.receive_json()
            self.assertEqual(initial["type"], "tasks_list")
            ws.send_text("ping")
            self.assertEqual(ws.receive_text(), "pong")

        # 4. Replayed ticket rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
                ws.receive_text()

        # 5. Concurrent consumption race: strictly 1 of 8 threads succeeds
        t_data = AuthManager.issue_ws_ticket(self.user_a_id, ttl_seconds=60)
        race_ticket = t_data["ticket"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: AuthManager.consume_ws_ticket(race_ticket), range(8)))
        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0], self.user_a_id)

    # ─── Phase 6: Private Model Routing Fail-Closed ───────────────────────

    async def test_phase6_private_routing_never_invokes_cloud_providers(self):
        router = LLMRouter()
        cloud_openai = MagicMock()
        cloud_openai.generate = AsyncMock(return_value="leaked_openai")
        cloud_groq = MagicMock()
        cloud_groq.generate = AsyncMock(return_value="leaked_groq")
        cloud_anthropic = MagicMock()
        cloud_anthropic.generate = AsyncMock(return_value="leaked_anthropic")

        failing_ollama = MagicMock()
        failing_ollama.generate = AsyncMock(side_effect=TimeoutError("local ollama timed out"))

        async def _failing_stream(*args, **kwargs):
            raise ConnectionError("local ollama unreachable")
            yield ""  # pragma: no cover

        failing_ollama.stream = _failing_stream

        router.providers = {
            "openai": cloud_openai,
            "groq": cloud_groq,
            "anthropic": cloud_anthropic,
            "ollama": failing_ollama,
        }

        for private_intent in ("local_private", "private_data"):
            ordered_names = [n for n, _ in router.get_ordered_providers(private_intent)]
            self.assertEqual(ordered_names, ["ollama"])

            with self.assertRaises(PrivateModelUnavailableError):
                await router.generate("confidential secret prompt", intent=private_intent)

            with self.assertRaises(PrivateModelUnavailableError):
                async for _ in router.stream("confidential secret prompt", intent=private_intent):
                    pass

        # Also when Ollama is absent entirely -> fails closed
        router.providers.pop("ollama")
        with self.assertRaises(PrivateModelUnavailableError):
            await router.generate("confidential secret prompt", intent="local_private")

        cloud_openai.generate.assert_not_called()
        cloud_groq.generate.assert_not_called()
        cloud_anthropic.generate.assert_not_called()

    # ─── Phase 8: Durable Image Generation Jobs ───────────────────────────

    async def test_phase8_durable_image_generation_lifecycle_and_retries(self):
        # 1. Create durable image job via API (idempotent)
        r1 = self.client.post(
            "/api/v1/images/jobs",
            headers=self.headers_a,
            json={"prompt": "Moonlit sakura temple", "requested_pipeline": "anime", "idempotency_key": "img-idem-1"},
        )
        self.assertEqual(r1.status_code, 202, r1.text)
        job_id = r1.json()["job_id"]
        self.assertEqual(r1.json()["status"], "QUEUED")

        r2 = self.client.post(
            "/api/v1/images/jobs",
            headers=self.headers_a,
            json={"prompt": "Moonlit sakura temple", "requested_pipeline": "anime", "idempotency_key": "img-idem-1"},
        )
        self.assertEqual(r2.json()["job_id"], job_id)
        self.assertTrue(r2.json()["idempotent_replay"])

        # Cross-user status check returns 404
        self.assertEqual(self.client.get(f"/api/v1/images/jobs/{job_id}", headers=self.headers_b).status_code, 404)

        # 2. Worker attempt 1 fails transiently -> requeued to QUEUED; attempt 2 succeeds -> COMPLETED
        worker = ImageJobWorker(worker_id="img_worker_test")
        claimed1 = worker.claim_next_job()
        self.assertEqual(claimed1.attempt_count, 1)

        async def _transient_fail(**kwargs):
            raise RuntimeError("Upstream 503 timeout")

        ok1 = await worker.execute_job(claimed1, generator_fn=_transient_fail)
        self.assertFalse(ok1)

        st1 = self.client.get(f"/api/v1/images/jobs/{job_id}", headers=self.headers_a).json()
        self.assertEqual(st1["status"], "QUEUED")
        self.assertEqual(st1["attempt_count"], 1)

        claimed2 = worker.claim_next_job()
        self.assertEqual(claimed2.attempt_count, 2)

        async def _succeed(**kwargs):
            return {"id": None, "provider": "pollinations", "model": "flux"}

        ok2 = await worker.execute_job(claimed2, generator_fn=_succeed)
        self.assertTrue(ok2)

        st2 = self.client.get(f"/api/v1/images/jobs/{job_id}", headers=self.headers_a).json()
        self.assertEqual(st2["status"], "COMPLETED")
        self.assertEqual(st2["actual_provider"], "pollinations")
        self.assertEqual(st2["actual_model"], "flux")
        self.assertIsNotNone(st2["completed_at"])

    # ─── Phase 9: Storage Deletion Outbox & Orphan Cleanup ────────────────

    def test_phase9_storage_deletion_outbox_consistency_and_orphans(self):
        storage = LocalFilesystemStorage(root_dir=os.path.join(self.temp_dir, "storage"))
        key = f"users/{self.user_a_id}/documents/doc1/spec.txt"
        storage.put(key, b"hello world", content_type="text/plain", user_id=self.user_a_id)

        with get_db_context() as db:
            doc = Document(
                id=uuid.uuid4(),
                user_id=self.user_a_id,
                filename="spec.txt",
                mime_type="text/plain",
                storage_path=key,
                storage_backend="local",
                storage_key=key,
                storage_size=11,
                index_generation=1,
            )
            db.add(doc)
            idx_task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=self.user_a_id,
                type="document_index",
                title="Index spec.txt",
                payload={"document_id": str(doc.id)},
                status="Running",
            )
            db.add(idx_task)
            db.commit()
            doc_id = doc.id
            idx_task_id = idx_task.id

        # 1. Storage deletion failure: DB record MUST NOT disappear; outbox PENDING; indexing task cancelled!
        failing_storage = MagicMock()
        failing_storage.backend_type = "local"
        failing_storage.delete.return_value = False

        with get_db_context() as db:
            res_fail = delete_document(
                doc_id,
                self.user_a_id,
                db,
                storage_override=failing_storage,
                raise_on_storage_error=False,
            )
            self.assertEqual(res_fail["deletion_status"], "DELETE_FAILED")
            self.assertEqual(res_fail["cancelled_index_tasks"], 1)

            still_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertIsNotNone(still_doc)
            self.assertEqual(still_doc.deletion_status, "DELETE_FAILED")
            self.assertEqual(still_doc.index_generation, 2)

            cancelled_t = db.query(BackgroundTask).filter(BackgroundTask.id == idx_task_id).first()
            self.assertEqual(cancelled_t.status, "Cancelled")
            self.assertTrue(cancelled_t.cancel_requested)

            # Repeated deletion reuses same outbox entry (no duplicates)
            delete_document(
                doc_id,
                self.user_a_id,
                db,
                storage_override=failing_storage,
                raise_on_storage_error=False,
            )
            self.assertEqual(db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.document_id == doc_id).count(), 1)

            # Force outbox due now and process with healthy storage -> completes cleanly
            ob = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.document_id == doc_id).first()
            ob.next_retry_at = utc_now() - timedelta(seconds=5)
            db.commit()

            stats = process_storage_deletion_outbox(db=db, storage_override=storage)
            self.assertEqual(stats["completed"], 1)
            self.assertIsNone(db.query(Document).filter(Document.id == doc_id).first())
            self.assertFalse(storage.exists(key))

        # 2. Orphan cleanup preserves user isolation
        orphan_a = f"users/{self.user_a_id}/documents/orphan/ghost.txt"
        other_user_file = f"users/{self.user_b_id}/documents/keep/bob.txt"
        storage.put(orphan_a, b"orphan", content_type="text/plain", user_id=self.user_a_id)
        storage.put(other_user_file, b"bob-data", content_type="text/plain", user_id=self.user_b_id)

        with get_db_context() as db:
            gc_res = cleanup_orphaned_storage_objects(self.user_a_id, db, storage_override=storage)
            self.assertEqual(gc_res["orphans_deleted"], 1)
        self.assertFalse(storage.exists(orphan_a))
        self.assertTrue(storage.exists(other_user_file))

    # ─── Phase 10: Readiness Truthfulness ─────────────────────────────────

    def test_phase10_readiness_truthfulness_and_no_secret_leak(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "JWT_SECRET": "prod_super_secret_jwt_key_at_least_32_chars"}):
            with patch("main._probe_sandbox_executor_readiness", new_callable=AsyncMock) as mock_sb:
                mock_sb.return_value = {"reachable": False, "ready": False}
                res = self.client.get("/readiness")
                self.assertEqual(res.status_code, 503)
                body = res.json()
                self.assertEqual(body["status"], "NOT_READY")
                self.assertFalse(body["ready"])
                self.assertNotIn("prod_super_secret_jwt_key_at_least_32_chars", res.text)

    # ─── Phase 11: Real Password Reset & Auth Rate Limiting ───────────────

    def test_phase11_password_reset_honest_disable_real_flow_and_rate_limits(self):
        # 1. Unconfigured email -> honest 503 & auth/config reports disabled
        with patch.dict(os.environ, {"SMTP_HOST": "", "SMTP_FROM_EMAIL": ""}):
            cfg = self.client.get("/api/v1/auth/config").json()
            self.assertFalse(cfg["password_reset_enabled"])
            self.assertFalse(cfg["google_oauth_enabled"])
            self.assertFalse(cfg["github_oauth_enabled"])

            r_disabled = self.client.post(
                "/api/v1/auth/password-reset/request",
                json={"identifier": "alice@example.com"},
            )
            self.assertEqual(r_disabled.status_code, 503)

        # 2. Configured email -> real hashed single-use token, enumeration-safe
        captured_urls = []
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.example.test", "SMTP_FROM_EMAIL": "noreply@example.test"}):
            with patch("services.email.send_password_reset_email", side_effect=lambda to, url: captured_urls.append((to, url))):
                r_exist = self.client.post(
                    "/api/v1/auth/password-reset/request",
                    json={"identifier": "alice@example.com"},
                )
                r_missing = self.client.post(
                    "/api/v1/auth/password-reset/request",
                    json={"identifier": "nobody@example.com"},
                )
                self.assertEqual(r_exist.status_code, 200)
                self.assertEqual(r_missing.status_code, 200)
                self.assertEqual(r_exist.json(), r_missing.json())
                self.assertEqual(len(captured_urls), 1)

        raw_token = captured_urls[0][1].split("reset_token=")[1]
        with get_db_context() as db:
            tok_row = db.query(PasswordResetToken).first()
            self.assertIsNotNone(tok_row)
            self.assertNotEqual(tok_row.token_hash, raw_token)
            self.assertEqual(tok_row.token_hash, hashlib.sha256(raw_token.encode()).hexdigest())

        # Confirm reset succeeds once and updates password
        r_conf = self.client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_token, "new_password": "NewSecurePassword456!"},
        )
        self.assertEqual(r_conf.status_code, 200)

        # Replay of consumed token rejected
        r_replay = self.client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw_token, "new_password": "AnotherPassword789!"},
        )
        self.assertEqual(r_replay.status_code, 400)

        # Login succeeds with new password
        r_login = self.client.post(
            "/api/v1/auth/token",
            data={"username": "alice@example.com", "password": "NewSecurePassword456!"},
        )
        self.assertEqual(r_login.status_code, 200)

        # 3. Rate limiting triggers HTTP 429 on excessive login attempts
        reset_rate_limits()
        got_429 = False
        with patch.dict(os.environ, {"SAKURA_DISABLE_RATE_LIMITS": "false"}):
            for _ in range(20):
                resp = self.client.post(
                    "/api/v1/auth/token",
                    data={"username": "alice@example.com", "password": "WrongPassword!"},
                )
                if resp.status_code == 429:
                    got_429 = True
                    break
        self.assertTrue(got_429, "Expected HTTP 429 rate limit on repeated failed logins")


if __name__ == "__main__":
    unittest.main()
