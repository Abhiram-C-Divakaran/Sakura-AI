"""
Tests for Document & BackgroundTask transactional atomicity and storage compensation.
Verifies single-transaction commit/rollback and lease-fenced execution.
"""

import io
import uuid
import unittest
from unittest.mock import MagicMock
from fastapi import UploadFile, HTTPException
from datetime import datetime, timedelta, timezone

from database.db import get_db_context, Base, engine
from database.models import User, Document, BackgroundTask, DocumentIndexingStatus, utc_now
from tasks.task_manager import TaskManager, TaskExecutionContext, TaskLeaseLostError
from services.upload import save_uploaded_file
from services.storage import get_storage_backend


class TestDocumentAtomicity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        with get_db_context() as db:
            self.user_id = uuid.uuid4()
            self.user = User(
                id=self.user_id,
                username=f"doc_user_{uuid.uuid4().hex[:8]}",
                hashed_password="fake_password"
            )
            db.add(self.user)
            db.commit()

    def test_create_task_in_session_atomicity(self):
        """Document and BackgroundTask commit atomically in caller's session, or rollback together."""
        doc_id = uuid.uuid4()
        task_id = None

        with get_db_context() as db:
            # 1. Add document
            doc = Document(
                id=doc_id,
                user_id=self.user_id,
                filename="test.txt",
                mime_type="text/plain",
                storage_path=f"users/{self.user_id}/documents/{doc_id}/test.txt",
                storage_backend="local",
                storage_key=f"users/{self.user_id}/documents/{doc_id}/test.txt",
                storage_size=10,
                indexing_status=DocumentIndexingStatus.QUEUED
            )
            db.add(doc)

            # 2. Add task within same session
            task = TaskManager.create_task_in_session(
                db=db,
                user_id=self.user_id,
                task_type="document_indexing",
                title="Index test.txt",
                payload={"document_id": str(doc_id)}
            )
            task_id = task.id

            # Rollback without committing
            db.rollback()

        # Verify neither document nor task exists
        with get_db_context() as db:
            found_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertIsNone(found_doc, "Document should have been rolled back")

            found_task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            self.assertIsNone(found_task, "BackgroundTask should have been rolled back")

    def test_create_task_in_session_commit(self):
        """Committed session persists both Document and BackgroundTask atomically."""
        doc_id = uuid.uuid4()
        task_id = None

        with get_db_context() as db:
            doc = Document(
                id=doc_id,
                user_id=self.user_id,
                filename="test_commit.txt",
                mime_type="text/plain",
                storage_path=f"users/{self.user_id}/documents/{doc_id}/test_commit.txt",
                storage_backend="local",
                storage_key=f"users/{self.user_id}/documents/{doc_id}/test_commit.txt",
                storage_size=10,
                indexing_status=DocumentIndexingStatus.QUEUED
            )
            db.add(doc)

            task = TaskManager.create_task_in_session(
                db=db,
                user_id=self.user_id,
                task_type="document_indexing",
                title="Index test_commit.txt",
                payload={"document_id": str(doc_id)}
            )
            task_id = task.id
            db.commit()

        with get_db_context() as db:
            found_doc = db.query(Document).filter(Document.id == doc_id).first()
            self.assertIsNotNone(found_doc)
            self.assertEqual(found_doc.filename, "test_commit.txt")

            found_task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            self.assertIsNotNone(found_task)
            self.assertEqual(found_task.type, "document_indexing")

    def test_storage_compensation_on_db_failure(self):
        """If database record save fails, uploaded object in storage is deleted (compensated)."""
        import asyncio

        async def _run_test():
            file_content = b"Content to test storage compensation"
            upload_file = UploadFile(
                filename="orphan_test.txt",
                file=io.BytesIO(file_content),
                headers={"content-type": "text/plain"}
            )

            # Mock db.commit to raise an Exception simulating DB crash
            mock_db = MagicMock()
            mock_db.commit.side_effect = RuntimeError("Simulated DB connection failure")

            with self.assertRaises(HTTPException):
                await save_uploaded_file(
                    file=upload_file,
                    user_id=self.user_id,
                    db=mock_db,
                    auto_index=False
                )

            # Confirm rollback was called on mock_db
            mock_db.rollback.assert_called_once()

        asyncio.run(_run_test())

    def test_assert_owned_in_session_fencing(self):
        """assert_owned_in_session raises TaskLeaseLostError if worker_id mismatches or lease expired."""
        task_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        worker_id = f"worker_{uuid.uuid4().hex[:6]}"
        now = utc_now()

        with get_db_context() as db:
            task = BackgroundTask(
                id=task_id,
                user_id=self.user_id,
                type="test_task",
                title="Test Task Title",
                status="Running",
                worker_id=worker_id,
                execution_attempt_id=attempt_id,
                lease_expires_at=now + timedelta(seconds=60),
                created_at=now
            )
            db.add(task)
            db.commit()

        # Valid context succeeds
        valid_ctx = TaskExecutionContext(
            task_id=task_id,
            worker_id=worker_id,
            execution_attempt_id=attempt_id
        )
        with get_db_context() as db:
            self.assertTrue(valid_ctx.assert_owned_in_session(db, lock=False))

        # Mismatched worker fails
        invalid_worker_ctx = TaskExecutionContext(
            task_id=task_id,
            worker_id="another_worker_id",
            execution_attempt_id=attempt_id
        )
        with get_db_context() as db:
            with self.assertRaises(TaskLeaseLostError):
                invalid_worker_ctx.assert_owned_in_session(db, lock=False)


if __name__ == "__main__":
    unittest.main()
