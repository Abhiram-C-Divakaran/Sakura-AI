"""
Sakura AI — Persistent Scheduled Task Execution Engine

Executes scheduled recurring assistant prompts, logs execution history to ScheduledTaskRun,
and manages periodic evaluation of cron and natural-language schedules with timezone awareness.
"""
import uuid
import time
import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from croniter import croniter
from sqlalchemy.orm import Session

from database.models import ScheduledTask, ScheduledTaskRun, User, utc_now
from database.db import get_db_context
from llm.router import LLMRouter


NATURAL_SCHEDULES = {
    "hourly": "0 * * * *",
    "every hour": "0 * * * *",
    "daily": "0 0 * * *",
    "every day": "0 0 * * *",
    "daily at 9am": "0 9 * * *",
    "every day at 9am": "0 9 * * *",
    "weekly": "0 0 * * 0",
    "every week": "0 0 * * 0",
    "every 15 minutes": "*/15 * * * *",
    "every 30 minutes": "*/30 * * * *",
    "every 5 minutes": "*/5 * * * *",
}


def normalize_schedule_expression(schedule: str) -> str:
    """Normalizes natural language schedule aliases to cron syntax."""
    s = (schedule or "").strip().lower()
    if s in NATURAL_SCHEDULES:
        return NATURAL_SCHEDULES[s]
    for k, v in NATURAL_SCHEDULES.items():
        if k in s:
            return v
    return schedule.strip()


def compute_next_run(schedule: str, tz_name: str = "UTC", from_time: Optional[datetime] = None) -> datetime:
    """
    Computes the authoritative next execution timestamp in UTC.
    Evaluates cron expressions and natural schedules according to user's IANA timezone.
    Handles DST transitions correctly.
    """
    # 1. Parse IANA timezone
    try:
        user_tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        user_tz = timezone.utc

    # 2. Establish base time in user timezone
    base = from_time or utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    base_local = base.astimezone(user_tz)

    # 3. Resolve cron expression
    cron_expr = normalize_schedule_expression(schedule)

    try:
        iter = croniter(cron_expr, base_local)
        next_local = iter.get_next(datetime)
        return next_local.astimezone(timezone.utc)
    except Exception:
        # Fallback to 24h interval if cron expression fails parsing
        return base + timedelta(days=1)


async def execute_scheduled_task_run(task_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """Executes a single scheduled task, generating output via LLMRouter and saving run history."""
    start_time = time.time()
    with get_db_context() as db:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        if not task:
            return None

        run = ScheduledTaskRun(
            id=uuid.uuid4(),
            task_id=task.id,
            status="RUNNING",
            started_at=utc_now()
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            router = LLMRouter()
            provider_name, provider = router.get_provider("general_inquiry")

            system_prompt = (
                "You are Sakura AI executing a scheduled automated task on behalf of the user. "
                "Provide a clear, detailed, and high-quality report."
            )
            response_text = await provider.generate(
                prompt=task.prompt,
                system_prompt=system_prompt,
                temperature=0.4,
                max_tokens=2048
            )

            duration_ms = int((time.time() - start_time) * 1000)
            now = utc_now()

            run.status = "COMPLETED"
            run.output = response_text
            run.completed_at = now
            run.duration_ms = duration_ms

            task.last_run_at = now
            task.next_run_at = compute_next_run(task.schedule, task.timezone, now)

            db.commit()
            return {
                "run_id": str(run.id),
                "status": "COMPLETED",
                "output": response_text,
                "duration_ms": duration_ms
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            now = utc_now()
            run.status = "FAILED"
            run.error = str(e)
            run.completed_at = now
            run.duration_ms = duration_ms
            task.last_run_at = now
            # Prevent corruption: calculate next run even on error so task continues running
            task.next_run_at = compute_next_run(task.schedule, task.timezone, now)
            db.commit()
            return {
                "run_id": str(run.id),
                "status": "FAILED",
                "error": str(e),
                "duration_ms": duration_ms
            }


class TaskSchedulerService:
    """Background service polling enabled tasks and executing them asynchronously."""

    def __init__(self, poll_interval_seconds: int = 60):
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self.poll_and_execute()
            except Exception as e:
                print(f"[TaskScheduler] Poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def poll_and_execute(self):
        with get_db_context() as db:
            now = utc_now()
            tasks = db.query(ScheduledTask).filter(
                ScheduledTask.enabled == True
            ).all()

            for t in tasks:
                # If next_run_at is missing, calculate immediately
                if not t.next_run_at:
                    t.next_run_at = compute_next_run(t.schedule, t.timezone, now)
                    db.commit()

                if t.next_run_at and t.next_run_at <= now:
                    # Advance next_run_at immediately to prevent double execution on subsequent polls
                    t.next_run_at = compute_next_run(t.schedule, t.timezone, now)
                    db.commit()
                    asyncio.create_task(execute_scheduled_task_run(t.id))
