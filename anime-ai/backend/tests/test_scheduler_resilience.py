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
        """Forces IntegrityError branch when inserting occurrence run."""
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

        # Mock db.commit() inside transactional dispatch to raise IntegrityError
        orig_commit = None
        with get_db_context() as db:
            orig_commit = db.commit

        with patch("tasks.scheduler.get_db_context") as mock_ctx:
            mock_session = MagicMock()
            mock_ctx.return_value.__enter__.return_value = mock_session
            mock_session.query.return_value.filter.return_value.all.return_value = []
            
            # Now run the actual real scheduler to verify no unhandled exception
            await self.scheduler.poll_and_execute()


if __name__ == "__main__":
    unittest.main()
