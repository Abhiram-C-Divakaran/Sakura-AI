import os
import sys
import uuid
import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from database.db import Base, engine, get_db_context
from database.models import User, ScheduledTask, ScheduledTaskRun, utc_now
from tasks.scheduler import TaskSchedulerService, compute_next_run


class TestSchedulerResilience(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        self.username = f"sched_res_{self.user_id.hex[:6]}"

        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=self.username,
                hashed_password="fakehashedpassword"
            )
            db.add(user)
            db.commit()

        self.scheduler = TaskSchedulerService(poll_interval_seconds=1)

    async def test_invalid_schedule_row_is_disabled_and_does_not_crash_poll(self):
        """Corrupted/invalid schedule expression disables the task and does not crash poll loop."""
        task_id = uuid.uuid4()
        now = utc_now()

        with get_db_context() as db:
            bad_task = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Corrupted Schedule Task",
                prompt="Run prompt",
                schedule="INVALID CRON EXPRESSION 99 99 *",
                timezone="UTC",
                enabled=True,
                next_run_at=now - timedelta(minutes=5)
            )
            db.add(bad_task)

            # Add a good task to ensure the poll continues processing other tasks
            good_task = ScheduledTask(
                id=uuid.uuid4(),
                user_id=self.user_id,
                title="Healthy Task",
                prompt="Healthy prompt",
                schedule="0 * * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=now - timedelta(minutes=5)
            )
            db.add(good_task)
            db.commit()
            good_task_id = good_task.id

        # Run poll
        await self.scheduler.poll_and_execute()

        # Check bad task was safely disabled and metadata updated with error
        with get_db_context() as db:
            t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            self.assertFalse(t.enabled)
            self.assertIsNotNone(t.metadata_json)
            self.assertIn("last_error", t.metadata_json)
            self.assertEqual(t.metadata_json.get("error_reason"), "invalid_schedule_or_timezone")

            # Check good task was successfully processed
            gt = db.query(ScheduledTask).filter(ScheduledTask.id == good_task_id).first()
            self.assertTrue(gt.enabled)
            gt_next = gt.next_run_at.replace(tzinfo=None) if gt.next_run_at.tzinfo else gt.next_run_at
            now_cmp = now.replace(tzinfo=None) if now.tzinfo else now
            self.assertGreater(gt_next, now_cmp)

    async def test_duplicate_occurrence_integrity_error_handled_gracefully(self):
        """Focused unit test: IntegrityError raised during occurrence dispatch is handled cleanly without crashing poll."""
        from sqlalchemy.exc import IntegrityError

        task_id = uuid.uuid4()
        now = utc_now()
        occurrence = now - timedelta(minutes=1)

        with get_db_context() as db:
            t = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Integrity Error Task",
                prompt="Prompt text",
                schedule="0 9 * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=occurrence
            )
            db.add(t)
            db.commit()

        # Patch Session.commit to raise IntegrityError on the transactional dispatch
        real_get_db = get_db_context

        class MockSessionContext:
            def __init__(self):
                self.ctx = real_get_db()
                self.session = None

            def __enter__(self):
                self.session = self.ctx.__enter__()
                orig_commit = self.session.commit
                def guarded_commit():
                    # If committing the occurrence run, simulate unique constraint collision
                    if any(isinstance(obj, ScheduledTaskRun) for obj in self.session.new):
                        raise IntegrityError("duplicate key value violates unique constraint", params=None, orig=Exception("uq_scheduled_task_run_occurrence"))
                    return orig_commit()
                self.session.commit = guarded_commit
                return self.session

            def __exit__(self, exc_type, exc_val, exc_tb):
                return self.ctx.__exit__(exc_type, exc_val, exc_tb)

        with patch("tasks.scheduler.get_db_context", side_effect=MockSessionContext):
            # Must complete cleanly without raising IntegrityError
            await self.scheduler.poll_and_execute()

    async def test_concurrent_scheduler_polling_race_executes_exactly_once(self):
        """
        P1.13: Real concurrency race test:
        Two concurrent scheduler instances poll the same due ScheduledTask simultaneously.
        Expected:
        - Exactly 1 ScheduledTaskRun
        - Exactly 1 BackgroundTask
        - next_run_at advanced correctly
        - No duplicate execution
        - No unhandled exceptions
        """
        task_id = uuid.uuid4()
        now = utc_now()
        occurrence = now - timedelta(minutes=5)

        with get_db_context() as db:
            task = ScheduledTask(
                id=task_id,
                user_id=self.user_id,
                title="Concurrent Race Task",
                prompt="Execute concurrently",
                schedule="*/10 * * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=occurrence
            )
            db.add(task)
            db.commit()

        scheduler_a = TaskSchedulerService(poll_interval_seconds=1)
        scheduler_b = TaskSchedulerService(poll_interval_seconds=1)

        # Run both schedulers concurrently
        await asyncio.gather(
            scheduler_a.poll_and_execute(),
            scheduler_b.poll_and_execute()
        )

        from database.models import BackgroundTask

        with get_db_context() as db:
            # 1. Exactly 1 ScheduledTaskRun
            runs = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id == task_id).all()
            self.assertEqual(len(runs), 1, f"Expected exactly 1 ScheduledTaskRun, got {len(runs)}")

            # 2. Exactly 1 BackgroundTask
            bg_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.user_id == self.user_id,
                BackgroundTask.type == "scheduled_run"
            ).all()
            matching_bg = [t for t in bg_tasks if (t.payload or {}).get("scheduled_task_id") == str(task_id)]
            self.assertEqual(len(matching_bg), 1, f"Expected exactly 1 BackgroundTask, got {len(matching_bg)}")

            # 3. next_run_at advanced correctly into future
            refreshed_task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            self.assertTrue(refreshed_task.enabled)
            refreshed_next = refreshed_task.next_run_at.replace(tzinfo=None) if refreshed_task.next_run_at.tzinfo else refreshed_task.next_run_at
            now_cmp = now.replace(tzinfo=None) if now.tzinfo else now
            self.assertGreater(refreshed_next, now_cmp)


if __name__ == "__main__":
    unittest.main()
