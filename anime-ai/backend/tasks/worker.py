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
from datetime import datetime, timedelta

from database.models import BackgroundTask, utc_now
from database.db import get_db_context
from tasks.task_manager import (
    update_task_state,
    execute_code_analysis,
    execute_doc_summary,
    execute_dataset_analysis,
    execute_web_research,
    execute_scheduled_task_job,
    execute_document_index,
    emit_task_update,
    TaskLeaseLostError,
    assert_task_lease_owned,
)
from llm.router import LLMRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sakura.worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TASK_QUEUE_NAME = "sakura:tasks:queue"
MAX_RETRIES = 3
LEASE_DURATION_SECONDS = 60
HEARTBEAT_INTERVAL_SECONDS = 15


_last_sync_redis_fail = 0.0

def get_sync_redis():
    """Gets a synchronous Redis client for queue operations."""
    global _last_sync_redis_fail
    import time
    now = time.time()
    if now - _last_sync_redis_fail < 5.0:
        return None
    try:
        import redis
        client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=0.2)
        client.ping()
        return client
    except Exception:
        _last_sync_redis_fail = now
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
    else:
        logger.warning(f"Redis client unavailable; task {task_id} stored authoritatively in PostgreSQL for DB polling.")
    return False


class DurableTaskWorker:
    """Long-running worker process consuming tasks from Redis with DB authoritative state."""

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self._running = False
        self.router = LLMRouter()

    def recover_stale_tasks(self) -> int:
        """
        Recovers tasks orphaned in 'Running' or 'Starting' status whose lease has expired.
        Never requeues an active worker's task whose heartbeat is healthy.
        Re-queues them if retries remain, or marks them Failed.
        """
        logger.info(f"Worker {self.worker_id} performing stale task recovery check...")
        recovered_count = 0
        now = utc_now()
        with get_db_context() as db:
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["Running", "Starting"]),
                BackgroundTask.lease_expires_at < now
            ).all()

            for task in stale_tasks:
                current_retries = task.retry_count or 0
                if current_retries >= MAX_RETRIES:
                    task.status = "Failed"
                    task.error = f"Task exceeded maximum retries ({MAX_RETRIES}). Lease expired without heartbeat."
                    task.completed_at = now
                    logger.warning(f"Task {task.id} failed after lease expiration and exceeding max retries.")
                else:
                    task.status = "Queued"
                    task.retry_count = current_retries + 1
                    task.worker_id = None
                    task.execution_attempt_id = None
                    task.started_at = None
                    task.heartbeat_at = None
                    task.lease_expires_at = None
                    logger.info(f"Task {task.id} lease expired and recovered to Queued (retry {task.retry_count}).")
                    recovered_count += 1
            db.commit()

        return recovered_count

    def claim_next_task(self) -> Optional[BackgroundTask]:
        """
        Atomically claims a queued task for this worker with a unique execution_attempt_id fencing token,
        lease expiration, and heartbeat timestamps.
        First checks Redis queue, then falls back to DB polling (using PostgreSQL FOR UPDATE SKIP LOCKED if available).
        """
        candidate_id_str: Optional[str] = None

        # 1. Try Redis queue
        client = get_sync_redis()
        if client:
            try:
                candidate_id_str = client.lpop(TASK_QUEUE_NAME)
            except Exception as e:
                logger.debug(f"Redis pop error: {e}")

        now = utc_now()
        lease_exp = now + timedelta(seconds=LEASE_DURATION_SECONDS)
        attempt_id = uuid.uuid4()

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
                        BackgroundTask.execution_attempt_id: attempt_id,
                        BackgroundTask.started_at: now,
                        BackgroundTask.heartbeat_at: now,
                        BackgroundTask.lease_expires_at: lease_exp
                    })
                    db.commit()
                    if rows > 0:
                        return db.query(BackgroundTask).filter(BackgroundTask.id == task_uuid).first()
            except Exception as e:
                logger.warning(f"Failed to claim candidate from Redis {candidate_id_str}: {e}")

        # 3. Fallback: Query database for earliest Queued task
        with get_db_context() as db:
            is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
            if is_postgres:
                # High-concurrency claim using PostgreSQL FOR UPDATE SKIP LOCKED
                candidate = db.query(BackgroundTask).filter(
                    BackgroundTask.status == "Queued"
                ).order_by(BackgroundTask.created_at.asc()).with_for_update(skip_locked=True).first()
                if candidate:
                    candidate.status = "Running"
                    candidate.worker_id = self.worker_id
                    candidate.execution_attempt_id = attempt_id
                    candidate.started_at = now
                    candidate.heartbeat_at = now
                    candidate.lease_expires_at = lease_exp
                    db.commit()
                    db.refresh(candidate)
                    return candidate
                return None

            # SQLite / fallback atomic update
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
                BackgroundTask.execution_attempt_id: attempt_id,
                BackgroundTask.started_at: now,
                BackgroundTask.heartbeat_at: now,
                BackgroundTask.lease_expires_at: lease_exp
            })
            db.commit()

            if rows > 0:
                return db.query(BackgroundTask).filter(BackgroundTask.id == candidate.id).first()

        return None

    async def execute_task(self, task: BackgroundTask):
        """Dispatches claimed task to its respective execution handler with live heartbeat renewal and fencing checks."""
        task_id = task.id
        user_id = task.user_id
        task_type = task.type
        payload = dict(task.payload or {})
        attempt_id = task.execution_attempt_id or uuid.uuid4()

        logger.info(f"Worker {self.worker_id} executing task {task_id} ({task_type}) [attempt={attempt_id}]: '{task.title}'")

        # Check for immediate cancellation and ensure task lease is recorded in DB
        with get_db_context() as db:
            current = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not current or current.cancel_requested or current.status == "Cancelled":
                logger.info(f"Task {task_id} was cancelled before execution started.")
                try:
                    await update_task_state(task_id, "Cancelled", 100, worker_id=self.worker_id, execution_attempt_id=attempt_id)
                except TaskLeaseLostError:
                    pass
                return

            if current.worker_id != self.worker_id or current.execution_attempt_id != attempt_id:
                now = utc_now()
                lease_exp = now + timedelta(seconds=LEASE_DURATION_SECONDS)
                current.status = "Running"
                current.worker_id = self.worker_id
                current.execution_attempt_id = attempt_id
                current.started_at = current.started_at or now
                current.heartbeat_at = now
                current.lease_expires_at = lease_exp
                db.commit()

        # Start periodic background heartbeat loop to keep lease active
        heartbeat_stop = asyncio.Event()

        async def _heartbeat_loop():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                    if heartbeat_stop.is_set():
                        break
                    with get_db_context() as db:
                        hb_now = utc_now()
                        hb_lease = hb_now + timedelta(seconds=LEASE_DURATION_SECONDS)
                        rows = db.query(BackgroundTask).filter(
                            BackgroundTask.id == task_id,
                            BackgroundTask.worker_id == self.worker_id,
                            BackgroundTask.execution_attempt_id == attempt_id,
                            BackgroundTask.status == "Running"
                        ).update({
                            BackgroundTask.heartbeat_at: hb_now,
                            BackgroundTask.lease_expires_at: hb_lease
                        })
                        db.commit()
                        if rows == 0:
                            logger.warning(
                                f"Heartbeat failed: Worker {self.worker_id} lost ownership of task {task_id} "
                                f"(token {attempt_id}). Stopping heartbeat loop."
                            )
                            heartbeat_stop.set()
                            break
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    logger.warning(f"Heartbeat update failed for task {task_id}: {ex}")

        hb_coro = asyncio.create_task(_heartbeat_loop())

        try:
            await update_task_state(task_id, "Running", 10, worker_id=self.worker_id, execution_attempt_id=attempt_id)

            if task_type == "code_analysis":
                await execute_code_analysis(task_id, user_id, payload, self.router)
            elif task_type == "doc_summary":
                await execute_doc_summary(task_id, user_id, payload, self.router)
            elif task_type == "dataset_analysis":
                await execute_dataset_analysis(task_id, user_id, payload, self.router)
            elif task_type == "web_research":
                await execute_web_research(task_id, user_id, payload, self.router)
            elif task_type == "scheduled_run":
                await execute_scheduled_task_job(task_id, user_id, payload, self.router)
            elif task_type == "document_index":
                await execute_document_index(task_id, user_id, payload, self.worker_id, attempt_id)
            else:
                await update_task_state(task_id, "Failed", 100, error=f"Unknown task type: {task_type}", worker_id=self.worker_id, execution_attempt_id=attempt_id)

            logger.info(f"Task {task_id} completed successfully.")
        except TaskLeaseLostError as e:
            logger.warning(f"Task {task_id} execution aborted: {e}. Worker {self.worker_id} no longer owns lease.")
            return
        except asyncio.CancelledError:
            logger.info(f"Task {task_id} received cancellation signal.")
            try:
                await update_task_state(task_id, "Cancelled", 100, worker_id=self.worker_id, execution_attempt_id=attempt_id)
            except TaskLeaseLostError:
                pass
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            try:
                await update_task_state(task_id, "Failed", 100, error=str(e), worker_id=self.worker_id, execution_attempt_id=attempt_id)
            except TaskLeaseLostError:
                pass
        finally:
            heartbeat_stop.set()
            hb_coro.cancel()
            try:
                await hb_coro
            except asyncio.CancelledError:
                pass

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
