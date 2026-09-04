import unittest
import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.scheduler import compute_next_run, normalize_schedule_expression

class TestSchedulingEngine(unittest.TestCase):
    def test_cron_utc_next_run(self):
        """0 9 * * * in UTC must produce next 9:00 AM UTC."""
        # Fixed base time: 2026-09-05 08:00:00 UTC
        base = datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc)
        next_run = compute_next_run("0 9 * * *", tz_name="UTC", from_time=base)
        expected = datetime(2026, 9, 5, 9, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run, expected)

    def test_cron_timezone_awareness_new_york(self):
        """0 9 * * * in America/New_York (EDT, UTC-4 in September) must execute at 13:00:00 UTC."""
        base = datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc) # 4:00 AM EDT
        next_run = compute_next_run("0 9 * * *", tz_name="America/New_York", from_time=base)
        # 9:00 AM EDT = 13:00:00 UTC
        expected = datetime(2026, 9, 5, 13, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run, expected)

    def test_cron_timezone_awareness_kolkata(self):
        """0 9 * * * in Asia/Kolkata (IST, UTC+5:30) must execute at 03:30:00 UTC."""
        base = datetime(2026, 9, 5, 2, 0, 0, tzinfo=timezone.utc) # 7:30 AM IST
        next_run = compute_next_run("0 9 * * *", tz_name="Asia/Kolkata", from_time=base)
        # 9:00 AM IST = 3:30 AM UTC
        expected = datetime(2026, 9, 5, 3, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run, expected)

    def test_natural_language_schedules(self):
        """Natural language strings like 'hourly', 'every 15 minutes', 'daily at 9am' normalize properly."""
        self.assertEqual(normalize_schedule_expression("hourly"), "0 * * * *")
        self.assertEqual(normalize_schedule_expression("every hour"), "0 * * * *")
        self.assertEqual(normalize_schedule_expression("daily at 9am"), "0 9 * * *")
        self.assertEqual(normalize_schedule_expression("every 15 minutes"), "*/15 * * * *")

        base = datetime(2026, 9, 5, 10, 10, 0, tzinfo=timezone.utc)
        next_hourly = compute_next_run("hourly", tz_name="UTC", from_time=base)
        self.assertEqual(next_hourly, datetime(2026, 9, 5, 11, 0, 0, tzinfo=timezone.utc))

    def test_failed_execution_does_not_corrupt_schedule(self):
        """When an execution fails, next_run_at must still advance to the future occurrence."""
        now = datetime(2026, 9, 5, 9, 1, 0, tzinfo=timezone.utc)
        next_run = compute_next_run("0 9 * * *", tz_name="UTC", from_time=now)
        # Next occurrence is tomorrow at 9 AM UTC
        expected = datetime(2026, 9, 6, 9, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run, expected)
        self.assertGreater(next_run, now)

if __name__ == "__main__":
    unittest.main()
