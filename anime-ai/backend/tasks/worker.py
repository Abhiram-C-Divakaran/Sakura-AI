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
    TaskExecutionContext,
    _is_lease_expired,
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

    def __init__(
        self,
        worker_id: Optional[str] = None,
        lease_duration: float = LEASE_DURATION_SECONDS,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
        max_heartbeat_failures: int = 3,
    ):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.lease_duration = float(lease_duration)
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))
        self.max_heartbeat_failures = max(1, int(max_heartbeat_failures))
        self._running = False
        self._stop_event: Optional[asyncio.Event] = None
        self._sync_cancel_event = __import__("threading").Event()
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
            from sqlalchemy import or_
            stale_tasks = db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(["Running", "Starting"]),
                or_(
                    BackgroundTask.lease_expires_at.is_(None),
                    BackgroundTask.lease_expires_at < now
                )
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
        lease_exp = now + timedelta(seconds=self.lease_duration)
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

        # P0.6: Fencing check — ONLY claim_next_task() is allowed to establish ownership.
        # execute_task() MUST NOT overwrite ownership!
        with get_db_context() as db:
            current = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not current:
                raise TaskLeaseLostError(f"Task {task_id} does not exist in database.")
            if current.cancel_requested or current.status == "Cancelled":
                logger.info(f"Task {task_id} was cancelled before execution started.")
                return

            now = utc_now()
            if (
                current.status != "Running"
                or current.worker_id != self.worker_id
                or current.execution_attempt_id != attempt_id
                or _is_lease_expired(current.lease_expires_at, now)
            ):
                raise TaskLeaseLostError(
                    f"Task {task_id} ownership check failed: expected running task owned by worker '{self.worker_id}' "
                    f"with attempt '{attempt_id}' with unexpired lease. (Found worker='{current.worker_id}', "
                    f"attempt='{current.execution_attempt_id}', status='{current.status}')"
                )

        # P0.10: Wire heartbeat loss to execution cancellation
        lease_lost_event = asyncio.Event()
        ctx = TaskExecutionContext(
            task_id=task_id,
            worker_id=self.worker_id,
            execution_attempt_id=attempt_id,
            lease_lost_event=lease_lost_event
        )

        handler_task: Optional[asyncio.Task] = None

        async def _heartbeat_loop():
            loop = asyncio.get_running_loop()
            last_confirmed = loop.time()
            consecutive_failures = 0
            lease_loss_window = max(self.heartbeat_interval * 2.0, self.lease_duration * 0.75)

            while not lease_lost_event.is_set():
                try:
                    await asyncio.wait_for(lease_lost_event.wait(), timeout=self.heartbeat_interval)
                    break
                except asyncio.TimeoutError:
                    pass

                if lease_lost_event.is_set():
                    break

                try:
                    with get_db_context() as db:
                        hb_now = utc_now()
                        hb_lease = hb_now + timedelta(seconds=self.lease_duration)
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
                                f"(token {attempt_id}). Setting lease_lost_event and cancelling handler."
                            )
                            lease_lost_event.set()
                            if handler_task and not handler_task.done():
                                handler_task.cancel()
                            break
                        # Confirmed lease renewal resets failure tracking
                        consecutive_failures = 0
                        last_confirmed = loop.time()
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    consecutive_failures += 1
                    elapsed_unconfirmed = loop.time() - last_confirmed
                    logger.warning(
                        f"Heartbeat DB error ({consecutive_failures}/{self.max_heartbeat_failures}, "
                        f"unconfirmed={elapsed_unconfirmed:.2f}s) for task {task_id}: {ex}"
                    )
                    if (
                        consecutive_failures >= self.max_heartbeat_failures
                        or elapsed_unconfirmed >= lease_loss_window
                    ):
                        logger.error(
                            f"Aborting task {task_id}: unable to confirm lease ownership within safe window "
                            f"(failures={consecutive_failures}, elapsed={elapsed_unconfirmed:.2f}s). "
                            f"Cancelling handler and suppressing all terminal writes."
                        )
                        lease_lost_event.set()
                        if handler_task and not handler_task.done():
                            handler_task.cancel()
                        break

        hb_coro = asyncio.create_task(_heartbeat_loop())

        async def _run_handler():
            await update_task_state(task_id, "Running", 10, ctx=ctx)

            if task_type == "code_analysis":
                await execute_code_analysis(task_id, user_id, payload, self.router, ctx=ctx)
            elif task_type == "doc_summary":
                await execute_doc_summary(task_id, user_id, payload, self.router, ctx=ctx)
            elif task_type == "dataset_analysis":
                await execute_dataset_analysis(task_id, user_id, payload, self.router, ctx=ctx)
            elif task_type == "web_research":
                await execute_web_research(task_id, user_id, payload, self.router, ctx=ctx)
            elif task_type == "scheduled_run":
                await execute_scheduled_task_job(task_id, user_id, payload, self.router, ctx=ctx)
            elif task_type == "document_index":
                await execute_document_index(task_id, user_id, payload, self.worker_id, attempt_id, ctx=ctx)
            elif task_type == "user_data_export":
                from services.account import build_and_store_user_export
                export_id_raw = payload.get("export_id")
                if not export_id_raw:
                    raise ValueError("Missing export_id in user_data_export payload")
                res = await asyncio.to_thread(build_and_store_user_export, uuid.UUID(str(export_id_raw)), user_id)
                await update_task_state(task_id, "Completed", 100, result=json.dumps(res), ctx=ctx)
            else:
                await update_task_state(task_id, "Failed", 100, error=f"Unknown task type: {task_type}", ctx=ctx)

        try:
            handler_task = asyncio.create_task(_run_handler())
            await handler_task
            logger.info(f"Task {task_id} completed successfully.")
        except TaskLeaseLostError as e:
            logger.warning(f"Task {task_id} execution aborted: {e}. Worker {self.worker_id} no longer owns lease.")
            return
        except asyncio.CancelledError:
            if lease_lost_event.is_set():
                logger.warning(f"Task {task_id} cancelled due to lease loss. Worker {self.worker_id} performing zero writes.")
                return
            logger.info(f"Task {task_id} received external cancellation signal.")
            try:
                await update_task_state(task_id, "Cancelled", 100, ctx=ctx)
            except TaskLeaseLostError:
                pass
        except Exception as e:
            if lease_lost_event.is_set():
                logger.warning(f"Task {task_id} failed after lease lost: {e}. Worker {self.worker_id} performing zero writes.")
                return
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            try:
                await update_task_state(task_id, "Failed", 100, error=str(e), ctx=ctx)
            except TaskLeaseLostError:
                pass
        finally:
            lease_lost_event.set()
            hb_coro.cancel()
            try:
                await hb_coro
            except asyncio.CancelledError:
                pass

    async def run(
        self,
        max_iterations: Optional[int] = None,
        max_concurrency: Optional[int] = None,
        idle_sleep: float = 0.75,
        error_sleep: float = 2.0,
    ):
        """
        Main worker orchestrator running bounded, independent concurrent loops for:
        1. General BackgroundTasks (bounded concurrency via Semaphore with leak-proof permit accounting)
        2. Maintenance loop (stale recovery, StorageDeletionOutbox, expired export/token pruning)
        3. Optional ImageGenerationJob loop when dedicated image-worker service is not split out
           (controlled by SAKURA_WORKER_HANDLE_IMAGES, default true in single-worker dev, false in prod).
        Prevents long-running background tasks from starving image jobs or storage cleanup.
        """
        from media.image_worker import ImageJobWorker
        from services.documents import process_storage_deletion_outbox
        from services.account import cleanup_expired_exports_and_tokens

        self._running = True
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        self.recover_stale_tasks()
        handle_images = os.getenv("SAKURA_WORKER_HANDLE_IMAGES", "true").strip().lower() == "true"
        task_concurrency = max(1, min(int(max_concurrency or os.getenv("TASK_WORKER_CONCURRENCY", "2")), 8))
        image_worker = ImageJobWorker(worker_id=f"{self.worker_id}_img") if handle_images else None
        if image_worker:
            image_worker.recover_stale_jobs()

        logger.info(
            f"Sakura Durable Task Worker {self.worker_id} online "
            f"(task_concurrency={task_concurrency}, handle_images={handle_images})..."
        )

        async def _background_task_loop():
            sem = asyncio.Semaphore(task_concurrency)
            in_flight: set[asyncio.Task] = set()
            iteration = 0

            async def _exec_bounded(t_obj: BackgroundTask):
                try:
                    await self.execute_task(t_obj)
                finally:
                    sem.release()

            try:
                while self._running:
                    if max_iterations is not None and iteration >= max_iterations:
                        break
                    iteration += 1
                    acquired = False
                    transferred = False
                    try:
                        await sem.acquire()
                        acquired = True
                        task = self.claim_next_task()
                        if task:
                            t = asyncio.create_task(_exec_bounded(task))
                            transferred = True
                            in_flight.add(t)
                            t.add_done_callback(in_flight.discard)
                        else:
                            sem.release()
                            acquired = False
                            await asyncio.sleep(idle_sleep)
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"Unexpected error in background task loop: {e}", exc_info=True)
                        if acquired and not transferred:
                            sem.release()
                            acquired = False
                        await asyncio.sleep(error_sleep)
                    finally:
                        if acquired and not transferred:
                            sem.release()
                            acquired = False
            finally:
                if in_flight:
                    await asyncio.gather(*list(in_flight), return_exceptions=True)

        async def _outbox_deletion_loop():
            from services.documents import OUTBOX_WAKEUP_REDIS_KEY
            iteration = 0
            while self._running:
                if max_iterations is not None and iteration >= max_iterations:
                    break
                iteration += 1
                try:
                    await asyncio.to_thread(
                        process_storage_deletion_outbox,
                        limit=25,
                        worker_id=self.worker_id,
                        worker_cancel_event=self._sync_cancel_event,
                    )
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in outbox deletion loop: {e}", exc_info=True)
                if max_iterations is not None and iteration >= max_iterations:
                    break
                # Wake immediately on Redis signal or poll every 1.0s
                woke = False
                client = get_sync_redis()
                if client:
                    try:
                        res = await asyncio.to_thread(client.blpop, OUTBOX_WAKEUP_REDIS_KEY, 1)
                        if res:
                            woke = True
                    except Exception:
                        pass
                if not woke and self._running:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                        break
                    except asyncio.TimeoutError:
                        pass

        async def _maintenance_loop():
            iteration = 0
            while self._running:
                if max_iterations is not None and iteration >= max_iterations:
                    break
                iteration += 1
                try:
                    self.recover_stale_tasks()
                    if image_worker:
                        image_worker.recover_stale_jobs()
                    cleanup_expired_exports_and_tokens()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in maintenance loop: {e}", exc_info=True)
                if max_iterations is not None and iteration >= max_iterations:
                    break
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30.0)
                    break
                except asyncio.TimeoutError:
                    pass

        loops = [_background_task_loop(), _outbox_deletion_loop(), _maintenance_loop()]
        if image_worker:
            loops.append(image_worker.run(max_iterations=max_iterations))

        try:
            await asyncio.gather(*loops)
        finally:
            if image_worker:
                image_worker.stop()
            logger.info(f"Worker {self.worker_id} shut down cleanly.")

    def stop(self):
        self._running = False
        self._sync_cancel_event.set()
        if self._stop_event is not None:
            self._stop_event.set()


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
