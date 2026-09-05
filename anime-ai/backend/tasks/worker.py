"""
Sakura AI — Dedicated Durable Background Task Worker
Processes asynchronous background jobs with Redis queue dispatch and PostgreSQL authoritative state.
Ensures zero task loss across API restarts and eliminates in-process async task leaks.
"""

import os
import sys
import json
import uuid
import signal
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from database.models import BackgroundTask, utc_now
from database.db import get_db_context
from tasks.task_manager import (
    update_task_state,
    execute_code_analysis,
    execute_doc_summary,
    execute_dataset_analysis,
    execute_web_research,
    emit_task_update,
)
from llm.router import LLMRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sakura.worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TASK_QUEUE_NAME = "sakura:tasks:queue"
MAX_RETRIES = 3


def get_sync_redis():
    """Gets a synchronous Redis client for queue operations."""
    try:
        import redis
        client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=0.2)
        client.ping()
        return client
    except Exception:
        return None


def enqueue_task(task_id: uuid.UUID) -> bool:
    """Pushes a task ID onto the Redis task queue."""
    client = get_sync_redis()
    if client:
        try:
            client.rpush(TASK_QUEUE_NAME, str(task_id))
            return True
        except Exception as e:
            logger.warning(f"Failed to enqueue task {task_id} to Redis: {e}")
    return False


class DurableTaskWorker:
    """Long-running worker process consuming tasks from Redis with DB authoritative state."""

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self._running = False
        self.router = LLMRouter()

    def recover_stale_tasks(self) -> int:
        """
        Recovers tasks orphaned in 'Running' or 'Starting' status from crashed or restarted workers.
        Re-queues them if retries remain, or marks them Failed.
        """
        logger.info(f"Worker {self.worker_id} performing stale task recovery check...")
        recovered_count = 0
        with get_db_context() as db:
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["Running", "Starting"])
            ).all()

            for task in stale_tasks:
                current_retries = task.retry_count or 0
                if current_retries >= MAX_RETRIES:
                    task.status = "Failed"
                    task.error = f"Task exceeded maximum retries ({MAX_RETRIES}). Worker terminated unexpectedly."
                    task.completed_at = utc_now()
                    logger.warning(f"Task {task.id} failed after exceeding max retries.")
                else:
                    task.status = "Queued"
                    task.retry_count = current_retries + 1
                    task.worker_id = None
                    task.started_at = None
                    logger.info(f"Task {task.id} recovered from stale state and re-queued (retry {task.retry_count}).")
                    recovered_count += 1
            db.commit()

        return recovered_count

    def claim_next_task(self) -> Optional[BackgroundTask]:
        """
        Atomically claims a queued task for this worker.
        First checks Redis queue, then falls back to DB polling.
        """
        candidate_id_str: Optional[str] = None

        # 1. Try Redis queue
        client = get_sync_redis()
        if client:
            try:
                candidate_id_str = client.lpop(TASK_QUEUE_NAME)
            except Exception as e:
                logger.debug(f"Redis pop error: {e}")

        # 2. If Redis had a task ID, try to claim it atomically in DB
        if candidate_id_str:
            try:
                task_uuid = uuid.UUID(candidate_id_str)
                with get_db_context() as db:
                    rows = db.query(BackgroundTask).filter(
                        BackgroundTask.id == task_uuid,
                        BackgroundTask.status == "Queued"
                    ).update({
                        BackgroundTask.status: "Running",
                        BackgroundTask.worker_id: self.worker_id,
                        BackgroundTask.started_at: utc_now()
                    })
                    db.commit()
                    if rows > 0:
                        return db.query(BackgroundTask).filter(BackgroundTask.id == task_uuid).first()
            except Exception as e:
                logger.warning(f"Failed to claim candidate from Redis {candidate_id_str}: {e}")

        # 3. Fallback: Query database for earliest Queued task
        with get_db_context() as db:
            candidate = db.query(BackgroundTask).filter(
                BackgroundTask.status == "Queued"
            ).order_by(BackgroundTask.created_at.asc()).first()

            if not candidate:
                return None

            rows = db.query(BackgroundTask).filter(
                BackgroundTask.id == candidate.id,
                BackgroundTask.status == "Queued"
            ).update({
                BackgroundTask.status: "Running",
                BackgroundTask.worker_id: self.worker_id,
                BackgroundTask.started_at: utc_now()
            })
            db.commit()

            if rows > 0:
                return db.query(BackgroundTask).filter(BackgroundTask.id == candidate.id).first()

        return None

    async def execute_task(self, task: BackgroundTask):
        """Dispatches claimed task to its respective execution handler."""
        task_id = task.id
        user_id = task.user_id
        task_type = task.type
        payload = dict(task.payload or {})

        logger.info(f"Worker {self.worker_id} executing task {task_id} ({task_type}): '{task.title}'")

        # Check for immediate cancellation
        with get_db_context() as db:
            current = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not current or current.status == "Cancelled":
                logger.info(f"Task {task_id} was cancelled before execution started.")
                return

        await update_task_state(task_id, "Running", 10)

        try:
            if task_type == "code_analysis":
                await execute_code_analysis(task_id, user_id, payload, self.router)
            elif task_type == "doc_summary":
                await execute_doc_summary(task_id, user_id, payload, self.router)
            elif task_type == "dataset_analysis":
                await execute_dataset_analysis(task_id, user_id, payload, self.router)
            elif task_type == "web_research":
                await execute_web_research(task_id, user_id, payload, self.router)
            else:
                await update_task_state(task_id, "Failed", 100, error=f"Unknown task type: {task_type}")

            logger.info(f"Task {task_id} completed successfully.")
        except asyncio.CancelledError:
            logger.info(f"Task {task_id} received cancellation signal.")
            await update_task_state(task_id, "Cancelled", 100)
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            await update_task_state(task_id, "Failed", 100, error=str(e))

    async def run(self, max_iterations: Optional[int] = None):
        """Main worker loop."""
        self._running = True
        self.recover_stale_tasks()
        logger.info(f"Sakura Durable Task Worker {self.worker_id} online and listening for jobs...")

        iteration = 0
        while self._running:
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            try:
                task = self.claim_next_task()
                if task:
                    await self.execute_task(task)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)

        logger.info(f"Worker {self.worker_id} shut down cleanly.")

    def stop(self):
        self._running = False


async def main():
    worker = DurableTaskWorker()

    def handle_signal():
        logger.info("Received termination signal, shutting down worker gracefully...")
        worker.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, AttributeError):
            # Windows does not support loop.add_signal_handler
            pass

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
