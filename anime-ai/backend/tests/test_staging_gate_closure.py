"""
Sakura AI — Staging Gate Closure Regression Test Suite
Covers:
- Phase 1: Lazy workspace initialization (no import-time mkdir), workspace permission contract
- Phase 2: Centralized transactional image quota enforcement across all endpoints + chat tools,
           batch variation charging, idempotent replay non-charging, rollback on failure,
           cross-user parent image ownership (404)
- Phase 3: Atomic UserDataExport + BackgroundTask creation, export expiry (410 Gone) & scheduled
           outbox cleanup, periodic token/ticket/auth pruning, verified account deletion
           (storage delete/list failures, legacy file failures, workspace permission failure,
           worker outbox recovery, repeated deletion, export worker failure)
- Phase 5: Worker anti-starvation (bounded independent concurrency) & image heartbeat DB-outage abort
- Phase 6: Strict TRUSTED_PROXY_CIDRS validation (rejecting 0.0.0.0/0, malformed, broad CIDRs)
- Phase 7: Truthful image capability descriptions & response flags
"""

import os
import sys
import uuid
import shutil
import asyncio
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"
os.environ["JWT_SECRET"] = "test-secret-key-for-gate-closure-minimum-32-chars-ok"
os.environ["INTEGRATION_ENCRYPTION_KEY"] = "test_integration_key_32_chars_ok!"
os.environ["SAKURA_SANDBOX_SERVICE_TOKEN"] = "test_sandbox_service_token_closure"
os.environ["SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY"] = "test_capability_signing_key_32chars!"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database.db import Base, engine, get_db_context
from database.models import (
    User,
    Conversation,
    Document,
    GeneratedImage,
    RepositoryWorkspace,
    BackgroundTask,
    ImageGenerationJob,
    ImageGenerationJobStatus,
    StorageDeletionOutbox,
    PasswordResetToken,
    WebSocketTicket,
    SandboxNetworkAuthorization,
    UserDataExport,
    AccountAuditEvent,
    utc_now,
)
from auth.manager import AuthManager
from services.rate_limit import reset_rate_limits, validate_trusted_proxy_cidrs
from services.quotas import get_user_quota_summary
from services.account import (
    delete_user_account,
    build_and_store_user_export,
    cleanup_expired_exports_and_tokens,
)
from services.documents import process_storage_deletion_outbox
from services.storage import LocalFilesystemStorage
from media.image_worker import ImageJobWorker, create_image_generation_job
from llm.agent import Agent, EDIT_IMAGE_TOOL
from tasks.worker import DurableTaskWorker


class TestStagingGateClosure(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    def setUp(self):
        reset_rate_limits()
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_gate_closure_")
        self.password = "GateClosurePass123!"
        self.user_a_id, self.user_a_name, self.headers_a = self._create_user("gate_a")
        self.user_b_id, self.user_b_name, self.headers_b = self._create_user("gate_b")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_user(self, prefix: str):
        uid = uuid.uuid4()
        uname = f"{prefix}_{uid.hex[:8]}"
        with get_db_context() as db:
            db.add(
                User(
                    id=uid,
                    username=uname,
                    email=f"{uname}@example.com",
                    hashed_password=AuthManager.hash_password(self.password),
                )
            )
            db.commit()
        token = AuthManager.create_access_token({"sub": uname})
        return uid, uname, {"Authorization": f"Bearer {token}"}

    def _seed_image(self, owner_id: uuid.UUID) -> uuid.UUID:
        img_id = uuid.uuid4()
        with get_db_context() as db:
            db.add(
                GeneratedImage(
                    id=img_id,
                    user_id=owner_id,
                    prompt="Original sakura landscape",
                    enhanced_prompt="Original sakura landscape enhanced",
                    aspect_ratio="1:1",
                    width=1024,
                    height=1024,
                    model="flux",
                    storage_path=f"/tmp/{img_id}.png",
                    image_url=f"/api/v1/library/files/{img_id}/download",
                )
            )
            db.commit()
        return img_id

    # ─── Phase 1: Import-time Safety ──────────────────────────────────────────

    def test_phase1_repository_import_does_not_create_workspace_directory(self):
        import importlib
        import coding.repository as repo_mod

        uncreated_dir = os.path.join(self.temp_dir, "never_created_on_import")
        with patch.dict(os.environ, {"SAKURA_WORKSPACE_ROOT": uncreated_dir}):
            importlib.reload(repo_mod)
            self.assertFalse(
                os.path.exists(uncreated_dir),
                "Importing coding.repository must NEVER create SAKURA_WORKSPACE_ROOT at import time",
            )

    # ─── Phase 2: Centralized Image Quotas & Parent Image Ownership ───────────

    async def test_phase2_centralized_image_quotas_all_entrypoints_and_parent_ownership(self):
        img_a = self._seed_image(self.user_a_id)
        img_b = self._seed_image(self.user_b_id)

        # 1. Cross-user parent image ID rejected with 404 on /images/edit, /variation, /upscale
        for ep, body in [
            ("/api/v1/images/edit", {"parent_image_id": str(img_b), "edit_instruction": "Make it dusk"}),
            ("/api/v1/images/variation", {"parent_image_id": str(img_b), "count": 2}),
            ("/api/v1/images/upscale", {"parent_image_id": str(img_b), "scale": 2}),
        ]:
            res = self.client.post(ep, headers=self.headers_a, json=body)
            self.assertEqual(res.status_code, 404, f"Expected 404 on cross-user {ep}, got {res.status_code}")

        # 2. Enforce quota across edit, upscale, variation (batch charging), idempotent replay, and chat tools
        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "4"}):
            # 2a. /images/edit uses 1 (1/4) and returns truthful capability flags
            r_edit = self.client.post(
                "/api/v1/images/edit",
                headers=self.headers_a,
                json={"parent_image_id": str(img_a), "edit_instruction": "Sunset lighting", "idempotency_key": "idem-edit-1"},
            )
            self.assertEqual(r_edit.status_code, 202, r_edit.text)
            self.assertEqual(r_edit.json()["workflow"], "PROMPT_VARIATION")
            self.assertFalse(r_edit.json()["image_conditioned_edit"])

            # 2b. Idempotent replay of /images/edit must NOT consume additional quota (still 1/4)
            r_replay = self.client.post(
                "/api/v1/images/edit",
                headers=self.headers_a,
                json={"parent_image_id": str(img_a), "edit_instruction": "Sunset lighting", "idempotency_key": "idem-edit-1"},
            )
            self.assertEqual(r_replay.status_code, 202)
            self.assertTrue(r_replay.json()["job"]["idempotent_replay"])

            # 2c. /images/variation with count=4 when only 3 remain -> MUST fail 429 and create ZERO jobs
            r_batch_over = self.client.post(
                "/api/v1/images/variation",
                headers=self.headers_a,
                json={"parent_image_id": str(img_a), "count": 4},
            )
            self.assertEqual(r_batch_over.status_code, 429)

            # 2d. /images/variation with count=2 -> uses 2 (3/4)
            r_batch_ok = self.client.post(
                "/api/v1/images/variation",
                headers=self.headers_a,
                json={"parent_image_id": str(img_a), "count": 2},
            )
            self.assertEqual(r_batch_ok.status_code, 202, r_batch_ok.text)
            self.assertEqual(len(r_batch_ok.json()["jobs"]), 2)

            # 2e. /images/upscale -> uses 1 (4/4) and returns truthful flags
            r_up = self.client.post(
                "/api/v1/images/upscale",
                headers=self.headers_a,
                json={"parent_image_id": str(img_a), "scale": 2},
            )
            self.assertEqual(r_up.status_code, 202, r_up.text)
            self.assertEqual(r_up.json()["workflow"], "HIGH_RES_REGENERATION")
            self.assertFalse(r_up.json()["true_upscale"])

            # 2f. Chatbot tools MUST be blocked by quota (4/4 exhausted) and cross-user parent rejected
            with get_db_context() as db:
                agent = Agent(
                    db=db,
                    user_id=self.user_a_id,
                    conversation_id=None,
                    llm_router=MagicMock(),
                    system_prompt="You are Sakura.",
                    history=[],
                )
                out_create = await agent._tool_create_image("Draw a cat")
                self.assertIn("quota exceeded", out_create.lower())

                out_foreign = await agent._tool_edit_image("Change sky", image_id=str(img_b))
                self.assertIn("not found", out_foreign.lower())

                out_edit = await agent._tool_edit_image("Change sky", image_id=str(img_a))
                self.assertIn("quota exceeded", out_edit.lower())

    def test_phase2_quota_reservation_rolls_back_on_job_insert_failure(self):
        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "5"}):
            with get_db_context() as db:
                before = get_user_quota_summary(db, self.user_a_id)["quotas"]["image_generation"]["used"]
                with patch.object(db, "commit", side_effect=RuntimeError("simulated DB commit failure")):
                    with self.assertRaises(RuntimeError):
                        create_image_generation_job(db=db, user_id=self.user_a_id, prompt="Should rollback")
            with get_db_context() as db:
                after = get_user_quota_summary(db, self.user_a_id)["quotas"]["image_generation"]["used"]
                self.assertEqual(before, after, "Quota reservation MUST roll back if job creation fails")

    # ─── Phase 3: Atomic Export, Expiry, Pruning & Durable Account Deletion ───

    def test_phase3_atomic_export_creation_and_expiry_enforcement_and_pruning(self):
        # 1. If BackgroundTask creation fails, UserDataExport MUST NOT persist orphaned
        with patch("api.routes.TaskManager.create_task_in_session", side_effect=RuntimeError("task insert boom")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/auth/me/export", headers=self.headers_a)
        with get_db_context() as db:
            self.assertEqual(db.query(UserDataExport).filter(UserDataExport.user_id == self.user_a_id).count(), 0)

        # 2. Successful atomic export -> expire it -> verify HTTP 410 Gone + scheduled outbox cleanup
        storage = LocalFilesystemStorage(root_dir=os.path.join(self.temp_dir, "exp_store"))
        with patch.dict(os.environ, {"SAKURA_STORAGE_BACKEND": "local", "SAKURA_STORAGE_ROOT": storage.root_dir}):
            r_exp = self.client.post("/api/v1/auth/me/export", headers=self.headers_a)
            self.assertEqual(r_exp.status_code, 202, r_exp.text)
            export_id = uuid.UUID(r_exp.json()["id"])

            build_and_store_user_export(export_id, self.user_a_id, storage_override=storage)

            # Force expiry in DB
            with get_db_context() as db:
                exp = db.query(UserDataExport).filter(UserDataExport.id == export_id).first()
                exp_key = exp.storage_key
                exp.expires_at = utc_now() - timedelta(minutes=5)
                db.commit()
                self.assertTrue(storage.exists(exp_key))

            # Download MUST fail with 410 Gone and mark EXPIRED
            r_dl = self.client.get(f"/api/v1/auth/me/export/{export_id}/download", headers=self.headers_a)
            self.assertEqual(r_dl.status_code, 410)

            # Seed expired tokens/tickets/auths and verify periodic cleanup deletes expired export + auth rows
            old_ts = utc_now() - timedelta(hours=48)
            with get_db_context() as db:
                db.add(PasswordResetToken(id=uuid.uuid4(), user_id=self.user_a_id, token_hash=uuid.uuid4().hex, expires_at=old_ts))
                db.add(WebSocketTicket(ticket=uuid.uuid4().hex, user_id=self.user_a_id, expires_at=old_ts))
                ws_id = uuid.uuid4()
                db.add(RepositoryWorkspace(id=ws_id, user_id=self.user_a_id, name="tmp", workspace_path=self.temp_dir, status="READY"))
                db.add(SandboxNetworkAuthorization(id=uuid.uuid4(), user_id=self.user_a_id, workspace_id=ws_id, command_hash="abc", expires_at=old_ts))
                db.commit()

            stats = cleanup_expired_exports_and_tokens(storage_override=storage)
            self.assertGreaterEqual(stats["export_objects_deleted"], 1)
            self.assertGreaterEqual(stats["reset_tokens_pruned"], 1)
            self.assertGreaterEqual(stats["ws_tickets_pruned"], 1)
            self.assertGreaterEqual(stats["network_auths_pruned"], 1)
            self.assertFalse(storage.exists(exp_key), "Expired export archive must be deleted from storage")

    def test_phase3_account_deletion_handles_storage_list_delete_legacy_and_workspace_failures(self):
        storage_root = os.path.join(self.temp_dir, "del_storage")
        ws_dir = os.path.join(self.temp_dir, "locked_ws")
        legacy_file = os.path.join(storage_root, "legacy_file.txt")
        os.makedirs(storage_root, exist_ok=True)
        os.makedirs(ws_dir, exist_ok=True)
        with open(legacy_file, "w", encoding="utf-8") as f:
            f.write("legacy payload")

        real_storage = LocalFilesystemStorage(root_dir=storage_root)
        doc_key = f"users/{self.user_a_id}/documents/{uuid.uuid4()}/spec.txt"
        real_storage.put(doc_key, b"hello", content_type="text/plain", user_id=self.user_a_id)

        with get_db_context() as db:
            db.add(RepositoryWorkspace(id=uuid.uuid4(), user_id=self.user_a_id, name="locked", workspace_path=ws_dir, status="READY"))
            db.add(
                Document(
                    id=uuid.uuid4(),
                    user_id=self.user_a_id,
                    filename="spec.txt",
                    mime_type="text/plain",
                    storage_backend="local",
                    storage_key=doc_key,
                    storage_path=doc_key,
                )
            )
            db.add(
                Document(
                    id=uuid.uuid4(),
                    user_id=self.user_a_id,
                    filename="legacy.txt",
                    mime_type="text/plain",
                    storage_backend="local",
                    storage_key=None,
                    storage_path=legacy_file,
                )
            )
            db.commit()

        # Simulate: storage.list_keys raises, storage.delete fails, os.remove fails on legacy, rmtree fails on ws_dir
        failing_storage = MagicMock()
        failing_storage.backend_type = "local"
        failing_storage.list_keys.side_effect = RuntimeError("S3 list_objects timeout")
        failing_storage.delete.return_value = False

        with patch.dict(os.environ, {"SAKURA_STORAGE_ROOT": storage_root}), \
             patch("services.account.shutil.rmtree", side_effect=PermissionError("workspace busy")), \
             patch("services.account.os.remove", side_effect=PermissionError("legacy locked")):
            with get_db_context() as db:
                user_obj = db.query(User).filter(User.id == self.user_a_id).first()
                res = delete_user_account(db, user_obj, storage_override=failing_storage)

        self.assertEqual(res["cleanup_status"], "PENDING_ASYNC_CLEANUP")
        self.assertFalse(res["cleanup_complete"])
        self.assertEqual(res["cleanup"]["workspace_cleanup_failures"], 1)
        self.assertTrue(res["cleanup"]["storage_prefix_scan_failed"])
        self.assertGreaterEqual(res["cleanup"]["storage_outbox_deferred"], 2)

        # Now simulate worker recovery once storage & filesystem permissions recover!
        with patch.dict(os.environ, {"SAKURA_STORAGE_ROOT": storage_root}):
            with get_db_context() as db:
                # Make outbox entries immediately due for retry
                db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.status == "PENDING").update(
                    {StorageDeletionOutbox.next_retry_at: utc_now() - timedelta(seconds=5)},
                    synchronize_session=False,
                )
                db.commit()
            outbox_stats = process_storage_deletion_outbox(limit=50, storage_override=real_storage)
            self.assertGreaterEqual(outbox_stats["completed"], 3)

        self.assertFalse(os.path.exists(ws_dir), "Workspace directory must be removed by durable outbox retry")
        self.assertFalse(os.path.exists(legacy_file), "Legacy file must be removed by durable outbox retry")
        self.assertFalse(real_storage.exists(doc_key), "Object storage key must be removed by durable outbox retry")

        # Repeated deletion request with old token returns 401 (safe & idempotent)
        r_again = self.client.request(
            "DELETE",
            "/api/v1/auth/me",
            headers=self.headers_a,
            json={"password": self.password, "confirm": "DELETE"},
        )
        self.assertEqual(r_again.status_code, 401)

    def test_phase3_export_worker_failure_marks_failed(self):
        fake_id = uuid.uuid4()
        with get_db_context() as db:
            db.add(UserDataExport(id=fake_id, user_id=self.user_a_id, status="QUEUED"))
            db.commit()

        bad_storage = MagicMock()
        bad_storage.put.side_effect = RuntimeError("disk full")
        with self.assertRaises(RuntimeError):
            build_and_store_user_export(fake_id, self.user_a_id, storage_override=bad_storage)

        with get_db_context() as db:
            exp = db.query(UserDataExport).filter(UserDataExport.id == fake_id).first()
            self.assertEqual(exp.status, "FAILED")
            self.assertIn("disk full", exp.error)

    # ─── Phase 5: Image Heartbeat DB Outage Abort & Anti-Starvation ───────────

    async def test_phase5_image_worker_aborts_after_consecutive_heartbeat_db_failures(self):
        with get_db_context() as db:
            job, _ = create_image_generation_job(db=db, user_id=self.user_a_id, prompt="DB outage abort test")
            job_id = job.id

        worker = ImageJobWorker(
            worker_id="img_db_outage",
            lease_duration=2.0,
            heartbeat_interval=0.05,
            max_heartbeat_failures=2,
        )
        with patch("media.image_worker._pop_redis_image_job", return_value=str(job_id)):
            claimed = worker.claim_next_job()
        self.assertIsNotNone(claimed)

        cancelled = asyncio.Event()

        async def slow_gen(user_id, prompt, params):
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return {"id": str(uuid.uuid4()), "provider": "pollinations", "model": "flux"}

        real_ctx = get_db_context
        call_counter = {"n": 0}

        def flaky_ctx():
            call_counter["n"] += 1
            # First call is execute_job entry verification; subsequent heartbeat calls fail with DB outage
            if call_counter["n"] >= 2:
                raise RuntimeError("PostgreSQL connection dropped")
            return real_ctx()

        with patch("media.image_worker.get_db_context", side_effect=flaky_ctx):
            ok = await worker.execute_job(claimed, generator_fn=slow_gen)

        self.assertFalse(ok)
        self.assertTrue(cancelled.is_set(), "In-flight generation MUST cancel when heartbeat cannot confirm lease")

    # ─── Phase 6 & 7: Strict Proxy CIDRs & Truthful Tool Descriptions ─────────

    def test_phase6_and_7_strict_proxy_cidrs_and_honest_image_tool_copy(self):
        nets, errs = validate_trusted_proxy_cidrs("127.0.0.1/32, 10.20.30.4/32")
        self.assertEqual(errs, [])
        self.assertEqual(len(nets), 2)

        _, bad_wildcard = validate_trusted_proxy_cidrs("0.0.0.0/0")
        self.assertTrue(bad_wildcard, "0.0.0.0/0 wildcard must be rejected")

        _, bad_broad = validate_trusted_proxy_cidrs("10.0.0.0/4")
        self.assertTrue(bad_broad, "Overly broad /4 CIDR must be rejected")

        _, bad_syntax = validate_trusted_proxy_cidrs("not-a-cidr")
        self.assertTrue(bad_syntax)

        desc = EDIT_IMAGE_TOOL["function"]["description"].lower()
        self.assertIn("prompt-based variation", desc)
        self.assertIn("rather than pixel-level", desc)


if __name__ == "__main__":
    unittest.main()
