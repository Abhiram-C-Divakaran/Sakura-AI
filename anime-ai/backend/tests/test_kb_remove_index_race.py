import os
import sys
import uuid
import tempfile
import unittest
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from database.db import Base, engine, get_db_context
from database.models import User, Document, DocumentChunk, DocumentIndexingStatus, BackgroundTask
from services.documents import create_document, remove_from_kb, enqueue_index
from tasks.task_manager import execute_document_index, TaskExecutionContext, TaskLeaseLostError


class TestKBRemoveIndexRace(unittest.IsolatedAsyncioTestCase):
    """
    Tests race condition where a document is removed from KB while indexing is underway.
    Proves that a stale generation worker cannot commit chunks or mark document READY.
    """

    async def asyncSetUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=f"kb_user_{self.user_id.hex[:6]}",
                hashed_password="fakehashedpassword"
            )
            db.add(user)
            db.commit()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_root = os.environ.get("SAKURA_STORAGE_ROOT")
        os.environ["SAKURA_STORAGE_ROOT"] = self.temp_dir.name

    async def asyncTearDown(self):
        if self.orig_root:
            os.environ["SAKURA_STORAGE_ROOT"] = self.orig_root
        else:
            os.environ.pop("SAKURA_STORAGE_ROOT", None)
        self.temp_dir.cleanup()

    async def test_remove_from_kb_aborts_stale_generation_indexing_worker(self):
        # 1. Create document in KB initially
        doc_text = "# Important Knowledge Base Document\n\nSection 1: Distributed architecture.\nSection 2: Worker fencing."
        with get_db_context() as db:
            doc = create_document(
                filename="system_architecture.md",
                content=doc_text,
                user_id=self.user_id,
                db=db
            )
            doc_id = doc.id
            init_gen = doc.index_generation

        # 2. Enqueue indexing task (increments generation to 2)
        with get_db_context() as db:
            task = enqueue_index(doc_id=doc_id, user_id=self.user_id, db=db)
            task_id = task.id
            task_gen = task.payload["index_generation"]
            self.assertEqual(task_gen, init_gen + 1)

        # 3. Simulate Worker starting indexing under task_gen (e.g. generation 2)
        ctx = TaskExecutionContext(
            task_id=task_id,
            worker_id="test_worker_alpha",
            execution_attempt_id=uuid.uuid4(),
            lease_lost_event=asyncio.Event()
        )

        # Before the worker reaches final commit, user removes document from KB
        with get_db_context() as db:
            remove_res = remove_from_kb(doc_id=doc_id, user_id=self.user_id, db=db)
            self.assertTrue(remove_res)
            # Re-read document
            refreshed = db.query(Document).filter(Document.id == doc_id).first()
            self.assertEqual(refreshed.index_generation, task_gen + 1)
            self.assertEqual(refreshed.indexing_status, DocumentIndexingStatus.NOT_INDEXED)
            self.assertFalse(refreshed.is_knowledge_base)

        # 4. Now execute_document_index with the stale generation task payload
        # It must raise TaskLeaseLostError and abort immediately
        with self.assertRaises(TaskLeaseLostError):
            await execute_document_index(
                task_id=task_id,
                user_id=self.user_id,
                payload={
                    "document_id": str(doc_id),
                    "requested_by_user_id": str(self.user_id),
                    "index_generation": task_gen,
                    "force_reindex": False
                },
                ctx=ctx
            )

        # 5. Verify final state in DB:
        # - cannot create chunks
        # - cannot set READY
        # - cannot set is_knowledge_base=True
        # - final state: NOT_INDEXED, is_knowledge_base=False, 0 chunks
        with get_db_context() as db:
            final_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertEqual(final_doc.indexing_status, DocumentIndexingStatus.NOT_INDEXED)
            self.assertFalse(final_doc.is_knowledge_base)
            chunks_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
            self.assertEqual(chunks_count, 0)


if __name__ == "__main__":
    unittest.main()
