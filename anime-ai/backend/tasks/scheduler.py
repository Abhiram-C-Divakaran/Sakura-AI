"""
Sakura AI — Persistent Scheduled Task Execution Engine

Executes scheduled recurring assistant prompts, logs execution history to ScheduledTaskRun,
and manages periodic evaluation of cron and natural-language schedules with timezone awareness.
"""
import uuid
import time
import asyncio
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from croniter import croniter
from sqlalchemy.orm import Session

from database.models import ScheduledTask, ScheduledTaskRun, User, utc_now
from database.db import get_db_context
from llm.router import LLMRouter

logger = logging.getLogger("sakura.scheduler")

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


def validate_timezone(tz_name: Optional[str]) -> str:
    """Validates that tz_name is a valid IANA timezone name. Raises ValueError if invalid."""
    if not tz_name or not tz_name.strip():
        return "UTC"
    clean_tz = tz_name.strip()
    try:
        ZoneInfo(clean_tz)
        return clean_tz
    except Exception:
        raise ValueError(
            f"Invalid timezone: '{tz_name}'. Must be a valid IANA timezone name "
            f"(e.g. 'UTC', 'America/New_York', 'Asia/Kolkata')."
        )


def validate_schedule_expression(schedule: str) -> str:
    """
    Validates and normalizes schedule expression to cron syntax.
    Raises ValueError if expression is invalid.
    """
    if not schedule or not schedule.strip():
        raise ValueError("Schedule expression cannot be empty.")
    s = schedule.strip().lower()
    if s in NATURAL_SCHEDULES:
        return NATURAL_SCHEDULES[s]
    for k, v in NATURAL_SCHEDULES.items():
        if k in s:
            return v

    cron_candidate = schedule.strip()
    if not croniter.is_valid(cron_candidate):
        raise ValueError(
            f"Invalid schedule expression: '{schedule}'. Must be a valid cron expression "
            f"(e.g. '0 9 * * *') or standard natural alias (e.g. 'hourly', 'daily at 9am')."
        )
    return cron_candidate


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
    Raises ValueError on invalid schedule or timezone (no silent fallback).
    """
    valid_tz = validate_timezone(tz_name)
    cron_expr = validate_schedule_expression(schedule)

    user_tz = ZoneInfo(valid_tz)
    base = from_time or utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    base_local = base.astimezone(user_tz)

    iter = croniter(cron_expr, base_local)
    next_local = iter.get_next(datetime)
    return next_local.astimezone(timezone.utc)


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
            try:
                task.next_run_at = compute_next_run(task.schedule, task.timezone, now)
            except Exception:
                task.next_run_at = now + timedelta(days=1)
            db.commit()
            return {
                "run_id": str(run.id),
                "status": "FAILED",
                "error": str(e),
                "duration_ms": duration_ms
            }


class TaskSchedulerService:
    """Background service polling enabled tasks with atomic DB locking and executing them asynchronously."""

    def __init__(self, poll_interval_seconds: int = 30):
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
                logger.error(f"Scheduler poll error: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def poll_and_execute(self):
        """Polls due tasks and claims them atomically using database UPDATE statements."""
        with get_db_context() as db:
            now = utc_now()

            # 1. Initialize next_run_at for any newly created tasks that lack it
            uninitialized = db.query(ScheduledTask).filter(
                ScheduledTask.enabled == True,
                ScheduledTask.next_run_at.is_(None)
            ).all()
            for t in uninitialized:
                try:
                    t.next_run_at = compute_next_run(t.schedule, t.timezone, now)
                except Exception as e:
                    logger.error(f"Cannot compute initial next_run_at for task {t.id}: {e}")
            if uninitialized:
                db.commit()

            # 2. Query due tasks
            due_tasks = db.query(ScheduledTask).filter(
                ScheduledTask.enabled == True,
                ScheduledTask.next_run_at <= now
            ).all()

            for t in due_tasks:
                try:
                    next_run = compute_next_run(t.schedule, t.timezone, now)
                except Exception as e:
                    logger.error(f"Cannot compute next run for task {t.id}: {e}")
                    continue

                # Atomic claim in DB: only succeeds if next_run_at <= now
                rows = db.query(ScheduledTask).filter(
                    ScheduledTask.id == t.id,
                    ScheduledTask.enabled == True,
                    ScheduledTask.next_run_at <= now
                ).update({
                    ScheduledTask.next_run_at: next_run,
                    ScheduledTask.last_run_at: now
                }, synchronize_session=False)
                db.commit()

                if rows > 0:
                    logger.info(f"Claimed scheduled task {t.id} ('{t.title}'). Dispatching execution...")
                    asyncio.create_task(execute_scheduled_task_run(t.id))


async def run_scheduler_forever():
    """Entry point for standalone scheduler process."""
    poll_sec = int(os.getenv("SAKURA_SCHEDULER_POLL_INTERVAL", "30"))
    service = TaskSchedulerService(poll_interval_seconds=poll_sec)
    logger.info(f"Starting standalone Sakura Task Scheduler (poll interval: {poll_sec}s)...")
    await service.start()
    try:
        while service._running:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await service.stop()
        logger.info("Sakura Task Scheduler stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(run_scheduler_forever())

