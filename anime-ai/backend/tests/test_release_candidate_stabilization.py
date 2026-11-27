"""
Sakura AI — Release Candidate Stabilization Regression Tests
Covers:
1. PostgreSQL backup/restore scripts & CI version-pinning guardrails
2. DurableTaskWorker heartbeat transient recovery vs consecutive DB failure abort & zero stale writes
3. Worker semaphore leak prevention in DurableTaskWorker & ImageJobWorker across repeated claim exceptions
4. Multi-worker-safe StorageDeletionOutbox atomic claiming, stale PROCESSING lease recovery & fenced finalization
5. Batch image variation idempotency (replay, concurrency, different keys, zero extra quota)
6. Chatbot _tool_edit_image() & ImageGenerationEngine.edit_image() truthfulness across all parent cases
7. Guarded deterministic test provider isolation (strictly ENVIRONMENT=test + opt-in flag, never for private intents)
"""

import os
import sys
import uuid
import asyncio
import tempfile
import shutil
import unittest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base, get_db_context
from database.models import (
    User,
    Document,
    GeneratedImage,
    BackgroundTask,
    ImageGenerationJob,
    ImageGenerationJobStatus,
    ImageVariationBatch,
    StorageDeletionOutbox,
    UserUsageQuota,
    utc_now,
)
from auth.manager import AuthManager
from tasks.worker import DurableTaskWorker
from media.image_worker import (
    ImageJobWorker,
    create_image_generation_job,
    create_batch_image_generation_jobs,
)
from media.image_engine import ImageGenerationEngine
from services.documents import (
    process_storage_deletion_outbox,
    recover_stale_outbox_claims,
    claim_storage_deletion_outbox_entries,
    finalize_claimed_outbox_entry,
)
from services.storage import LocalFilesystemStorage
from llm.agent import Agent
from llm.router import LLMRouter, PrivateModelUnavailableError
from llm.providers.deterministic_test import is_deterministic_test_provider_enabled


def _make_user(db, prefix="rc_user"):
    u = User(
        id=uuid.uuid4(),
        username=f"{prefix}_{uuid.uuid4().hex[:8]}@example.com",
        email=f"{prefix}_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=AuthManager.hash_password("StrongPass123!"),
        created_at=utc_now(),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestBackupRestoreAndCIGuardrails(unittest.TestCase):
    """Phase 1 & Phase 2: Verify CI and backup/restore scripts enforce strict PG 15 parity and orphan checks."""

    def test_ci_uses_pinned_postgres_15_and_no_unpinned_postgresql_client_fallback(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        ci_path = os.path.join(repo_root, ".github", "workflows", "ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            ci_text = f.read()

        self.assertNotIn("apt-get install -y --no-install-recommends postgresql-client\n", ci_text)
        self.assertIn("postgres:15", ci_text)
        self.assertIn("EXPECTED_ALEMBIC_HEAD", ci_text)
        self.assertIn("corrupt_probe.dump", ci_text)
        self.assertIn("fullstack-integration:", ci_text)
        self.assertIn("if: always()", ci_text)

    def test_backup_and_verify_scripts_enforce_version_parity_and_assertions(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        backup_sh = os.path.join(repo_root, "anime-ai", "ops", "scripts", "backup_postgres.sh")
        verify_sh = os.path.join(repo_root, "anime-ai", "ops", "scripts", "verify_restore.sh")
        with open(backup_sh, "r", encoding="utf-8") as f:
            b_text = f.read()
        with open(verify_sh, "r", encoding="utf-8") as f:
            v_text = f.read()

        self.assertIn("CLIENT_MAJOR", b_text)
        self.assertIn("SERVER_MAJOR", b_text)
        self.assertIn("CLIENT_MAJOR", v_text)
        self.assertIn("SERVER_MAJOR", v_text)
        self.assertIn("EXPECTED_ALEMBIC_HEAD", v_text)
        self.assertIn("REQUIRED_TABLES", v_text)
        self.assertIn("pg_extension WHERE extname = 'vector'", v_text)
        self.assertIn("pg_restore --list", v_text)


class TestDurableTaskWorkerHeartbeatsAndSemaphores(unittest.IsolatedAsyncioTestCase):
    """Phase 3 & Phase 4: Hardened heartbeat failure tracking + leak-proof semaphore accounting."""

    async def test_transient_heartbeat_db_errors_recover_cleanly(self):
        with get_db_context() as db:
            user = _make_user(db, "hb_recover")
            task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=user.id,
                type="code_analysis",
                title="Transient HB test",
                payload={"code": "print(1)"},
                status="Queued",
                created_at=utc_now(),
            )
            db.add(task)
            db.commit()
            task_id = task.id

        worker = DurableTaskWorker(
            worker_id=f"w_hb_rec_{uuid.uuid4().hex[:6]}",
            lease_duration=2.0,
            heartbeat_interval=0.06,
            max_heartbeat_failures=3,
        )
        claimed = worker.claim_next_task()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, task_id)

        hb_calls = {"count": 0}
        real_get_db = get_db_context

        class _FlakyCtx:
            def __enter__(self):
                hb_calls["count"] += 1
                # Fail first 2 heartbeat DB calls (below max_heartbeat_failures=3), then succeed!
                if hb_calls["count"] in (2, 3):
                    raise RuntimeError("Transient DB blip")
                self._inner = real_get_db()
                return self._inner.__enter__()

            def __exit__(self, *args):
                return self._inner.__exit__(*args)

        async def _slow_handler(tid, uid, payload, router, ctx=None):
            await asyncio.sleep(0.32)
            from tasks.task_manager import update_task_state
            await update_task_state(tid, "Completed", 100, result="recovered_ok", ctx=ctx)

        with patch("tasks.worker.get_db_context", side_effect=lambda: _FlakyCtx()), \
             patch("tasks.worker.execute_code_analysis", side_effect=_slow_handler):
            await worker.execute_task(claimed)

        with get_db_context() as db:
            refreshed = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            self.assertEqual(refreshed.status, "Completed")
            self.assertEqual(refreshed.result, "recovered_ok")

    async def test_consecutive_heartbeat_failures_cancel_handler_with_zero_stale_writes(self):
        with get_db_context() as db:
            user = _make_user(db, "hb_abort")
            task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=user.id,
                type="code_analysis",
                title="Consecutive HB abort test",
                payload={"code": "print(2)"},
                status="Queued",
                created_at=utc_now(),
            )
            db.add(task)
            db.commit()
            task_id = task.id

        worker = DurableTaskWorker(
            worker_id=f"w_hb_abort_{uuid.uuid4().hex[:6]}",
            lease_duration=1.5,
            heartbeat_interval=0.05,
            max_heartbeat_failures=3,
        )
        claimed = worker.claim_next_task()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, task_id)

        real_get_db = get_db_context
        handler_started = {"flag": False}
        handler_cancelled = {"flag": False}

        class _FailingHbCtx:
            def __enter__(self):
                # Once handler is actively running, every heartbeat DB attempt fails!
                if handler_started["flag"]:
                    raise RuntimeError("Persistent DB outage")
                self._inner = real_get_db()
                return self._inner.__enter__()

            def __exit__(self, *args):
                return self._inner.__exit__(*args)

        async def _blocking_handler(tid, uid, payload, router, ctx=None):
            handler_started["flag"] = True
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                handler_cancelled["flag"] = True
                raise

        with patch("tasks.worker.get_db_context", side_effect=lambda: _FailingHbCtx()), \
             patch("tasks.worker.update_task_state", return_value=None), \
             patch("tasks.worker.execute_code_analysis", side_effect=_blocking_handler):
            await asyncio.wait_for(worker.execute_task(claimed), timeout=2.0)

        self.assertTrue(handler_cancelled["flag"], "Handler must be actively cancelled on consecutive heartbeat loss!")
        with get_db_context() as db:
            refreshed = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            # Zero terminal writes by stale worker!
            self.assertEqual(refreshed.status, "Running")
            self.assertIsNone(refreshed.completed_at)

    async def test_durable_task_worker_semaphore_does_not_leak_on_claim_exceptions(self):
        worker = DurableTaskWorker(worker_id=f"w_sem_{uuid.uuid4().hex[:6]}")
        attempts = {"n": 0}
        executed = []

        class _FakeTask:
            id = uuid.uuid4()

        def _flaky_claim():
            attempts["n"] += 1
            # Fail 5 consecutive times (exceeding max_concurrency=2!) then return a real work item
            if attempts["n"] <= 5:
                raise RuntimeError("Simulated DB claim failure")
            if attempts["n"] == 6:
                return _FakeTask()
            worker.stop()
            return None

        async def _fake_exec(task_obj):
            executed.append(task_obj.id)

        with patch.dict(os.environ, {"SAKURA_WORKER_HANDLE_IMAGES": "false"}), \
             patch.object(worker, "recover_stale_tasks", return_value=0), \
             patch.object(worker, "claim_next_task", side_effect=_flaky_claim), \
             patch.object(worker, "execute_task", side_effect=_fake_exec), \
             patch("services.documents.process_storage_deletion_outbox", return_value={}), \
             patch("services.account.cleanup_expired_exports_and_tokens", return_value={}):
            await asyncio.wait_for(
                worker.run(max_iterations=8, max_concurrency=2, idle_sleep=0.01, error_sleep=0.01),
                timeout=3.0,
            )

        self.assertEqual(len(executed), 1, "Worker must still claim and execute tasks after >concurrency claim exceptions!")

    async def test_image_job_worker_semaphore_does_not_leak_on_claim_exceptions(self):
        worker = ImageJobWorker(worker_id=f"img_sem_{uuid.uuid4().hex[:6]}")
        attempts = {"n": 0}
        executed = []

        class _FakeJob:
            id = uuid.uuid4()

        def _flaky_claim():
            attempts["n"] += 1
            if attempts["n"] <= 5:
                raise RuntimeError("Simulated image claim DB error")
            if attempts["n"] == 6:
                return _FakeJob()
            worker.stop()
            return None

        async def _fake_exec(job_obj):
            executed.append(job_obj.id)
            return True

        with patch.object(worker, "recover_stale_jobs", return_value=0), \
             patch.object(worker, "claim_next_job", side_effect=_flaky_claim), \
             patch.object(worker, "execute_job", side_effect=_fake_exec):
            await asyncio.wait_for(
                worker.run(max_iterations=8, max_concurrency=2, idle_sleep=0.01, error_sleep=0.01),
                timeout=3.0,
            )

        self.assertEqual(len(executed), 1, "ImageJobWorker must not deadlock after >concurrency claim exceptions!")


class TestMultiWorkerStorageDeletionOutbox(unittest.TestCase):
    """Phase 5: Atomic multi-worker claiming, stale PROCESSING lease recovery, and fenced completion."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="sakura_outbox_rc_")
        self.storage = LocalFilesystemStorage(root_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_two_workers_claim_disjoint_outbox_entries(self):
        with get_db_context() as db:
            user = _make_user(db, "outbox_multi")
            ids = []
            for i in range(4):
                key = f"users/{user.id}/multi_{i}.txt"
                self.storage.put(key, b"payload", content_type="text/plain", user_id=user.id)
                row = StorageDeletionOutbox(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    storage_backend="local",
                    storage_key=key,
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=5),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                db.add(row)
                ids.append(row.id)
            db.commit()

        # Worker A claims 2 entries; Worker B claims remaining entries -> strictly disjoint!
        with get_db_context() as db_a:
            claimed_a = claim_storage_deletion_outbox_entries(db_a, worker_id="outbox_A", limit=2)
        with get_db_context() as db_b:
            claimed_b = claim_storage_deletion_outbox_entries(db_b, worker_id="outbox_B", limit=10)

        ids_a = {e["id"] for e in claimed_a}
        ids_b = {e["id"] for e in claimed_b}
        self.assertEqual(ids_a & ids_b, set(), "Two workers must never claim the same outbox entry!")
        self.assertTrue(set(ids).issubset(ids_a | ids_b))

        # Finalize all claimed entries cleanly
        with get_db_context() as db:
            for e in claimed_a:
                self.assertEqual(finalize_claimed_outbox_entry(db, e, "outbox_A", True, None), "completed")
            for e in claimed_b:
                self.assertEqual(finalize_claimed_outbox_entry(db, e, "outbox_B", True, None), "completed")

    def test_stale_processing_claim_recovered_and_stale_worker_fenced_out(self):
        with get_db_context() as db:
            user = _make_user(db, "outbox_stale")
            key = f"users/{user.id}/stale_recovery.txt"
            self.storage.put(key, b"stale_bytes", content_type="text/plain", user_id=user.id)
            stale_token = uuid.uuid4()
            entry_id = uuid.uuid4()
            row = StorageDeletionOutbox(
                id=entry_id,
                user_id=user.id,
                storage_backend="local",
                storage_key=key,
                status="PROCESSING",
                worker_id="dead_worker_1",
                claim_token=stale_token,
                claimed_at=utc_now() - timedelta(minutes=10),
                lease_expires_at=utc_now() - timedelta(minutes=5),
                attempt_count=0,
                max_attempts=5,
                created_at=utc_now() - timedelta(minutes=10),
                updated_at=utc_now() - timedelta(minutes=10),
            )
            db.add(row)
            db.commit()

        # Healthy worker runs process_storage_deletion_outbox -> recovers stale claim & completes deletion!
        stats = process_storage_deletion_outbox(
            limit=25,
            storage_override=self.storage,
            worker_id="healthy_worker_2",
        )
        self.assertGreaterEqual(stats["recovered"], 1)
        self.assertGreaterEqual(stats["completed"], 1)
        self.assertFalse(self.storage.exists(key))

        # Now stale dead_worker_1 wakes up late and tries to write FAILED/retry -> MUST BE FENCED OUT!
        stale_entry_snapshot = {
            "id": entry_id,
            "user_id": user.id,
            "document_id": None,
            "storage_backend": "local",
            "storage_key": key,
            "legacy_path": None,
            "attempt_count": 0,
            "max_attempts": 5,
            "claim_token": stale_token,
        }
        with get_db_context() as db:
            res = finalize_claimed_outbox_entry(db, stale_entry_snapshot, "dead_worker_1", False, "stale error")
            self.assertEqual(res, "stale")
            rec = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == entry_id).first()
            self.assertEqual(rec.status, "COMPLETED")
            self.assertIsNone(rec.last_error)


class TestVariationBatchIdempotencyAndEditTruthfulness(unittest.IsolatedAsyncioTestCase):
    """Phase 6: Batch variation idempotency + chatbot edit truthfulness across all parent cases."""

    def test_variation_batch_idempotency_replay_concurrency_and_quota(self):
        with get_db_context() as db:
            user = _make_user(db, "var_idem")
            parent_id = uuid.uuid4()
            doc = Document(
                id=parent_id,
                user_id=user.id,
                filename="base.png",
                mime_type="image/png",
                storage_path="/tmp/base.png",
                is_knowledge_base=False,
                indexing_status="NOT_INDEXED",
            )
            img = GeneratedImage(
                id=parent_id,
                user_id=user.id,
                document_id=parent_id,
                prompt="Sakura castle at dawn",
                enhanced_prompt="Sakura castle at dawn",
                aspect_ratio="1:1",
                width=1024,
                height=1024,
                model="flux",
                storage_path="/tmp/base.png",
                image_url=f"/api/v1/library/files/{parent_id}/download",
            )
            db.add(doc)
            db.add(img)
            db.commit()
            user_id = user.id

        specs = [
            {"prompt": "Sakura castle (var 1)", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(parent_id), "workflow": "VARIATION"}},
            {"prompt": "Sakura castle (var 2)", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(parent_id), "workflow": "VARIATION"}},
        ]

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "4"}):
            # 1. First creation
            with get_db_context() as db:
                jobs1, created1 = create_batch_image_generation_jobs(
                    db=db,
                    user_id=user_id,
                    job_specs=specs,
                    idempotency_key="batch-key-alpha",
                    parent_image_id=parent_id,
                )
                ids1 = [j.id for j in jobs1]
            self.assertTrue(created1)
            self.assertEqual(len(ids1), 2)

            # 2. Replay with same idempotency key -> exact same job IDs, ZERO extra quota
            with get_db_context() as db:
                jobs2, created2 = create_batch_image_generation_jobs(
                    db=db,
                    user_id=user_id,
                    job_specs=specs,
                    idempotency_key="batch-key-alpha",
                    parent_image_id=parent_id,
                )
                ids2 = [j.id for j in jobs2]
                quota_row = db.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == user_id,
                    UserUsageQuota.category == "image_generation",
                ).first()
                usage_after_replay = quota_row.usage_count
            self.assertFalse(created2)
            self.assertEqual(ids2, ids1)
            self.assertEqual(usage_after_replay, 2)

            # 3. Concurrent duplicate submission with same NEW key -> exactly 1 batch created, quota += 2 (total 4)
            def _worker_submit():
                with get_db_context() as s:
                    return create_batch_image_generation_jobs(
                        db=s,
                        user_id=user_id,
                        job_specs=specs,
                        idempotency_key="batch-key-concurrent",
                        parent_image_id=parent_id,
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(_worker_submit)
                f2 = pool.submit(_worker_submit)
                (c_jobs1, c_created1) = f1.result()
                (c_jobs2, c_created2) = f2.result()

            self.assertEqual([j.id for j in c_jobs1], [j.id for j in c_jobs2])
            self.assertEqual(int(c_created1) + int(c_created2), 1)

            with get_db_context() as db:
                quota_row = db.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == user_id,
                    UserUsageQuota.category == "image_generation",
                ).first()
                self.assertEqual(quota_row.usage_count, 4)
                total_jobs = db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_id).count()
                self.assertEqual(total_jobs, 4)

    async def test_chatbot_edit_image_truthfulness_all_four_parent_cases(self):
        with get_db_context() as db:
            user_a = _make_user(db, "edit_truth_a")
            user_b = _make_user(db, "edit_truth_b")

            # User B owns an image; User A has NO images yet
            img_b_id = uuid.uuid4()
            db.add(Document(
                id=img_b_id, user_id=user_b.id, filename="b.png",
                mime_type="image/png", storage_path="/tmp/b.png",
            ))
            db.add(GeneratedImage(
                id=img_b_id, user_id=user_b.id, document_id=img_b_id,
                prompt="User B original", enhanced_prompt="User B original",
                aspect_ratio="1:1", width=1024, height=1024, model="flux",
                storage_path="/tmp/b.png", image_url="/api/v1/library/files/b/download",
            ))
            db.commit()

            agent_a = Agent(db=db, user_id=user_a.id, llm_router=LLMRouter(), system_prompt="", history=[])

            # Case 1: No-parent (user has zero images, image_id omitted) -> honest rejection, 0 jobs, 0 quota
            out_no_parent = await agent_a._tool_edit_image("Make the sky purple", image_id=None)
            self.assertIn("No previously generated image", out_no_parent)
            self.assertEqual(db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_a.id).count(), 0)

            # Case 2: Missing-parent (random non-existent UUID) -> rejected, 0 jobs
            out_missing = await agent_a._tool_edit_image("Make the sky purple", image_id=str(uuid.uuid4()))
            self.assertIn("not found or access denied", out_missing.lower())
            self.assertEqual(db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_a.id).count(), 0)

            # Case 3: Foreign-parent (User B's image ID) -> rejected, 0 jobs
            out_foreign = await agent_a._tool_edit_image("Make the sky purple", image_id=str(img_b_id))
            self.assertIn("not found or access denied", out_foreign.lower())
            self.assertEqual(db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_a.id).count(), 0)

            # ImageGenerationEngine.edit_image also refuses foreign/missing parent directly!
            engine_a = ImageGenerationEngine(db, user_a.id)
            with self.assertRaises(ValueError):
                await engine_a.edit_image(parent_image_id=img_b_id, edit_instruction="Steal parent")

            # Case 4: Valid owned parent -> enqueues PROMPT_VARIATION job with valid parent_image_id
            img_a_id = uuid.uuid4()
            db.add(Document(
                id=img_a_id, user_id=user_a.id, filename="a.png",
                mime_type="image/png", storage_path="/tmp/a.png",
            ))
            db.add(GeneratedImage(
                id=img_a_id, user_id=user_a.id, document_id=img_a_id,
                prompt="User A original", enhanced_prompt="User A original",
                aspect_ratio="1:1", width=1024, height=1024, model="flux",
                storage_path="/tmp/a.png", image_url="/api/v1/library/files/a/download",
            ))
            db.commit()

            out_valid = await agent_a._tool_edit_image("Make the sky twilight pink", image_id=str(img_a_id))
            self.assertIn("Prompt variation job", out_valid)
            jobs_a = db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_a.id).all()
            self.assertEqual(len(jobs_a), 1)
            self.assertEqual(jobs_a[0].parameters.get("parent_image_id"), str(img_a_id))
            self.assertEqual(jobs_a[0].parameters.get("workflow"), "PROMPT_VARIATION")


class TestGuardedDeterministicTestProviders(unittest.TestCase):
    """Phase 7: Deterministic test providers must NEVER activate outside ENVIRONMENT=test or for private intents."""

    def test_disabled_in_production_staging_and_development_even_if_flag_set(self):
        for env_name in ("production", "staging", "development", ""):
            with patch.dict(os.environ, {"ENVIRONMENT": env_name, "SAKURA_DETERMINISTIC_TEST_PROVIDERS": "1"}):
                self.assertFalse(
                    is_deterministic_test_provider_enabled(),
                    f"Deterministic test providers MUST NOT activate in ENVIRONMENT='{env_name}'",
                )

    def test_enabled_only_in_test_and_never_routes_private_intents(self):
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "test",
                "SAKURA_DETERMINISTIC_TEST_PROVIDERS": "1",
                "OLLAMA_BASE_URL": "",
                "OLLAMA_MODEL": "",
            },
        ):
            self.assertTrue(is_deterministic_test_provider_enabled())
            router = LLMRouter()
            prov_name, _ = router.get_provider("general_chat")
            self.assertEqual(prov_name, "deterministic_test")

            # Private intents MUST still fail closed (never routed to deterministic_test!)
            with self.assertRaises(PrivateModelUnavailableError):
                router.get_provider("local_private")
            with self.assertRaises(PrivateModelUnavailableError):
                router.get_provider("private_data")


if __name__ == "__main__":
    unittest.main()
