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
from sqlalchemy.exc import IntegrityError

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


class TaskSchedulerService:
    """Background service polling enabled tasks with atomic DB locking and dispatching durable worker jobs."""

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
        """
        Polls due tasks and transactionally dispatches durable jobs within ONE database transaction:
        1. Atomically claim due ScheduledTask and advance next_run_at
        2. Create ScheduledTaskRun occurrence record
        3. Create BackgroundTask queue record
        4. Commit transaction
        5. Best-effort push to Redis queue for immediate worker wake-up
        """
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
                    t.enabled = False
                    meta = dict(t.metadata_json or {})
                    meta["last_error"] = str(e)
                    meta["error_reason"] = "invalid_schedule_or_timezone"
                    t.metadata_json = meta
            if uninitialized:
                db.commit()

            # 2. Query due tasks
            due_tasks = db.query(ScheduledTask).filter(
                ScheduledTask.enabled == True,
                ScheduledTask.next_run_at <= now
            ).all()

            for t in due_tasks:
                occurrence_time = t.next_run_at
                try:
                    next_run = compute_next_run(t.schedule, t.timezone, now)
                except Exception as e:
                    logger.error(f"Cannot compute next run for task {t.id}: {e}")
                    t.enabled = False
                    meta = dict(t.metadata_json or {})
                    meta["last_error"] = str(e)
                    meta["error_reason"] = "invalid_schedule_or_timezone"
                    t.metadata_json = meta
                    db.commit()
                    continue

                # Idempotency pre-check: skip if run for this occurrence was already created
                existing_run = db.query(ScheduledTaskRun).filter(
                    ScheduledTaskRun.task_id == t.id,
                    ScheduledTaskRun.scheduled_for == occurrence_time
                ).first()
                if existing_run:
                    logger.info(f"Occurrence for task {t.id} at {occurrence_time} already claimed. Advancing next_run_at.")
                    db.query(ScheduledTask).filter(
                        ScheduledTask.id == t.id,
                        ScheduledTask.next_run_at == occurrence_time
                    ).update({
                        ScheduledTask.next_run_at: next_run,
                        ScheduledTask.last_run_at: now
                    }, synchronize_session=False)
                    db.commit()
                    continue

                bg_task_id = None
                try:
                    # Atomic claim in DB: only succeeds if next_run_at == occurrence_time
                    rows = db.query(ScheduledTask).filter(
                        ScheduledTask.id == t.id,
                        ScheduledTask.enabled == True,
                        ScheduledTask.next_run_at == occurrence_time
                    ).update({
                        ScheduledTask.next_run_at: next_run,
                        ScheduledTask.last_run_at: now
                    }, synchronize_session=False)

                    if rows == 0:
                        # Claim lost to concurrent scheduler instance
                        continue

                    # Transactional creation of occurrence run + durable background job
                    run_id = uuid.uuid4()
                    run = ScheduledTaskRun(
                        id=run_id,
                        task_id=t.id,
                        status="QUEUED",
                        scheduled_for=occurrence_time,
                        started_at=now
                    )
                    db.add(run)

                    from database.models import BackgroundTask
                    bg_task_id = uuid.uuid4()
                    bg_task = BackgroundTask(
                        id=bg_task_id,
                        user_id=t.user_id,
                        type="scheduled_run",
                        title=f"Scheduled: {t.title}",
                        payload={
                            "scheduled_task_id": str(t.id),
                            "run_id": str(run_id),
                            "scheduled_for": occurrence_time.isoformat() if occurrence_time else None
                        },
                        status="Queued",
                        progress=0,
                        created_at=now,
                        cancel_requested=False
                    )
                    db.add(bg_task)

                    # Commit all 3 state mutations atomically
                    db.commit()
                    logger.info(f"Transactionally dispatched scheduled task {t.id} (Run: {run_id}, Job: {bg_task_id})")

                except IntegrityError:
                    db.rollback()
                    logger.info(f"Occurrence for task {t.id} at {occurrence_time} already claimed (idempotency enforced by DB). Skipping.")
                    continue
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error during transactional dispatch for task {t.id}: {e}", exc_info=True)
                    continue

                # 5. Best-effort Redis wake-up ONLY AFTER commit
                if bg_task_id:
                    try:
                        from tasks.worker import enqueue_task
                        enqueue_task(bg_task_id)
                    except Exception as e:
                        logger.warning(f"Redis wake-up dispatch failed for job {bg_task_id} (worker DB polling will pick it up): {e}")


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

