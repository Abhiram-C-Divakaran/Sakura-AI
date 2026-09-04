"""
Sakura AI — Persistent Scheduled Task Execution Engine

Executes scheduled recurring assistant prompts, logs execution history to ScheduledTaskRun,
and manages periodic evaluation of cron/interval schedules.
"""
import uuid
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from database.models import ScheduledTask, ScheduledTaskRun, User, utc_now
from database.db import get_db_context
from llm.router import LLMRouter


def compute_next_run(schedule: str, from_time: Optional[datetime] = None) -> datetime:
    """Estimates next run timestamp based on interval / cron schedule string."""
    base = from_time or utc_now()
    s = schedule.lower().strip()
    if "hour" in s:
        return base + timedelta(hours=1)
    elif "day" in s or "daily" in s or "9am" in s:
        return base + timedelta(days=1)
    elif "week" in s:
        return base + timedelta(weeks=1)
    elif "minute" in s:
        return base + timedelta(minutes=15)
    else:
        # Default fallback to 24 hours
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
            task.next_run_at = compute_next_run(task.schedule, now)

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
                if t.next_run_at and t.next_run_at <= now:
                    asyncio.create_task(execute_scheduled_task_run(t.id))
