"""
Sakura AI — PostgreSQL / pgvector Contract, Outbox Concurrency & Variation Idempotency Suite

Contains:
1. Cross-dialect contract tests (run on both SQLite & PostgreSQL):
   - Outbox unexpired-lease enforcement (expired worker cannot finalize even before recovery)
   - Long-running storage deletion with automatic lease renewal
   - Image variation required idempotency key (HTTP 400), replay (HTTP 202, 0 extra quota),
     and payload fingerprint conflict (HTTP 409, 0 extra quota)
   - BM25 lexical retrieval without embedding provider & hybrid RRF with real 1536-dim vectors
   - Historical malformed embedding diagnostic validation

2. Real PostgreSQL 15 integration & concurrency tests (enabled when SAKURA_POSTGRES_TEST=1):
   - Existing JSON -> vector(1536) Alembic upgrade preserving valid 1536-dim embeddings & NULLs
   - Malformed historical JSON embedding rejection with actionable diagnostics
   - Native PostgreSQL vector(1536) persistence, dimension verification & cosine-distance ordering
   - Multi-session concurrent PostgreSQL FOR UPDATE SKIP LOCKED outbox claiming & lease fencing
   - Multi-session concurrent PostgreSQL image variation batch idempotency & quota atomicity
"""

import os
import time
import uuid
import shutil
import tempfile
import unittest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"

from database.db import SessionLocal, engine, get_db_context, normalize_database_url
from database.models import (
    User,
    Document,
    DocumentChunk,
    GeneratedImage,
    ImageGenerationJob,
    ImageVariationBatch,
    StorageDeletionOutbox,
    UserUsageQuota,
    utc_now,
)
from auth.manager import AuthManager
from rag.retrieval import HybridRetriever
from rag.embeddings.manager import EmbeddingManager
from services.documents import (
    claim_storage_deletion_outbox_entries,
    finalize_claimed_outbox_entry,
    recover_stale_outbox_claims,
    process_storage_deletion_outbox,
)
from services.storage import LocalFilesystemStorage
from media.image_worker import (
    create_batch_image_generation_jobs,
    compute_variation_request_fingerprint,
    IdempotencyConflictError,
)
from main import app


def _make_unit_vec(hot_index: int, secondary_index: int = None, secondary_weight: float = 0.0) -> list[float]:
    vec = [0.0] * 1536
    vec[hot_index] = 1.0
    if secondary_index is not None:
        vec[secondary_index] = secondary_weight
    return vec


def _make_user(db, prefix="pgc_user"):
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


class _FixedEmbeddingManager(EmbeddingManager):
    """Test-only deterministic embedding provider returning real 1536-dim vectors."""

    def __init__(self, query_vec: list[float]):
        self.api_key = "test-fixed"
        self.client = object()
        self._query_vec = query_vec

    @property
    def is_available(self) -> bool:
        return True

    def get_embedding(self, text: str):
        return list(self._query_vec)


class _SlowLocalStorage(LocalFilesystemStorage):
    """Wraps LocalFilesystemStorage to simulate a slow deletion that exceeds initial lease."""

    def __init__(self, root_dir: str, delay_seconds: float = 0.45):
        super().__init__(root_dir=root_dir)
        self.delay_seconds = delay_seconds

    def delete(self, storage_key: str) -> bool:
        time.sleep(self.delay_seconds)
        return super().delete(storage_key)


class _FailingThenWorkingStorage(LocalFilesystemStorage):
    """Fails the first N delete calls with a transient storage error, then succeeds."""

    def __init__(self, root_dir: str, fail_count: int = 1):
        super().__init__(root_dir=root_dir)
        self.remaining_failures = fail_count

    def delete(self, storage_key: str) -> bool:
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("Transient S3 503 Service Unavailable")
        return super().delete(storage_key)


class TestDatabaseContractAndHardening(unittest.IsolatedAsyncioTestCase):
    """Runs on both SQLite and PostgreSQL without skips."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="sakura_contract_")
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_outbox_cannot_finalize_after_lease_expiry_without_recovery(self):
        storage = LocalFilesystemStorage(root_dir=self.tmp_dir)
        with get_db_context() as db:
            user = _make_user(db, "exp_norec")
            doc_id = uuid.uuid4()
            key = f"users/{user.id}/documents/{doc_id}/keep_me.txt"
            storage.put(key, b"important", content_type="text/plain", user_id=user.id)
            doc = Document(
                id=doc_id,
                user_id=user.id,
                filename="keep_me.txt",
                mime_type="text/plain",
                storage_path=key,
                storage_key=key,
                storage_backend="local",
            )
            outbox_id = uuid.uuid4()
            row = StorageDeletionOutbox(
                id=outbox_id,
                user_id=user.id,
                document_id=doc_id,
                storage_backend="local",
                storage_key=key,
                status="PENDING",
                attempt_count=0,
                max_attempts=5,
                next_retry_at=utc_now() - timedelta(seconds=1),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(doc)
            db.add(row)
            db.commit()

        with get_db_context() as db:
            claimed = claim_storage_deletion_outbox_entries(db, worker_id="slow_worker", limit=5, lease_seconds=0.3)
            target = next(c for c in claimed if c["id"] == outbox_id)
            # Force lease expiration WITHOUT running recover_stale_outbox_claims
            db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).update(
                {StorageDeletionOutbox.lease_expires_at: utc_now() - timedelta(seconds=2)},
                synchronize_session=False,
            )
            db.commit()

            outcome = finalize_claimed_outbox_entry(db, target, "slow_worker", True, None)
            self.assertEqual(outcome, "stale", "Expired worker MUST NOT finalize even before stale recovery runs!")

            # Document row MUST still exist untouched; outbox row MUST NOT be COMPLETED
            still_doc = db.query(Document).filter(Document.id == doc_id).first()
            still_outbox = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).first()
            self.assertIsNotNone(still_doc)
            self.assertEqual(still_outbox.status, "PROCESSING")

    def test_outbox_long_running_deletion_renews_lease_and_completes(self):
        slow_storage = _SlowLocalStorage(root_dir=self.tmp_dir, delay_seconds=0.55)
        with get_db_context() as db:
            user = _make_user(db, "long_del")
            key = f"users/{user.id}/long_delete.bin"
            slow_storage.put(key, b"slow_payload", content_type="application/octet-stream", user_id=user.id)
            outbox_id = uuid.uuid4()
            db.add(StorageDeletionOutbox(
                id=outbox_id,
                user_id=user.id,
                storage_backend="local",
                storage_key=key,
                status="PENDING",
                attempt_count=0,
                max_attempts=5,
                next_retry_at=utc_now() - timedelta(seconds=1),
                created_at=utc_now(),
                updated_at=utc_now(),
            ))
            db.commit()

        stats = process_storage_deletion_outbox(
            limit=10,
            storage_override=slow_storage,
            worker_id="renewing_worker",
            lease_seconds=0.30,
            renew_interval=0.10,
            operation_timeout_seconds=5.0,
        )
        self.assertGreaterEqual(stats["renewals"], 2, f"Expected >=2 lease renewals during slow delete: {stats}")
        self.assertGreaterEqual(stats["completed"], 1)
        self.assertFalse(slow_storage.exists(key))

        with get_db_context() as db:
            rec = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).first()
            self.assertEqual(rec.status, "COMPLETED")

    def test_variation_endpoint_requires_key_replays_match_and_returns_409_on_mismatch(self):
        with get_db_context() as db:
            user = _make_user(db, "var_409")
            img_a = uuid.uuid4()
            img_b = uuid.uuid4()
            for iid, prompt in ((img_a, "Moonlit pagoda"), (img_b, "Cyberpunk shrine")):
                db.add(Document(id=iid, user_id=user.id, filename=f"{iid}.png", mime_type="image/png", storage_path="/tmp/x.png"))
                db.add(GeneratedImage(
                    id=iid, user_id=user.id, document_id=iid, prompt=prompt, enhanced_prompt=prompt,
                    aspect_ratio="1:1", width=1024, height=1024, model="flux",
                    storage_path="/tmp/x.png", image_url=f"/api/v1/library/files/{iid}/download",
                ))
            db.commit()
            token = AuthManager.create_access_token({"sub": user.username})
            uid = user.id

        headers = {"Authorization": f"Bearer {token}"}

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "5"}):
            # 1. Missing or blank idempotency_key -> HTTP 400
            r_missing = self.client.post("/api/v1/images/variation", headers=headers, json={"parent_image_id": str(img_a), "count": 2})
            self.assertEqual(r_missing.status_code, 400)
            r_blank = self.client.post("/api/v1/images/variation", headers=headers, json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": "   "})
            self.assertEqual(r_blank.status_code, 400)

            # 2. Valid request -> HTTP 202, creates 2 jobs
            r_ok = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": "var-fp-key-1"},
            )
            self.assertEqual(r_ok.status_code, 202, r_ok.text)
            self.assertFalse(r_ok.json()["idempotent_replay"])
            orig_ids = [j["id"] for j in r_ok.json()["jobs"]]
            self.assertEqual(len(orig_ids), 2)

            # 3. Same key + same params -> HTTP 202 replay, identical IDs, 0 extra quota
            r_rep = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": "var-fp-key-1"},
            )
            self.assertEqual(r_rep.status_code, 202)
            self.assertTrue(r_rep.json()["idempotent_replay"])
            self.assertEqual([j["id"] for j in r_rep.json()["jobs"]], orig_ids)

            # 4. Same key + different count -> HTTP 409 Conflict
            r_conflict_count = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 3, "idempotency_key": "var-fp-key-1"},
            )
            self.assertEqual(r_conflict_count.status_code, 409)

            # 5. Same key + different parent_image_id -> HTTP 409 Conflict
            r_conflict_parent = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_b), "count": 2, "idempotency_key": "var-fp-key-1"},
            )
            self.assertEqual(r_conflict_parent.status_code, 409)

            # Quota MUST still be exactly 2 (zero extra charges on replay or 409!)
            with get_db_context() as db:
                q = db.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == uid,
                    UserUsageQuota.category == "image_generation",
                ).first()
                self.assertEqual(q.usage_count, 2)

    async def test_bm25_fallback_and_hybrid_retrieval_with_1536_vectors(self):
        with get_db_context() as db:
            user = _make_user(db, "rag_hybrid")
            doc = Document(
                id=uuid.uuid4(),
                user_id=user.id,
                filename="rag_spec.md",
                mime_type="text/markdown",
                storage_path="/tmp/rag_spec.md",
                is_knowledge_base=True,
                indexing_status="READY",
            )
            db.add(doc)
            c_semantic = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=0,
                content="Sakura distributed lease fencing architecture",
                embedding=_make_unit_vec(0),
            )
            c_lexical = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=1,
                content="PostgreSQL pgvector cosine similarity quantum indexing protocol",
                embedding=_make_unit_vec(1),
            )
            c_null = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=2,
                content="Unembedded lexical note about quantum banana pancakes",
                embedding=None,
            )
            db.add_all([c_semantic, c_lexical, c_null])
            db.commit()

            # 1. BM25 works cleanly with NO embedding provider configured
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                bm25_mgr = EmbeddingManager(api_key=None)
                self.assertFalse(bm25_mgr.is_available)
                retriever_bm25 = HybridRetriever(db, embedding_manager=bm25_mgr)
                bm25_res = await retriever_bm25.retrieve(user.id, "quantum banana pancakes", limit=3)
                self.assertGreaterEqual(len(bm25_res), 1)
                self.assertEqual(bm25_res[0]["chunk_id"], str(c_null.id))

            # 2. Hybrid retrieval with real 1536-dim embedding ranks exact vector match #1 and excludes NULL from semantic search
            vec_mgr = _FixedEmbeddingManager(_make_unit_vec(0, secondary_index=1, secondary_weight=0.01))
            retriever_hybrid = HybridRetriever(db, embedding_manager=vec_mgr)
            sem_only = retriever_hybrid._search_semantic([doc.id], vec_mgr.get_embedding("q"), limit=5)
            self.assertEqual([c.id for c in sem_only], [c_semantic.id, c_lexical.id])

            hybrid_res = await retriever_hybrid.retrieve(user.id, "distributed lease fencing", limit=3)
            self.assertGreaterEqual(len(hybrid_res), 1)
            self.assertEqual(hybrid_res[0]["chunk_id"], str(c_semantic.id))

    def test_malformed_historical_embedding_validator_raises_actionable_error(self):
        import importlib.util
        mig_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "alembic",
                "versions",
                "j9f7a263b56c_pgvector_embeddings_and_variation_fingerprint.py",
            )
        )
        spec = importlib.util.spec_from_file_location("mig_j9f7", mig_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        class _FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        class _FakeBind:
            def __init__(self, rows):
                self._rows = rows

            def execute(self, stmt):
                return _FakeResult(self._rows)

        bad_id_1 = uuid.uuid4()
        bad_id_2 = uuid.uuid4()
        # Wrong dimension & non-numeric element MUST raise with row IDs
        with self.assertRaises(RuntimeError) as ctx1:
            mod._validate_existing_json_embeddings(_FakeBind([(bad_id_1, [0.1, 0.2, 0.3])]))
        self.assertIn(str(bad_id_1), str(ctx1.exception))
        self.assertIn("1536", str(ctx1.exception))

        with self.assertRaises(RuntimeError) as ctx2:
            mod._validate_existing_json_embeddings(_FakeBind([(bad_id_2, {"not": "a_list"})]))
        self.assertIn(str(bad_id_2), str(ctx2.exception))

        # Valid 1536-dim array passes cleanly
        mod._validate_existing_json_embeddings(_FakeBind([(uuid.uuid4(), _make_unit_vec(7))]))

        # Booleans, strings, and non-finite floats (NaN/Inf) MUST all fail safely with chunk IDs
        bad_bool_id = uuid.uuid4()
        with self.assertRaises(RuntimeError) as ctx_bool:
            mod._validate_existing_json_embeddings(_FakeBind([(bad_bool_id, [True] + [0.0] * 1535)]))
        self.assertIn(str(bad_bool_id), str(ctx_bool.exception))

        bad_str_id = uuid.uuid4()
        with self.assertRaises(RuntimeError) as ctx_str:
            mod._validate_existing_json_embeddings(_FakeBind([(bad_str_id, ["0.1"] + [0.0] * 1535)]))
        self.assertIn(str(bad_str_id), str(ctx_str.exception))

        bad_nan_id = uuid.uuid4()
        with self.assertRaises(RuntimeError) as ctx_nan:
            mod._validate_existing_json_embeddings(_FakeBind([(bad_nan_id, [float("nan")] + [0.0] * 1535)]))
        self.assertIn(str(bad_nan_id), str(ctx_nan.exception))

    def test_unified_delete_document_slow_storage_renewal_concurrent_and_worker_race(self):
        """
        Phase 1 comprehensive tests for unified delete_document():
        1. API deletion with slow storage > initial lease renews lease & completes cleanly.
        2. Two simultaneous API deletion calls NEVER duplicate physical deletion or steal claim.
        3. API deletion racing with active worker claim NEVER steals claim or deletes DB row.
        4. Storage failure retains Document (DELETE_FAILED) and repeated deletion succeeds once storage recovers.
        5. Timeout + late completion quarantines outbox, retains Document, and late finish cannot delete DB row.
        6. DB failure after physical deletion recovers cleanly via outbox worker.
        """
        import threading
        from services.documents import delete_document

        # 1. Slow storage deletion exceeding initial lease -> renews lease & completes cleanly
        slow_storage = _SlowLocalStorage(root_dir=self.tmp_dir, delay_seconds=0.45)
        with get_db_context() as db:
            user = _make_user(db, "del_slow")
            doc_id = uuid.uuid4()
            key = f"users/{user.id}/documents/{doc_id}/slow.txt"
            slow_storage.put(key, b"slow_api_delete", content_type="text/plain", user_id=user.id)
            db.add(Document(
                id=doc_id, user_id=user.id, filename="slow.txt", mime_type="text/plain",
                storage_path=key, storage_key=key, storage_backend="local",
            ))
            db.commit()

            res = delete_document(
                doc_id, user.id, db,
                storage_override=slow_storage,
                lease_seconds=0.25,
                renew_interval=0.08,
                operation_timeout_seconds=5.0,
            )
            self.assertEqual(res["deletion_status"], "COMPLETED")
            self.assertGreaterEqual(res["lease_renewals"], 2)
            self.assertFalse(slow_storage.exists(key))
            self.assertIsNone(db.query(Document).filter(Document.id == doc_id).first())

        # 2. Two simultaneous API deletion calls -> physical delete invoked ONCE; second sees in-progress/completed
        class _BarrierCountingStorage(LocalFilesystemStorage):
            def __init__(self, root_dir: str):
                super().__init__(root_dir=root_dir)
                self.started = threading.Event()
                self.allow_finish = threading.Event()
                self.delete_calls = 0
                self._lock = threading.Lock()

            def delete(self, storage_key: str) -> bool:
                with self._lock:
                    self.delete_calls += 1
                self.started.set()
                self.allow_finish.wait(timeout=3.0)
                return super().delete(storage_key)

        barrier_storage = _BarrierCountingStorage(root_dir=self.tmp_dir)
        with get_db_context() as db:
            user2 = _make_user(db, "del_race")
            doc2_id = uuid.uuid4()
            key2 = f"users/{user2.id}/documents/{doc2_id}/race.txt"
            barrier_storage.put(key2, b"race_bytes", content_type="text/plain", user_id=user2.id)
            db.add(Document(
                id=doc2_id, user_id=user2.id, filename="race.txt", mime_type="text/plain",
                storage_path=key2, storage_key=key2, storage_backend="local",
            ))
            db.commit()
            u2_id = user2.id

        res_holder = {}

        def _call_one():
            with get_db_context() as s1:
                res_holder["one"] = delete_document(
                    doc2_id, u2_id, s1,
                    storage_override=barrier_storage,
                    raise_on_storage_error=False,
                    lease_seconds=30.0,
                )

        t1 = threading.Thread(target=_call_one)
        t1.start()
        self.assertTrue(barrier_storage.started.wait(timeout=2.0), "First API delete did not start")

        # While call 1 holds unexpired PROCESSING lease, call 2 arrives -> MUST NOT steal claim or call delete!
        with get_db_context() as s2:
            res_two = delete_document(
                doc2_id, u2_id, s2,
                storage_override=barrier_storage,
                raise_on_storage_error=False,
                lease_seconds=30.0,
            )
        self.assertTrue(res_two.get("already_in_progress"))
        self.assertEqual(res_two["deletion_status"], "DELETING")
        self.assertEqual(barrier_storage.delete_calls, 1, "Concurrent API delete MUST NOT invoke duplicate physical deletion!")

        barrier_storage.allow_finish.set()
        t1.join(timeout=3.0)
        self.assertEqual(res_holder["one"]["deletion_status"], "COMPLETED")
        self.assertEqual(barrier_storage.delete_calls, 1)
        self.assertFalse(barrier_storage.exists(key2))

        # 3. API deletion racing with active background worker claim -> API does NOT steal worker's lease!
        with get_db_context() as db:
            user3 = _make_user(db, "del_wrace")
            doc3_id = uuid.uuid4()
            key3 = f"users/{user3.id}/documents/{doc3_id}/wrace.txt"
            LocalFilesystemStorage(root_dir=self.tmp_dir).put(key3, b"worker_owned", content_type="text/plain", user_id=user3.id)
            db.add(Document(
                id=doc3_id, user_id=user3.id, filename="wrace.txt", mime_type="text/plain",
                storage_path=key3, storage_key=key3, storage_backend="local",
            ))
            worker_token = uuid.uuid4()
            outbox3_id = uuid.uuid4()
            db.add(StorageDeletionOutbox(
                id=outbox3_id, user_id=user3.id, document_id=doc3_id,
                storage_backend="local", storage_key=key3,
                status="PROCESSING", worker_id="bg_worker_active",
                claim_token=worker_token, claimed_at=utc_now(),
                lease_expires_at=utc_now() + timedelta(seconds=60),
                attempt_count=0, max_attempts=5, created_at=utc_now(), updated_at=utc_now(),
            ))
            db.commit()

            api_race_res = delete_document(
                doc3_id, user3.id, db,
                storage_override=LocalFilesystemStorage(root_dir=self.tmp_dir),
                raise_on_storage_error=False,
            )
            self.assertTrue(api_race_res.get("already_in_progress"))
            ob3 = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox3_id).first()
            self.assertEqual(ob3.worker_id, "bg_worker_active")
            self.assertEqual(ob3.claim_token, worker_token)
            self.assertIsNotNone(db.query(Document).filter(Document.id == doc3_id).first())

        # 4. Storage failure -> retains Document (DELETE_FAILED); repeated API deletion succeeds once storage recovers
        flaky = _FailingThenWorkingStorage(root_dir=self.tmp_dir, fail_count=1)
        with get_db_context() as db:
            user4 = _make_user(db, "del_retry")
            doc4_id = uuid.uuid4()
            key4 = f"users/{user4.id}/documents/{doc4_id}/retry.txt"
            flaky.put(key4, b"retry_doc", content_type="text/plain", user_id=user4.id)
            db.add(Document(
                id=doc4_id, user_id=user4.id, filename="retry.txt", mime_type="text/plain",
                storage_path=key4, storage_key=key4, storage_backend="local",
            ))
            db.commit()

            r_fail = delete_document(doc4_id, user4.id, db, storage_override=flaky, raise_on_storage_error=False)
            self.assertEqual(r_fail["deletion_status"], "DELETE_FAILED")
            d4 = db.query(Document).filter(Document.id == doc4_id).first()
            self.assertIsNotNone(d4)
            self.assertEqual(d4.deletion_status, "DELETE_FAILED")
            self.assertTrue(flaky.exists(key4))

            # Repeated API deletion reuses same outbox row and succeeds
            r_ok = delete_document(doc4_id, user4.id, db, storage_override=flaky, raise_on_storage_error=False)
            self.assertEqual(r_ok["deletion_status"], "COMPLETED")
            self.assertEqual(r_ok["outbox_id"], r_fail["outbox_id"])
            self.assertFalse(flaky.exists(key4))
            self.assertIsNone(db.query(Document).filter(Document.id == doc4_id).first())

        # 5. Timeout + late completion -> quarantined in PROCESSING, Document retained, late finish cannot delete DB row
        class _StuckStorage(LocalFilesystemStorage):
            def __init__(self, root_dir: str):
                super().__init__(root_dir=root_dir)
                self.release = threading.Event()
                self.finished = threading.Event()

            def delete(self, storage_key: str) -> bool:
                self.release.wait(timeout=3.0)
                self.finished.set()
                return super().delete(storage_key)

        stuck = _StuckStorage(root_dir=self.tmp_dir)
        with get_db_context() as db:
            user5 = _make_user(db, "del_timeout")
            doc5_id = uuid.uuid4()
            key5 = f"users/{user5.id}/documents/{doc5_id}/stuck.txt"
            stuck.put(key5, b"stuck_bytes", content_type="text/plain", user_id=user5.id)
            db.add(Document(
                id=doc5_id, user_id=user5.id, filename="stuck.txt", mime_type="text/plain",
                storage_path=key5, storage_key=key5, storage_backend="local",
            ))
            db.commit()

            r_to = delete_document(
                doc5_id, user5.id, db,
                storage_override=stuck,
                raise_on_storage_error=False,
                lease_seconds=0.22,
                renew_interval=0.08,
                operation_timeout_seconds=0.25,
                timeout_grace_seconds=0.08,
            )
            self.assertTrue(r_to.get("timed_out"))
            self.assertEqual(r_to["deletion_status"], "DELETE_FAILED")
            # Document still retained and outbox quarantined in PROCESSING (not released to PENDING!)
            self.assertIsNotNone(db.query(Document).filter(Document.id == doc5_id).first())
            ob5 = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == uuid.UUID(r_to["outbox_id"])).first()
            self.assertEqual(ob5.status, "PROCESSING")

            # Now late operation completes -> DB row MUST still remain untouched until proper recovery/re-claim!
            stuck.release.set()
            self.assertTrue(stuck.finished.wait(timeout=2.0))
            db.expire_all()
            self.assertIsNotNone(db.query(Document).filter(Document.id == doc5_id).first())

        # 6. DB failure after physical deletion -> outbox stays PROCESSING until lease expiry, then worker recovers & deletes DB row
        local_store = LocalFilesystemStorage(root_dir=self.tmp_dir)
        with get_db_context() as db:
            user6 = _make_user(db, "del_dbfail")
            doc6_id = uuid.uuid4()
            key6 = f"users/{user6.id}/documents/{doc6_id}/dbfail.txt"
            local_store.put(key6, b"gone_before_db_commit", content_type="text/plain", user_id=user6.id)
            db.add(Document(
                id=doc6_id, user_id=user6.id, filename="dbfail.txt", mime_type="text/plain",
                storage_path=key6, storage_key=key6, storage_backend="local",
            ))
            db.commit()

            with patch(
                "services.documents.finalize_claimed_outbox_entry",
                side_effect=RuntimeError("Simulated DB commit failure after storage delete"),
            ):
                with self.assertRaises(RuntimeError):
                    delete_document(doc6_id, user6.id, db, storage_override=local_store, lease_seconds=30.0)

            # Physical object is already deleted, but DB row and PROCESSING outbox row remain consistent!
            self.assertFalse(local_store.exists(key6))
            self.assertIsNotNone(db.query(Document).filter(Document.id == doc6_id).first())
            ob6 = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.document_id == doc6_id).first()
            self.assertIsNotNone(ob6)
            self.assertEqual(ob6.status, "PROCESSING")

            # Simulate lease expiry -> background worker recovers stale claim, deletes missing object idempotently, removes Document!
            db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == ob6.id).update(
                {StorageDeletionOutbox.lease_expires_at: utc_now() - timedelta(seconds=5)},
                synchronize_session=False,
            )
            db.commit()
            db.expire_all()

            rec_stats = process_storage_deletion_outbox(
                db=db, limit=10, storage_override=local_store, worker_id="recovery_after_db_fail",
            )
            self.assertGreaterEqual(rec_stats["recovered"], 1)
            self.assertGreaterEqual(rec_stats["completed"], 1)
            db.expire_all()
            self.assertIsNone(db.query(Document).filter(Document.id == doc6_id).first())
            ob6_after = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == ob6.id).first()
            self.assertEqual(ob6_after.status, "COMPLETED")

    def test_legacy_null_fingerprint_variation_batch_compatibility_policy(self):
        """Legacy ImageVariationBatch rows with NULL fingerprint reject mismatched params (409) & backfill on match."""
        with get_db_context() as db:
            user = _make_user(db, "var_legacy")
            img_a = uuid.uuid4()
            img_b = uuid.uuid4()
            for iid, prompt in ((img_a, "Legacy A"), (img_b, "Legacy B")):
                db.add(Document(id=iid, user_id=user.id, filename=f"{iid}.png", mime_type="image/png", storage_path="/tmp/l.png"))
                db.add(GeneratedImage(
                    id=iid, user_id=user.id, document_id=iid, prompt=prompt, enhanced_prompt=prompt,
                    aspect_ratio="1:1", width=1024, height=1024, model="flux",
                    storage_path="/tmp/l.png", image_url=f"/api/v1/library/files/{iid}/download",
                ))
            j1 = ImageGenerationJob(
                id=uuid.uuid4(), user_id=user.id, prompt="Legacy A (variation 1)",
                requested_pipeline="auto", status="QUEUED",
                parameters={"parent_image_id": str(img_a), "intensity": "medium", "conversation_id": None},
            )
            j2 = ImageGenerationJob(
                id=uuid.uuid4(), user_id=user.id, prompt="Legacy A (variation 2)",
                requested_pipeline="auto", status="QUEUED",
                parameters={"parent_image_id": str(img_a), "intensity": "medium", "conversation_id": None},
            )
            legacy_batch = ImageVariationBatch(
                id=uuid.uuid4(),
                user_id=user.id,
                idempotency_key="legacy-null-fp-key",
                request_fingerprint=None,
                parent_image_id=img_a,
                job_ids=[str(j1.id), str(j2.id)],
                created_at=utc_now(),
            )
            db.add_all([j1, j2, legacy_batch])
            db.commit()
            token = AuthManager.create_access_token({"sub": user.username})
            orig_ids = [str(j1.id), str(j2.id)]
            batch_id = legacy_batch.id

        headers = {"Authorization": f"Bearer {token}"}
        # Mismatched count -> HTTP 409
        r_bad_cnt = self.client.post(
            "/api/v1/images/variation", headers=headers,
            json={"parent_image_id": str(img_a), "count": 3, "idempotency_key": "legacy-null-fp-key"},
        )
        self.assertEqual(r_bad_cnt.status_code, 409)

        # Mismatched parent_image_id -> HTTP 409
        r_bad_parent = self.client.post(
            "/api/v1/images/variation", headers=headers,
            json={"parent_image_id": str(img_b), "count": 2, "idempotency_key": "legacy-null-fp-key"},
        )
        self.assertEqual(r_bad_parent.status_code, 409)

        # Matching params -> HTTP 202 replay with original job IDs & fingerprint backfilled!
        r_ok = self.client.post(
            "/api/v1/images/variation", headers=headers,
            json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": "legacy-null-fp-key"},
        )
        self.assertEqual(r_ok.status_code, 202, r_ok.text)
        self.assertTrue(r_ok.json()["idempotent_replay"])
        self.assertEqual([j["id"] for j in r_ok.json()["jobs"]], orig_ids)

        with get_db_context() as db:
            refreshed = db.query(ImageVariationBatch).filter(ImageVariationBatch.id == batch_id).first()
            self.assertIsNotNone(refreshed.request_fingerprint, "Legacy batch fingerprint should be backfilled on verified match")


@unittest.skipUnless(
    os.getenv("SAKURA_POSTGRES_TEST", "0") == "1",
    "PostgreSQL pgvector & concurrency tests disabled (set SAKURA_POSTGRES_TEST=1)",
)
class TestPostgresPgvectorAndConcurrency(unittest.IsolatedAsyncioTestCase):
    """Real PostgreSQL 15 integration tests — ZERO skips allowed in PostgreSQL CI."""

    @classmethod
    def setUpClass(cls):
        raw_url = os.getenv("DATABASE_URL", "")
        if not raw_url or not raw_url.startswith(("postgresql", "postgres")):
            raise AssertionError("SAKURA_POSTGRES_TEST=1 requires a PostgreSQL DATABASE_URL!")
        cls.pg_url = normalize_database_url(raw_url)
        cls.pg_engine = sa.create_engine(cls.pg_url, pool_size=10, max_overflow=10)
        cls.PGSession = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=cls.pg_engine)
        cls.tmp_dir = tempfile.mkdtemp(prefix="sakura_pg_conc_")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "pg_engine"):
            cls.pg_engine.dispose()
        if hasattr(cls, "tmp_dir"):
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_pg_existing_json_schema_upgrade_to_vector_1536_preserves_data_and_rejects_malformed(self):
        """
        Tests upgrading a genuinely isolated temporary PostgreSQL database from i8e6f152a45b
        (JSON embedding) to j9f7a263b56c (native vector(1536)):
        - Valid 1536-dim JSON embedding is preserved as vector(1536) with exact float values
        - NULL embedding is preserved as NULL
        - Malformed JSON embedding (wrong dim, boolean, non-array) aborts upgrade with actionable error
        - Wrong vector typmod (vector(768)) aborts upgrade with actionable error
        - Downgrade converts vector(1536) back to JSON preserving values and NULLs
        """
        from sqlalchemy.engine.url import make_url
        import json

        temp_db_name = f"sakura_pgvec_upg_{uuid.uuid4().hex[:10]}"
        parsed_url = make_url(self.pg_url)
        admin_url = parsed_url.set(database="postgres")
        temp_url = parsed_url.set(database=temp_db_name)

        admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{temp_db_name}"'))

        temp_engine = sa.create_engine(temp_url)
        try:
            # 1. Upgrade fresh temporary database to pre-pgvector revision i8e6f152a45b
            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", str(temp_url))
            with temp_engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "i8e6f152a45b")

            # Confirm pre-upgrade column is JSON
            with temp_engine.connect() as conn:
                pre_type = conn.execute(
                    sa.text(
                        "SELECT udt_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'document_chunks' AND column_name = 'embedding'"
                    )
                ).scalar()
                self.assertIn(pre_type, ("json", "jsonb"))

            uid = uuid.uuid4()
            doc_id = uuid.uuid4()
            valid_cid = uuid.uuid4()
            null_cid = uuid.uuid4()
            bad_cid = uuid.uuid4()
            vec = _make_unit_vec(5, secondary_index=42, secondary_weight=0.25)

            with temp_engine.begin() as conn:
                conn.execute(
                    sa.text("INSERT INTO users (id, username, hashed_password) VALUES (:id, :u, :p)"),
                    {"id": uid, "u": f"upg_{uid.hex[:6]}", "p": "hash"},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO documents (id, user_id, filename, mime_type, storage_path, is_knowledge_base, indexing_status) "
                        "VALUES (:id, :uid, 'hist.md', 'text/markdown', '/tmp/hist.md', true, 'READY')"
                    ),
                    {"id": doc_id, "uid": uid},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks (id, document_id, chunk_index, content, embedding) "
                        "VALUES (:id, :did, 0, 'Valid historical JSON embedding', CAST(:emb AS json))"
                    ),
                    {"id": valid_cid, "did": doc_id, "emb": json.dumps(vec)},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks (id, document_id, chunk_index, content, embedding) "
                        "VALUES (:id, :did, 1, 'Null historical embedding', NULL)"
                    ),
                    {"id": null_cid, "did": doc_id},
                )
                # Insert malformed row first to prove upgrade fails cleanly with actionable diagnostics
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks (id, document_id, chunk_index, content, embedding) "
                        "VALUES (:id, :did, 2, 'Malformed historical embedding', CAST(:emb AS json))"
                    ),
                    {"id": bad_cid, "did": doc_id, "emb": json.dumps([0.1, 0.2, 0.3])},
                )

            with self.assertRaises(RuntimeError) as err_ctx:
                with temp_engine.begin() as conn:
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
            self.assertIn(str(bad_cid), str(err_ctx.exception))
            self.assertIn("1536", str(err_ctx.exception))

            # Remove malformed row -> upgrade to head MUST succeed and preserve exact vector values & NULL
            with temp_engine.begin() as conn:
                conn.execute(sa.text("DELETE FROM document_chunks WHERE id = :id"), {"id": bad_cid})

            with temp_engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")

            with temp_engine.connect() as conn:
                emb_type = conn.execute(
                    sa.text(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON a.attrelid = c.oid
                        WHERE c.relname = 'document_chunks'
                          AND a.attname = 'embedding'
                          AND NOT a.attisdropped
                        """
                    )
                ).scalar()
                self.assertEqual(emb_type, "vector(1536)")

                dims = conn.execute(
                    sa.text("SELECT vector_dims(embedding) FROM document_chunks WHERE id = :id"),
                    {"id": valid_cid},
                ).scalar()
                self.assertEqual(dims, 1536)

                # Verify actual preserved float values (not merely dimensions!)
                raw_vec_text = conn.execute(
                    sa.text("SELECT embedding::text FROM document_chunks WHERE id = :id"),
                    {"id": valid_cid},
                ).scalar()
                parsed_vals = json.loads(raw_vec_text)
                self.assertEqual(len(parsed_vals), 1536)
                self.assertAlmostEqual(float(parsed_vals[5]), 1.0, places=5)
                self.assertAlmostEqual(float(parsed_vals[42]), 0.25, places=5)
                self.assertAlmostEqual(float(parsed_vals[0]), 0.0, places=5)

                null_check = conn.execute(
                    sa.text("SELECT embedding IS NULL FROM document_chunks WHERE id = :id"),
                    {"id": null_cid},
                ).scalar()
                self.assertTrue(null_check)

            # Verify downgrade back to i8e6f152a45b converts vector(1536) back to JSON preserving values & NULL
            with temp_engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.downgrade(cfg, "i8e6f152a45b")

            with temp_engine.connect() as conn:
                down_vals = conn.execute(
                    sa.text("SELECT embedding FROM document_chunks WHERE id = :id"),
                    {"id": valid_cid},
                ).scalar()
                self.assertEqual(len(down_vals), 1536)
                self.assertAlmostEqual(float(down_vals[5]), 1.0, places=5)
                self.assertAlmostEqual(float(down_vals[42]), 0.25, places=5)

            # Verify wrong vector typmod (e.g. vector(768)) is explicitly caught & rejected with chunk ID
            with temp_engine.begin() as conn:
                conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(
                    sa.text("UPDATE document_chunks SET embedding = NULL WHERE id = :id"),
                    {"id": valid_cid},
                )
                conn.execute(sa.text("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768) USING NULL"))
                vec_768 = [0.0] * 768
                vec_768[0] = 1.0
                conn.execute(
                    sa.text("UPDATE document_chunks SET embedding = CAST(:v AS vector(768)) WHERE id = :id"),
                    {"id": valid_cid, "v": json.dumps(vec_768)},
                )

            with self.assertRaises(RuntimeError) as typmod_err:
                with temp_engine.begin() as conn:
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
            self.assertIn(str(valid_cid), str(typmod_err.exception))
            self.assertIn("1536", str(typmod_err.exception))
        finally:
            temp_engine.dispose()
            with admin_engine.connect() as conn:
                conn.execute(
                    sa.text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :dname AND pid <> pg_backend_pid()"
                    ),
                    {"dname": temp_db_name},
                )
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{temp_db_name}"'))
            admin_engine.dispose()

    async def test_pg_native_cosine_distance_ordering_and_null_handling(self):
        with self.PGSession() as db:
            user = _make_user(db, "pg_cos")
            doc = Document(
                id=uuid.uuid4(),
                user_id=user.id,
                filename="pg_vec.md",
                mime_type="text/markdown",
                storage_path="/tmp/pg_vec.md",
                is_knowledge_base=True,
                indexing_status="READY",
            )
            db.add(doc)
            c_near = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=0,
                content="Nearest vector match",
                embedding=_make_unit_vec(10, secondary_index=11, secondary_weight=0.05),
            )
            c_far = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=1,
                content="Orthogonal distant vector",
                embedding=_make_unit_vec(99),
            )
            c_null = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                chunk_index=2,
                content="Chunk without embedding",
                embedding=None,
            )
            db.add_all([c_near, c_far, c_null])
            db.commit()

            # Read back and verify dimension & values
            loaded = db.query(DocumentChunk).filter(DocumentChunk.id == c_near.id).first()
            vals = list(loaded.embedding)
            self.assertEqual(len(vals), 1536)
            self.assertAlmostEqual(float(vals[10]), 1.0, places=5)
            self.assertAlmostEqual(float(vals[11]), 0.05, places=5)

            # Execute native PostgreSQL cosine_distance ordering via HybridRetriever
            qvec = _make_unit_vec(10)
            retriever = HybridRetriever(db, embedding_manager=_FixedEmbeddingManager(qvec))
            sem_hits = retriever._search_semantic([doc.id], qvec, limit=5)
            self.assertEqual([c.id for c in sem_hits], [c_near.id, c_far.id])

            # Hybrid RRF returns c_near first
            hybrid_hits = await retriever.retrieve(user.id, "vector match", limit=3)
            self.assertEqual(hybrid_hits[0]["chunk_id"], str(c_near.id))

    def test_pg_concurrent_outbox_skip_locked_lease_expiry_renewal_and_retry(self):
        storage = LocalFilesystemStorage(root_dir=self.tmp_dir)
        outbox_ids = []
        with self.PGSession() as db:
            user = _make_user(db, "pg_outbox_conc")
            uid = user.id
            for i in range(10):
                key = f"users/{uid}/pg_conc_{i}.txt"
                storage.put(key, f"data_{i}".encode("utf-8"), content_type="text/plain", user_id=uid)
                oid = uuid.uuid4()
                db.add(StorageDeletionOutbox(
                    id=oid,
                    user_id=uid,
                    storage_backend="local",
                    storage_key=key,
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=5),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ))
                outbox_ids.append(oid)
            db.commit()

        # 1. Two independent PG sessions claiming concurrently with FOR UPDATE SKIP LOCKED
        def _claim_batch(worker_name: str):
            with self.PGSession() as s:
                return claim_storage_deletion_outbox_entries(s, worker_id=worker_name, limit=6, lease_seconds=60)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_a = pool.submit(_claim_batch, "pg_worker_A")
            f_b = pool.submit(_claim_batch, "pg_worker_B")
            claimed_a = f_a.result()
            claimed_b = f_b.result()

        ids_a = {e["id"] for e in claimed_a if e["id"] in outbox_ids}
        ids_b = {e["id"] for e in claimed_b if e["id"] in outbox_ids}
        self.assertEqual(ids_a & ids_b, set(), "PG SKIP LOCKED workers MUST claim strictly disjoint rows!")
        self.assertEqual(len(ids_a | ids_b), 10)

        # 2. Finalization after expiry without recovery -> rejected ('stale')
        target = next(e for e in claimed_a if e["id"] in outbox_ids)
        with self.PGSession() as s:
            s.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == target["id"]).update(
                {StorageDeletionOutbox.lease_expires_at: utc_now() - timedelta(seconds=5)},
                synchronize_session=False,
            )
            s.commit()
            self.assertEqual(finalize_claimed_outbox_entry(s, target, "pg_worker_A", True, None), "stale")

        # 3. Stale lease recovery -> reclaimed by Worker C -> old Worker A token rejected
        with self.PGSession() as s:
            rec_count = recover_stale_outbox_claims(s)
            self.assertGreaterEqual(rec_count, 1)
            reclaimed = claim_storage_deletion_outbox_entries(s, worker_id="pg_worker_C", limit=10, lease_seconds=60)
            reclaimed_entry = next(e for e in reclaimed if e["id"] == target["id"])
            # Old Worker A trying to finalize after Worker C reclaimed -> stale!
            self.assertEqual(finalize_claimed_outbox_entry(s, target, "pg_worker_A", True, None), "stale")
            # Worker C finalizes cleanly
            self.assertEqual(finalize_claimed_outbox_entry(s, reclaimed_entry, "pg_worker_C", True, None), "completed")

        # Clean up remaining claimed entries
        with self.PGSession() as s:
            for e in claimed_a:
                if e["id"] != target["id"]:
                    finalize_claimed_outbox_entry(s, e, "pg_worker_A", True, None)
            for e in claimed_b:
                finalize_claimed_outbox_entry(s, e, "pg_worker_B", True, None)

        # 4. Transient object-storage failure retries with backoff, then succeeds
        flaky = _FailingThenWorkingStorage(root_dir=self.tmp_dir, fail_count=1)
        retry_key = f"users/{uid}/transient_retry.txt"
        flaky.put(retry_key, b"retry_me", content_type="text/plain", user_id=uid)
        retry_oid = uuid.uuid4()
        with self.PGSession() as s:
            s.add(StorageDeletionOutbox(
                id=retry_oid,
                user_id=uid,
                storage_backend="local",
                storage_key=retry_key,
                status="PENDING",
                attempt_count=0,
                max_attempts=5,
                next_retry_at=utc_now() - timedelta(seconds=1),
                created_at=utc_now(),
                updated_at=utc_now(),
            ))
            s.commit()

        with self.PGSession() as s:
            st1 = process_storage_deletion_outbox(db=s, limit=10, storage_override=flaky, worker_id="pg_retry_w")
            self.assertGreaterEqual(st1["retried"], 1)
            rec1 = s.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == retry_oid).first()
            self.assertEqual(rec1.status, "PENDING")
            self.assertEqual(rec1.attempt_count, 1)
            self.assertIsNotNone(rec1.next_retry_at)
            # Fast-forward backoff window and re-run -> succeeds!
            rec1.next_retry_at = utc_now() - timedelta(seconds=1)
            s.commit()
            st2 = process_storage_deletion_outbox(db=s, limit=10, storage_override=flaky, worker_id="pg_retry_w")
            self.assertGreaterEqual(st2["completed"], 1)
            rec2 = s.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == retry_oid).first()
            self.assertEqual(rec2.status, "COMPLETED")
            self.assertFalse(flaky.exists(retry_key))

    def test_pg_concurrent_image_variation_idempotency_and_409_conflict(self):
        with self.PGSession() as db:
            user = _make_user(db, "pg_var_conc")
            uid = user.id
            pid = uuid.uuid4()
            db.add(Document(id=pid, user_id=uid, filename="p.png", mime_type="image/png", storage_path="/tmp/p.png"))
            db.add(GeneratedImage(
                id=pid, user_id=uid, document_id=pid, prompt="PG Concurrent Castle",
                enhanced_prompt="PG Concurrent Castle", aspect_ratio="1:1", width=1024, height=1024,
                model="flux", storage_path="/tmp/p.png", image_url=f"/api/v1/library/files/{pid}/download",
            ))
            db.commit()

        specs = [
            {"prompt": "PG Castle var 1", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid), "workflow": "VARIATION"}},
            {"prompt": "PG Castle var 2", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid), "workflow": "VARIATION"}},
        ]
        fp_2 = compute_variation_request_fingerprint(pid, count=2)
        fp_3 = compute_variation_request_fingerprint(pid, count=3)

        def _submit_same():
            with self.PGSession() as s:
                return create_batch_image_generation_jobs(
                    db=s,
                    user_id=uid,
                    job_specs=specs,
                    idempotency_key="pg-conc-key-1",
                    parent_image_id=pid,
                    request_fingerprint=fp_2,
                    require_idempotency_key=True,
                )

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "10"}):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [f.result() for f in [pool.submit(_submit_same) for _ in range(4)]]

            created_flags = [int(created) for _, created in results]
            self.assertEqual(sum(created_flags), 1, f"Exactly 1 concurrent PG caller must create batch: {created_flags}")
            id_sets = [[j.id for j in jobs] for jobs, _ in results]
            for ids in id_sets:
                self.assertEqual(ids, id_sets[0])

            # Mismatched fingerprint with same key MUST raise IdempotencyConflictError
            with self.PGSession() as s:
                with self.assertRaises(IdempotencyConflictError):
                    create_batch_image_generation_jobs(
                        db=s,
                        user_id=uid,
                        job_specs=specs,
                        idempotency_key="pg-conc-key-1",
                        parent_image_id=pid,
                        request_fingerprint=fp_3,
                        require_idempotency_key=True,
                    )
                quota = s.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == uid,
                    UserUsageQuota.category == "image_generation",
                ).first()
                self.assertEqual(quota.usage_count, 2, "Quota MUST only be charged once for the winning batch!")

    def test_pg_concurrent_api_delete_and_worker_race(self):
        """
        Real PostgreSQL multi-session test proving API delete_document() and background
        process_storage_deletion_outbox() share one lease-fenced state machine:
        - Concurrent API delete & background worker cannot steal an active PG lease
        - Physical storage delete is executed strictly ONCE
        - Document row is removed only after physical deletion finishes
        """
        import threading
        from services.documents import delete_document

        class _PGBarrierStorage(LocalFilesystemStorage):
            def __init__(self, root_dir: str):
                super().__init__(root_dir=root_dir)
                self.started = threading.Event()
                self.allow_finish = threading.Event()
                self.delete_calls = 0
                self._lock = threading.Lock()

            def delete(self, storage_key: str) -> bool:
                with self._lock:
                    self.delete_calls += 1
                self.started.set()
                self.allow_finish.wait(timeout=5.0)
                return super().delete(storage_key)

        storage = _PGBarrierStorage(root_dir=self.tmp_dir)
        with self.PGSession() as db:
            user = _make_user(db, "pg_del_race")
            uid = user.id
            doc_id = uuid.uuid4()
            key = f"users/{uid}/documents/{doc_id}/pg_race.txt"
            storage.put(key, b"pg_race_payload", content_type="text/plain", user_id=uid)
            db.add(Document(
                id=doc_id, user_id=uid, filename="pg_race.txt", mime_type="text/plain",
                storage_path=key, storage_key=key, storage_backend="local",
            ))
            db.commit()

        holder = {}

        def _api_delete_primary():
            with self.PGSession() as s1:
                holder["primary"] = delete_document(
                    doc_id, uid, s1,
                    storage_override=storage,
                    raise_on_storage_error=False,
                    lease_seconds=30.0,
                )

        t = threading.Thread(target=_api_delete_primary)
        t.start()
        self.assertTrue(storage.started.wait(timeout=3.0), "Primary PG delete did not start")

        # While primary holds unexpired PG PROCESSING lease:
        # 1. Second independent PG API delete sees in-progress, zero duplicate delete
        with self.PGSession() as s2:
            res_second = delete_document(
                doc_id, uid, s2,
                storage_override=storage,
                raise_on_storage_error=False,
                lease_seconds=30.0,
            )
        self.assertTrue(res_second.get("already_in_progress"))
        self.assertEqual(res_second["deletion_status"], "DELETING")

        # 2. Independent PG background worker skips locked/active PROCESSING lease
        with self.PGSession() as s3:
            w_stats = process_storage_deletion_outbox(
                db=s3, limit=20, storage_override=storage, worker_id="pg_racer_worker",
            )
            self.assertEqual(w_stats["completed"], 0)
            self.assertIsNotNone(s3.query(Document).filter(Document.id == doc_id).first())

        self.assertEqual(storage.delete_calls, 1, "Physical deletion MUST only execute once under PG concurrency!")

        storage.allow_finish.set()
        t.join(timeout=5.0)
        self.assertEqual(holder["primary"]["deletion_status"], "COMPLETED")
        self.assertEqual(storage.delete_calls, 1)
        self.assertFalse(storage.exists(key))

        with self.PGSession() as s_chk:
            self.assertIsNone(s_chk.query(Document).filter(Document.id == doc_id).first())


if __name__ == "__main__":
    unittest.main()
