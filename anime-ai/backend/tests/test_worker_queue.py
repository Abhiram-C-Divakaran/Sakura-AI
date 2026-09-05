import os
import sys
import uuid
import unittest
from datetime import datetime, timezone, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"

from database.models import BackgroundTask, User, utc_now
from database.db import get_db_context
from tasks.task_manager import TaskManager
from tasks.worker import DurableTaskWorker, MAX_RETRIES


class TestWorkerQueue(unittest.TestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            db.query(BackgroundTask).delete()
            user = db.query(User).filter(User.id == self.user_id).first()
            if not user:
                user = User(
                    id=self.user_id,
                    username=f"worker_user_{uuid.uuid4().hex[:6]}",
                    hashed_password="hash"
                )
                db.add(user)
            db.commit()

    def test_task_creation_persists_as_queued(self):
        """TaskManager.create_task must persist task with status='Queued'."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Review PR #42",
            payload={"code": "def foo(): pass"}
        )
        self.assertIsNotNone(task.id)
        self.assertEqual(task.status, "Queued")
        self.assertEqual(task.progress, 0)
        self.assertEqual(task.retry_count, 0)

        # Verify in database
        with get_db_context() as db:
            db_task = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertIsNotNone(db_task)
            self.assertEqual(db_task.status, "Queued")

    def test_atomic_claim_and_concurrency(self):
        """When worker 1 claims a task, worker 2 cannot claim the same task."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="doc_summary",
            title="Summarize Spec",
            payload={"document_id": str(uuid.uuid4())}
        )

        worker1 = DurableTaskWorker(worker_id="worker_alpha_1")
        worker2 = DurableTaskWorker(worker_id="worker_beta_2")

        # Worker 1 claims
        claimed_by_1 = worker1.claim_next_task()
        self.assertIsNotNone(claimed_by_1)
        self.assertEqual(claimed_by_1.id, task.id)
        self.assertEqual(claimed_by_1.status, "Running")
        self.assertEqual(claimed_by_1.worker_id, "worker_alpha_1")

        # Worker 2 attempts claim; must get None
        claimed_by_2 = worker2.claim_next_task()
        # Either None or a different task, definitely NOT task.id
        if claimed_by_2:
            self.assertNotEqual(claimed_by_2.id, task.id)

    def test_recover_stale_tasks_requeues(self):
        """Orphaned tasks in 'Running' state are recovered back to 'Queued' with incremented retry_count."""
        with get_db_context() as db:
            stale_task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=self.user_id,
                type="code_analysis",
                title="Crashed Job",
                status="Running",
                worker_id="dead_worker_999",
                started_at=utc_now(),
                lease_expires_at=utc_now() - timedelta(minutes=2),
                retry_count=0
            )
            db.add(stale_task)
            db.commit()
            stale_task_id = stale_task.id

        worker = DurableTaskWorker(worker_id="worker_recovery_test")
        recovered = worker.recover_stale_tasks()
        self.assertGreaterEqual(recovered, 1)

        with get_db_context() as db:
            updated = db.query(BackgroundTask).filter(BackgroundTask.id == stale_task_id).first()
            self.assertEqual(updated.status, "Queued")
            self.assertEqual(updated.retry_count, 1)
            self.assertIsNone(updated.worker_id)

    def test_stale_task_fails_after_max_retries(self):
        """Tasks exceeding MAX_RETRIES are marked 'Failed' during recovery."""
        with get_db_context() as db:
            dead_task = BackgroundTask(
                id=uuid.uuid4(),
                user_id=self.user_id,
                type="code_analysis",
                title="Fatal Poison Job",
                status="Running",
                worker_id="dead_worker_abc",
                started_at=utc_now(),
                lease_expires_at=utc_now() - timedelta(minutes=2),
                retry_count=MAX_RETRIES
            )
            db.add(dead_task)
            db.commit()
            dead_task_id = dead_task.id

        worker = DurableTaskWorker(worker_id="worker_recovery_max_test")
        worker.recover_stale_tasks()

        with get_db_context() as db:
            updated = db.query(BackgroundTask).filter(BackgroundTask.id == dead_task_id).first()
            self.assertEqual(updated.status, "Failed")
            self.assertIsNotNone(updated.completed_at)
            self.assertIn("exceeded maximum retries", updated.error)


if __name__ == "__main__":
    unittest.main()
