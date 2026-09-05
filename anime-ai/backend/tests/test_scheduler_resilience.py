import os
import sys
import uuid
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"

from database.models import ScheduledTask, User, utc_now
from database.db import get_db_context
from tasks.scheduler import (
    compute_next_run,
    validate_schedule_expression,
    validate_timezone,
    TaskSchedulerService,
)


class TestSchedulerResilience(unittest.TestCase):
    def test_invalid_schedule_expression_raises_value_error(self):
        """Invalid cron and unknown schedule strings must raise ValueError (no silent 24h fallback)."""
        invalid_schedules = [
            "invalid cron string",
            "not a schedule",
            "* * *",        # only 3 fields
            "60 * * * *",    # invalid minute (0-59)
            "",
        ]
        for s in invalid_schedules:
            with self.subTest(schedule=s):
                with self.assertRaises(ValueError):
                    validate_schedule_expression(s)

                with self.assertRaises(ValueError):
                    compute_next_run(s, tz_name="UTC")

    def test_invalid_timezone_raises_value_error(self):
        """Invalid timezone identifiers must raise ValueError (no silent UTC fallback)."""
        invalid_tzs = [
            "Mars/Olympus_Mons",
            "Fake/Timezone",
            "NotATimezone",
            "12345",
        ]
        for tz in invalid_tzs:
            with self.subTest(timezone=tz):
                with self.assertRaises(ValueError):
                    validate_timezone(tz)

                with self.assertRaises(ValueError):
                    compute_next_run("0 9 * * *", tz_name=tz)

    def test_valid_timezones_and_dst(self):
        """Valid IANA timezones evaluate properly according to local time."""
        # UTC
        base_utc = datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc)
        next_run = compute_next_run("0 9 * * *", tz_name="UTC", from_time=base_utc)
        self.assertEqual(next_run, datetime(2026, 9, 5, 9, 0, 0, tzinfo=timezone.utc))

        # Kolkata (UTC+5:30)
        base_ist = datetime(2026, 9, 5, 2, 0, 0, tzinfo=timezone.utc) # 7:30 AM IST
        next_run_ist = compute_next_run("0 9 * * *", tz_name="Asia/Kolkata", from_time=base_ist)
        # 9:00 AM IST = 3:30 AM UTC
        self.assertEqual(next_run_ist, datetime(2026, 9, 5, 3, 30, 0, tzinfo=timezone.utc))

    def test_atomic_claim_prevents_duplicate_runs(self):
        """Atomic DB locking in poll_and_execute ensures only one scheduler claims a due task."""
        user_id = uuid.uuid4()
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                user = User(id=user_id, username=f"sched_{uuid.uuid4().hex[:6]}", hashed_password="pw")
                db.add(user)

            # Create a due task
            due_time = utc_now() - timedelta(minutes=5)
            task = ScheduledTask(
                id=uuid.uuid4(),
                user_id=user_id,
                title="Concurrent Test Task",
                prompt="Report status",
                schedule="0 9 * * *",
                timezone="UTC",
                enabled=True,
                next_run_at=due_time
            )
            db.add(task)
            db.commit()
            task_id = task.id

        service1 = TaskSchedulerService()
        service2 = TaskSchedulerService()

        from database.models import ScheduledTaskRun, BackgroundTask

        # Simulate both schedulers polling at the same moment
        import asyncio
        asyncio.run(service1.poll_and_execute())
        asyncio.run(service2.poll_and_execute())

        with get_db_context() as db:
            runs = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id == task_id).all()
            self.assertEqual(len(runs), 1, "Exactly one durable ScheduledTaskRun must be created for the occurrence.")
            self.assertIn(runs[0].status, ["QUEUED", "RUNNING", "COMPLETED"])

            # Check that exactly one BackgroundTask was enqueued
            bg_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.type == "scheduled_run"
            ).all()
            matching_bg = [b for b in bg_tasks if b.payload and b.payload.get("scheduled_task_id") == str(task_id)]
            self.assertEqual(len(matching_bg), 1, "Exactly one BackgroundTask must be enqueued.")


if __name__ == "__main__":
    unittest.main()
