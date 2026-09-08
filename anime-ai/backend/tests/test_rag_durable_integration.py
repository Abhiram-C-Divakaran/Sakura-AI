import os
import sys
import uuid
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_STORAGE_BACKEND"] = "local"

from database.db import Base, engine, get_db_context
from database.models import User, Document, DocumentChunk, BackgroundTask, DocumentIndexingStatus
from services.storage import get_storage_backend, build_document_storage_key
from tasks.worker import DurableTaskWorker
from rag.retrieval import HybridRetriever
from api.library import remove_file_from_knowledge_base


class TestRagDurableIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        DocumentChunk.__table__.drop(bind=engine, checkfirst=True)
        Document.__table__.drop(bind=engine, checkfirst=True)
        BackgroundTask.__table__.drop(bind=engine, checkfirst=True)
        Document.__table__.create(bind=engine, checkfirst=True)
        DocumentChunk.__table__.create(bind=engine, checkfirst=True)
        BackgroundTask.__table__.create(bind=engine, checkfirst=True)
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        self.username = f"test_rag_user_{self.user_id.hex[:6]}"

        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=self.username,
                hashed_password="fakehashedpassword"
            )
            db.add(user)
            db.commit()

        self.storage = get_storage_backend()

    async def test_full_rag_indexing_and_removal_lifecycle(self):
        doc_id = uuid.uuid4()
        filename = "quantum_computing_notes.txt"
        storage_key = build_document_storage_key(str(self.user_id), str(doc_id), filename)
        content = (
            "Quantum superposition enables qubits to exist in complex linear combinations of states. "
            "Shor's algorithm provides exponential speedup for integer factorization. "
            "Quantum error correction uses topological surface codes to protect quantum information."
        ).encode("utf-8")

        # 1. Put document into durable storage
        self.storage.put(storage_key, content, content_type="text/plain")

        # 2. Register document in database as QUEUED for indexing
        with get_db_context() as db:
            doc = Document(
                id=doc_id,
                user_id=self.user_id,
                filename=filename,
                mime_type="text/plain",
                storage_path=storage_key,
                storage_backend=self.storage.backend_type,
                storage_key=storage_key,
                storage_size=len(content),
                is_knowledge_base=False,
                indexing_status=DocumentIndexingStatus.QUEUED,
                metadata_json={"title": "Quantum Notes"}
            )
            db.add(doc)

            # Create background task for document_index
            bg_task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=self.user_id,
                type="document_index",
                title=f"Index: {filename}",
                payload={
                    "document_id": str(doc_id),
                    "force_reindex": True
                },
                status="Queued"
            )
            db.add(bg_task)
            db.commit()
            task_id = bg_task.id

        # 3. Worker claims and executes document_index task
        worker = DurableTaskWorker(worker_id="test-rag-worker")
        claimed = worker.claim_next_task()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, task_id)

        # Execute task
        await worker.execute_task(claimed)

        # 4. Verify document state transitions in authoritative DB columns
        with get_db_context() as db:
            updated_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertIsNotNone(updated_doc)
            self.assertTrue(updated_doc.is_knowledge_base)
            self.assertEqual(updated_doc.indexing_status, DocumentIndexingStatus.READY)

            chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
            self.assertGreater(len(chunks), 0)

        # 5. Verify HybridRetriever retrieves content from knowledge base
        with get_db_context() as db:
            retriever = HybridRetriever(db)
            results = await retriever.retrieve(self.user_id, "Shor's algorithm quantum factorization", limit=3)
            self.assertGreater(len(results), 0)
            retrieved_chunk = results[0]
            self.assertIn("quantum", retrieved_chunk.get("content", "").lower())

        # 6. Remove document from knowledge base via API handler
        with get_db_context() as db:
            user_obj = db.query(User).filter(User.id == self.user_id).first()
            remove_res = await remove_file_from_knowledge_base(str(doc_id), current_user=user_obj, db=db)
            self.assertEqual(remove_res["status"], "removed_from_knowledge_base")

        # 7. Verify authoritative DB columns and chunk deletion
        with get_db_context() as db:
            final_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertFalse(final_doc.is_knowledge_base)
            self.assertEqual(final_doc.indexing_status, DocumentIndexingStatus.NOT_INDEXED)

            remaining_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
            self.assertEqual(remaining_chunks, 0)

            # Retriever must return 0 results now that document is removed from KB
            retriever = HybridRetriever(db)
            empty_results = await retriever.retrieve(self.user_id, "Shor's algorithm quantum factorization", limit=3)
            self.assertEqual(len(empty_results), 0)


if __name__ == "__main__":
    unittest.main()
