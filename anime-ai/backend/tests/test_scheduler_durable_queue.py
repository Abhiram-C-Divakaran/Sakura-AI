import os
import sys
import uuid
import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["INTEGRATION_ENCRYPTION_KEY"] = "test-integration-encryption-key-32chars!"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-testing-only-32b!"

from database.models import ScheduledTask, ScheduledTaskRun, BackgroundTask, User, utc_now
from database.db import get_db_context
from tasks.scheduler import TaskSchedulerService, compute_next_run
from tasks.worker import DurableTaskWorker
from tasks.task_manager import TaskManager, update_task_state


class TestSchedulerDurableQueue(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from database.db import Base, engine
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self._env_patch = patch.dict(os.environ, {"SAKURA_EMBEDDED_WORKER": "false"})
        self._env_patch.start()
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            # Clean up leftover tasks and schedules for clean test isolation
            db.query(BackgroundTask).delete()
            db.query(ScheduledTaskRun).delete()
            db.query(ScheduledTask).delete()
            user = db.query(User).filter(User.id == self.user_id).first()
            if not user:
                user = User(
                    id=self.user_id,
                    username=f"sched_dur_{uuid.uuid4().hex[:6]}",
                    hashed_password="pw"
                )
                db.add(user)
            db.commit()

    def tearDown(self):
        self._env_patch.stop()
        from main import app
        app.dependency_overrides.clear()

    async def test_scheduler_restart_does_not_duplicate_occurrence(self):
        """Scheduler crash/restart cannot duplicate an occurrence that was already dispatched."""
        due_time = utc_now() - timedelta(minutes=10)
        task_id = uuid.uuid4()

        with get_db_context() as db:
            task = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Idempotent Task",
                prompt="Report metrics",
                schedule="0 9 * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=due_time
            )
            db.add(task)
            db.commit()

        sched1 = TaskSchedulerService()
        await sched1.poll_and_execute()

        # Check that 1 run was created
        with get_db_context() as db:
            runs = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id == task_id).all()
            self.assertEqual(len(runs), 1)
            t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            # Temporarily reset next_run_at back to due_time to simulate crash right after claim
            t.next_run_at = due_time
            db.commit()

        # Restart scheduler
        sched2 = TaskSchedulerService()
        await sched2.poll_and_execute()

        with get_db_context() as db:
            # Idempotency check prevents duplicate run for the same scheduled_for
            runs_after = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id == task_id).all()
            self.assertEqual(len(runs_after), 1, "Scheduler restart must not create duplicate ScheduledTaskRun for the same occurrence.")

    async def test_scheduler_dispatch_to_worker_execution(self):
        """Scheduler enqueues work, and the SakuraWorker executes it durably to completion."""
        due_time = utc_now() - timedelta(minutes=5)
        task_id = uuid.uuid4()

        with get_db_context() as db:
            task = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Durable Execution Task",
                prompt="Daily summary",
                schedule="0 9 * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=due_time
            )
            db.add(task)
            db.commit()

        # 1. Scheduler polls and enqueues
        sched = TaskSchedulerService()
        await sched.poll_and_execute()

        with get_db_context() as db:
            run = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id == task_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "QUEUED")
            run_id = run.id

            bg_task = db.query(BackgroundTask).filter(
                BackgroundTask.type == "scheduled_run"
            ).order_by(BackgroundTask.created_at.desc()).first()
            self.assertIsNotNone(bg_task)
            self.assertEqual(bg_task.status, "Queued")
            bg_task_id = bg_task.id

        # 2. Worker claims and executes task
        worker = DurableTaskWorker(worker_id="test-durable-worker")
        
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value="LLM executed scheduled report successfully!")
        
        with patch.object(worker.router, "get_provider", return_value=("mock_llm", mock_provider)):
            claimed = worker.claim_next_task()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.id, bg_task_id)

            await worker.execute_task(claimed)

        # 3. Verify ScheduledTaskRun and BackgroundTask both reached terminal COMPLETED
        with get_db_context() as db:
            final_run = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.id == run_id).first()
            self.assertEqual(final_run.status, "COMPLETED")
            self.assertIn("LLM executed scheduled report", final_run.output)
            self.assertIsNotNone(final_run.completed_at)

            final_bg = db.query(BackgroundTask).filter(BackgroundTask.id == bg_task_id).first()
            self.assertEqual(final_bg.status, "Completed")
            self.assertEqual(final_bg.progress, 100)

    async def test_manual_trigger_creates_durable_run_and_worker_executes(self):
        """Manual run returns HTTP 202, creates durable run, and executes through the worker."""
        task_id = uuid.uuid4()
        with get_db_context() as db:
            task = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Manual Run Task",
                prompt="Execute immediately",
                schedule="0 9 * * *",
                timezone="UTC",
                enabled=True
            )
            db.add(task)
            db.commit()

        from fastapi.testclient import TestClient
        from main import app
        from auth.manager import AuthManager

        user_obj = None
        with get_db_context() as db:
            user_obj = db.query(User).filter(User.id == self.user_id).first()

        app.dependency_overrides[AuthManager.get_current_user] = lambda: user_obj

        client = TestClient(app)
        response = client.post(f"/api/v1/scheduled/{task_id}/run")
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["status"], "QUEUED")
        self.assertIn("run_id", data)
        self.assertIn("background_task_id", data)

        run_id = uuid.UUID(data["run_id"])
        bg_id = uuid.UUID(data["background_task_id"])

        # Execute via worker
        worker = DurableTaskWorker(worker_id="test-manual-worker")
        claimed = worker.claim_next_task()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, bg_id)

        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value="Manual run output completed.")
        
        with patch.object(worker.router, "get_provider", return_value=("mock_llm", mock_provider)):
            await worker.execute_task(claimed)

        with get_db_context() as db:
            run = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.id == run_id).first()
            self.assertEqual(run.status, "COMPLETED")
            self.assertEqual(run.output, "Manual run output completed.")


if __name__ == "__main__":
    unittest.main()
