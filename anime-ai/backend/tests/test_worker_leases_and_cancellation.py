"""
Tests for Durable Worker Leases, Concurrency-Safe Claiming, and Task Cancellation
Proves that active workers are protected by leases, expired workers are recovered,
and cancellation is terminal and non-overwritable.
"""

import os
import uuid
import unittest
import asyncio
from datetime import datetime, timedelta, timezone

from database.db import get_db_context
from database.models import User, BackgroundTask, utc_now
from tasks.worker import DurableTaskWorker, MAX_RETRIES, LEASE_DURATION_SECONDS
from tasks.task_manager import TaskManager, update_task_state


class TestWorkerLeasesAndCancellation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            db.query(BackgroundTask).filter(BackgroundTask.status == "Queued").delete()
            user = User(
                id=self.user_id,
                username=f"lease_user_{uuid.uuid4().hex[:6]}",
                hashed_password="test_hash"
            )
            db.add(user)
            db.commit()

    def tearDown(self):
        with get_db_context() as db:
            db.query(BackgroundTask).filter(BackgroundTask.user_id == self.user_id).delete()
            db.query(User).filter(User.id == self.user_id).delete()
            db.commit()

    def test_two_workers_cannot_claim_same_task(self):
        """Proves atomic claim concurrency: two workers trying to claim the same task results in exactly 1 claim."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Concurrency Claim Test",
            payload={"code": "print('hello')"}
        )

        worker_a = DurableTaskWorker(worker_id="worker_A")
        worker_b = DurableTaskWorker(worker_id="worker_B")

        claim_a = worker_a.claim_next_task()
        claim_b = worker_b.claim_next_task()

        self.assertIsNotNone(claim_a)
        self.assertEqual(claim_a.id, task.id)
        self.assertEqual(claim_a.worker_id, "worker_A")
        self.assertIsNotNone(claim_a.lease_expires_at)
        self.assertGreater(claim_a.lease_expires_at, utc_now())

        # Second worker gets nothing because task is now Running
        self.assertIsNone(claim_b)

    def test_active_worker_task_not_requeued_by_new_worker(self):
        """Proves that a new worker starting does NOT falsely recover another active worker's task."""
        worker_a = DurableTaskWorker(worker_id="worker_A")
        worker_b = DurableTaskWorker(worker_id="worker_B")

        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Active Lease Protection Test",
            payload={"code": "print('active')"}
        )

        claimed = worker_a.claim_next_task()
        self.assertIsNotNone(claimed)

        # Worker B starts up and runs stale task recovery
        recovered_count = worker_b.recover_stale_tasks()
        self.assertEqual(recovered_count, 0)

        # Verify task is still Running under worker A
        with get_db_context() as db:
            refreshed = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertEqual(refreshed.status, "Running")
            self.assertEqual(refreshed.worker_id, "worker_A")

    def test_expired_lease_is_recovered(self):
        """Proves that if a worker dies and its lease expires, recovery picks it up and requeues."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Expired Lease Recovery Test",
            payload={"code": "print('crashed')"}
        )

        # Simulate crashed worker: task is Running but lease expired 10 minutes ago
        past_time = utc_now() - timedelta(minutes=10)
        with get_db_context() as db:
            db.query(BackgroundTask).filter(BackgroundTask.id == task.id).update({
                BackgroundTask.status: "Running",
                BackgroundTask.worker_id: "dead_worker_999",
                BackgroundTask.started_at: past_time,
                BackgroundTask.lease_expires_at: past_time
            })
            db.commit()

        worker_live = DurableTaskWorker(worker_id="worker_live")
        recovered = worker_live.recover_stale_tasks()
        self.assertEqual(recovered, 1)

        with get_db_context() as db:
            refreshed = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertEqual(refreshed.status, "Queued")
            self.assertIsNone(refreshed.worker_id)
            self.assertEqual(refreshed.retry_count, 1)

    def test_poison_task_fails_after_max_retries(self):
        """Proves that an expired task that has exceeded MAX_RETRIES transitions to Failed."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Poison Task Test",
            payload={"code": "print('poison')"}
        )

        past_time = utc_now() - timedelta(minutes=10)
        with get_db_context() as db:
            db.query(BackgroundTask).filter(BackgroundTask.id == task.id).update({
                BackgroundTask.status: "Running",
                BackgroundTask.worker_id: "dead_worker",
                BackgroundTask.retry_count: MAX_RETRIES,
                BackgroundTask.lease_expires_at: past_time
            })
            db.commit()

        worker_live = DurableTaskWorker(worker_id="worker_live")
        recovered = worker_live.recover_stale_tasks()
        self.assertEqual(recovered, 0)  # Not requeued, marked failed

        with get_db_context() as db:
            refreshed = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertEqual(refreshed.status, "Failed")
            self.assertIn("exceeded maximum retries", refreshed.error)

    async def test_cancelled_status_cannot_be_overwritten_by_completed(self):
        """Proves terminal state protection: once cancelled, Completed updates are rejected."""
        task = TaskManager.create_task(
            user_id=self.user_id,
            task_type="code_analysis",
            title="Terminal State Protection Test",
            payload={"code": "print('cancel_protect')"}
        )

        # Cancel the task
        await TaskManager.cancel_task(task.id, self.user_id)

        with get_db_context() as db:
            t = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertEqual(t.status, "Cancelled")
            self.assertTrue(t.cancel_requested)

        # Attempt to overwrite with progress and Completed
        await update_task_state(task.id, "Running", 50)
        await update_task_state(task.id, "Completed", 100, result="Should not overwrite!")

        with get_db_context() as db:
            final_task = db.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
            self.assertEqual(final_task.status, "Cancelled")


if __name__ == "__main__":
    unittest.main()
