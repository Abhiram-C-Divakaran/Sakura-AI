import os
import sys
import uuid
import asyncio
import unittest

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from database.db import Base, engine, get_db_context
from database.models import User, BackgroundTask, utc_now
from tasks.task_manager import (
    update_task_state,
    assert_task_lease_owned,
    TaskLeaseLostError
)
from tasks.worker import DurableTaskWorker


class TestWorkerFencing(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        BackgroundTask.__table__.drop(bind=engine, checkfirst=True)
        BackgroundTask.__table__.create(bind=engine, checkfirst=True)
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        self.username = f"fence_user_{self.user_id.hex[:6]}"

        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=self.username,
                hashed_password="fakehashedpassword"
            )
            db.add(user)
            db.commit()

    async def test_worker_fencing_token_rejects_stale_worker(self):
        task_id = uuid.uuid4()
        with get_db_context() as db:
            task = BackgroundTask(
                id=task_id,
                user_id=self.user_id,
                type="code_analysis",
                title="Fencing Test Task",
                status="Queued"
            )
            db.add(task)
            db.commit()

        worker_a = DurableTaskWorker(worker_id="worker-node-A")
        worker_b = DurableTaskWorker(worker_id="worker-node-B")

        # 1. Worker A claims the task
        claimed_a = worker_a.claim_next_task()
        self.assertIsNotNone(claimed_a)
        self.assertEqual(claimed_a.id, task_id)
        token_a = claimed_a.execution_attempt_id
        self.assertIsNotNone(token_a)

        # Worker A can verify lease ownership
        self.assertTrue(assert_task_lease_owned(task_id, worker_a.worker_id, token_a))

        # Worker A updates progress successfully
        res = await update_task_state(
            task_id=task_id,
            status="Running",
            progress=25,
            worker_id=worker_a.worker_id,
            execution_attempt_id=token_a
        )
        self.assertEqual(res["progress"], 25)

        # 2. Simulate Worker A lease expiration and Worker B claiming the task
        with get_db_context() as db:
            db_task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            token_b = uuid.uuid4()
            db_task.worker_id = worker_b.worker_id
            db_task.execution_attempt_id = token_b
            db_task.status = "Running"
            db.commit()

        # 3. Worker A tries to assert ownership with stale token -> raises TaskLeaseLostError
        with self.assertRaises(TaskLeaseLostError):
            assert_task_lease_owned(task_id, worker_a.worker_id, token_a)

        # 4. Worker A tries to update state with stale token -> raises TaskLeaseLostError
        with self.assertRaises(TaskLeaseLostError):
            await update_task_state(
                task_id=task_id,
                status="Running",
                progress=50,
                worker_id=worker_a.worker_id,
                execution_attempt_id=token_a
            )

        # 5. Worker B with valid token succeeds
        self.assertTrue(assert_task_lease_owned(task_id, worker_b.worker_id, token_b))
        res_b = await update_task_state(
            task_id=task_id,
            status="Completed",
            progress=100,
            result="Completed by Worker B",
            worker_id=worker_b.worker_id,
            execution_attempt_id=token_b
        )
        self.assertEqual(res_b["status"], "Completed")

    async def test_execute_task_aborts_without_overwriting_when_owned_by_another_worker(self):
        """Worker A attempting execute_task on a task owned by Worker B raises TaskLeaseLostError without overwriting DB."""
        task_id = uuid.uuid4()
        token_b = uuid.uuid4()
        worker_a = DurableTaskWorker(worker_id="worker-node-A")
        worker_b = DurableTaskWorker(worker_id="worker-node-B")

        with get_db_context() as db:
            task = BackgroundTask(
                id=task_id,
                user_id=self.user_id,
                type="code_analysis",
                title="Fencing Takeover Test",
                status="Running",
                worker_id=worker_b.worker_id,
                execution_attempt_id=token_b
            )
            db.add(task)
            db.commit()

        # Worker A attempts to execute task with its own stale token
        stale_task = BackgroundTask(
            id=task_id,
            user_id=self.user_id,
            type="code_analysis",
            title="Fencing Takeover Test",
            status="Running",
            worker_id=worker_a.worker_id,
            execution_attempt_id=uuid.uuid4()
        )

        with self.assertRaises(TaskLeaseLostError):
            await worker_a.execute_task(stale_task)

        # In DB, Worker B's ownership must remain completely intact and unaltered
        with get_db_context() as db:
            db_task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            self.assertEqual(db_task.worker_id, worker_b.worker_id)
            self.assertEqual(db_task.execution_attempt_id, token_b)
            self.assertEqual(db_task.status, "Running")


if __name__ == "__main__":
    unittest.main()
