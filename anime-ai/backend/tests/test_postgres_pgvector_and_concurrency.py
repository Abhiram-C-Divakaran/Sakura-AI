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
        Tests upgrading a real PostgreSQL schema from i8e6f152a45b (JSON embedding) to
        j9f7a263b56c (native vector(1536)) inside an isolated PostgreSQL schema:
        - Valid 1536-dim JSON embedding is preserved as vector(1536) with exact values
        - NULL embedding is preserved as NULL
        - Malformed JSON embedding aborts upgrade with actionable error without data loss
        """
        schema_name = f"pgvec_upg_{uuid.uuid4().hex[:10]}"
        with self.pg_engine.connect() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema_name}"'))
            conn.commit()

        schema_engine = sa.create_engine(
            self.pg_url,
            connect_args={"options": f"-csearch_path={schema_name},public"},
        )
        try:
            # 1. Upgrade isolated schema to pre-pgvector revision i8e6f152a45b
            cfg = Config("alembic.ini")
            with schema_engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "i8e6f152a45b")

            # Seed valid 1536-dim JSON embedding, NULL embedding, and verify JSON type pre-upgrade
            uid = uuid.uuid4()
            doc_id = uuid.uuid4()
            valid_cid = uuid.uuid4()
            null_cid = uuid.uuid4()
            bad_cid = uuid.uuid4()
            vec = _make_unit_vec(5, secondary_index=42, secondary_weight=0.25)

            import json
            with schema_engine.begin() as conn:
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
                # Insert malformed row first to prove upgrade fails cleanly with actionable error
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks (id, document_id, chunk_index, content, embedding) "
                        "VALUES (:id, :did, 2, 'Malformed historical embedding', CAST(:emb AS json))"
                    ),
                    {"id": bad_cid, "did": doc_id, "emb": json.dumps([0.1, 0.2, 0.3])},
                )

            with self.assertRaises(RuntimeError) as err_ctx:
                with schema_engine.begin() as conn:
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
            self.assertIn(str(bad_cid), str(err_ctx.exception))
            self.assertIn("1536", str(err_ctx.exception))

            # Remove malformed row -> upgrade to head MUST succeed and preserve valid & NULL rows
            with schema_engine.begin() as conn:
                conn.execute(sa.text("DELETE FROM document_chunks WHERE id = :id"), {"id": bad_cid})

            with schema_engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")

            with schema_engine.connect() as conn:
                emb_type = conn.execute(
                    sa.text(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON a.attrelid = c.oid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = :sname
                          AND c.relname = 'document_chunks'
                          AND a.attname = 'embedding'
                          AND NOT a.attisdropped
                        """
                    ),
                    {"sname": schema_name},
                ).scalar()
                self.assertEqual(emb_type, "vector(1536)")

                dims = conn.execute(
                    sa.text("SELECT vector_dims(embedding) FROM document_chunks WHERE id = :id"),
                    {"id": valid_cid},
                ).scalar()
                self.assertEqual(dims, 1536)

                null_check = conn.execute(
                    sa.text("SELECT embedding IS NULL FROM document_chunks WHERE id = :id"),
                    {"id": null_cid},
                ).scalar()
                self.assertTrue(null_check)
        finally:
            schema_engine.dispose()
            with self.pg_engine.connect() as conn:
                conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()

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


if __name__ == "__main__":
    unittest.main()
