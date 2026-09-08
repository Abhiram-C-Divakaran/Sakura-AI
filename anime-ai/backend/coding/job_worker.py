"""
Sakura AI — Durable Coding Job Worker & Event Persistence Engine
Executes repository-level coding tasks with worker lease fencing, persistent event replay,
graceful crash recovery, and cancellation semantics.
"""

import os
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database.models import CodingJob, CodingTaskEvent, RepositoryWorkspace, User, CodingTask, utc_now
from database.db import get_db_context
from coding.agent import CodingAgent
from coding.tools import CodingToolchain
from llm.router import LLMRouter

logger = logging.getLogger("sakura.coding.worker")

CODING_JOB_QUEUE_NAME = "sakura:coding:jobs"
CODING_EVENT_CHANNEL_PREFIX = "sakura:coding:events:"
CODING_LEASE_DURATION_SECONDS = 60
CODING_HEARTBEAT_INTERVAL_SECONDS = 5
MAX_CODING_JOB_RETRIES = 2


def get_sync_redis():
    """Optional sync Redis connection for queue and pub/sub."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        return client
    except Exception:
        return None


def enqueue_coding_job(task_id: str, job_id: uuid.UUID) -> bool:
    """Enqueues job to Redis queue for immediate worker dispatch."""
    client = get_sync_redis()
    if client:
        try:
            client.rpush(CODING_JOB_QUEUE_NAME, str(job_id))
            return True
        except Exception as e:
            logger.debug(f"Redis rpush error for coding job: {e}")
    return False


def publish_coding_event(task_id: str, event_data: dict) -> None:
    """Publishes a coding event to Redis pub/sub channel for live SSE streaming."""
    client = get_sync_redis()
    if client:
        try:
            channel = f"{CODING_EVENT_CHANNEL_PREFIX}{task_id}"
            client.publish(channel, json.dumps(event_data))
        except Exception as e:
            logger.debug(f"Failed to publish coding event to Redis: {e}")


class CodingJobWorker:
    """
    Durable worker process responsible for claiming, running, and persisting
    repository-level coding jobs with lease fencing.
    """

    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"coding_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self._running = False
        self.llm_router = LLMRouter()

    def recover_stale_jobs(self) -> int:
        """
        Recovers jobs orphaned in RUNNING status whose lease has expired.
        Never requeues an active worker's job whose heartbeat is healthy.
        """
        now = utc_now()
        recovered_count = 0
        with get_db_context() as db:
            stale_jobs = db.query(CodingJob).filter(
                CodingJob.status == "RUNNING",
                or_(
                    CodingJob.lease_expires_at.is_(None),
                    CodingJob.lease_expires_at < now
                )
            ).all()

            for job in stale_jobs:
                current_retries = job.retry_count or 0
                if current_retries >= MAX_CODING_JOB_RETRIES:
                    job.status = "FAILED"
                    job.error = f"Job exceeded max retries ({MAX_CODING_JOB_RETRIES}). Worker lease expired."
                    job.completed_at = now
                    logger.warning(f"Coding job {job.id} failed after lease expired and max retries exceeded.")
                else:
                    job.status = "QUEUED"
                    job.retry_count = current_retries + 1
                    job.worker_id = None
                    job.execution_attempt_id = None
                    job.started_at = None
                    job.heartbeat_at = None
                    job.lease_expires_at = None
                    recovered_count += 1
                    logger.info(f"Coding job {job.id} recovered to QUEUED (retry {job.retry_count}).")
            db.commit()

        return recovered_count

    def claim_next_job(self) -> Optional[CodingJob]:
        """
        Atomically claims a queued coding job for this worker with a unique execution_attempt_id.
        """
        candidate_job_id_str: Optional[str] = None

        client = get_sync_redis()
        if client:
            try:
                candidate_job_id_str = client.lpop(CODING_JOB_QUEUE_NAME)
            except Exception:
                pass

        now = utc_now()
        lease_exp = now + timedelta(seconds=CODING_LEASE_DURATION_SECONDS)
        attempt_id = uuid.uuid4()

        with get_db_context() as db:
            if candidate_job_id_str:
                try:
                    c_uuid = uuid.UUID(candidate_job_id_str.decode("utf-8") if isinstance(candidate_job_id_str, bytes) else str(candidate_job_id_str))
                    rows = db.query(CodingJob).filter(
                        CodingJob.id == c_uuid,
                        CodingJob.status == "QUEUED"
                    ).update({
                        CodingJob.status: "RUNNING",
                        CodingJob.worker_id: self.worker_id,
                        CodingJob.execution_attempt_id: attempt_id,
                        CodingJob.started_at: now,
                        CodingJob.heartbeat_at: now,
                        CodingJob.lease_expires_at: lease_exp
                    })
                    db.commit()
                    if rows > 0:
                        return db.query(CodingJob).filter(CodingJob.id == c_uuid).first()
                except Exception as e:
                    logger.debug(f"Failed claiming candidate job from Redis: {e}")

            # Database fallback poll (with FOR UPDATE SKIP LOCKED if supported)
            is_postgres = (db.bind.dialect.name == "postgresql") if db.bind else False
            if is_postgres:
                candidate = db.query(CodingJob).filter(
                    CodingJob.status == "QUEUED"
                ).order_by(CodingJob.created_at.asc()).with_for_update(skip_locked=True).first()
                if candidate:
                    candidate.status = "RUNNING"
                    candidate.worker_id = self.worker_id
                    candidate.execution_attempt_id = attempt_id
                    candidate.started_at = now
                    candidate.heartbeat_at = now
                    candidate.lease_expires_at = lease_exp
                    db.commit()
                    db.refresh(candidate)
                    return candidate
                return None

            candidate = db.query(CodingJob).filter(
                CodingJob.status == "QUEUED"
            ).order_by(CodingJob.created_at.asc()).first()

            if not candidate:
                return None

            rows = db.query(CodingJob).filter(
                CodingJob.id == candidate.id,
                CodingJob.status == "QUEUED"
            ).update({
                CodingJob.status: "RUNNING",
                CodingJob.worker_id: self.worker_id,
                CodingJob.execution_attempt_id: attempt_id,
                CodingJob.started_at: now,
                CodingJob.heartbeat_at: now,
                CodingJob.lease_expires_at: lease_exp
            })
            db.commit()

            if rows > 0:
                return db.query(CodingJob).filter(CodingJob.id == candidate.id).first()

        return None

    def record_event(
        self,
        task_id: str,
        job_id: uuid.UUID,
        seq: int,
        phase: str,
        event_type: str,
        message: Optional[str] = None,
        tool_name: Optional[str] = None,
        args_summary: Optional[str] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        exit_code: Optional[int] = None,
        diff_metadata: Optional[dict] = None,
        verification_metadata: Optional[dict] = None
    ) -> CodingTaskEvent:
        """Persists a CodingTaskEvent and publishes to Redis pub/sub for realtime streaming."""
        with get_db_context() as db:
            evt = CodingTaskEvent(
                id=uuid.uuid4(),
                task_id=str(task_id),
                job_id=job_id,
                sequence_number=seq,
                phase=phase,
                event_type=event_type,
                message=message,
                tool_name=tool_name,
                arguments_summary=args_summary,
                stdout_preview=stdout[:1000] if stdout else None,
                stderr_preview=stderr[:1000] if stderr else None,
                exit_code=exit_code,
                diff_metadata=diff_metadata or {},
                verification_metadata=verification_metadata or {},
                created_at=utc_now()
            )
            db.add(evt)
            db.commit()
            db.refresh(evt)
            evt_dict = evt.to_dict()

        publish_coding_event(str(task_id), evt_dict)
        return evt

    async def execute_job(self, job: CodingJob):
        """Executes a claimed coding job with heartbeat renewal, event persistence, and cancellation checks."""
        job_id = job.id
        task_id = str(job.task_id)
        workspace_id = job.workspace_id
        user_id = job.user_id
        attempt_id = job.execution_attempt_id
        seq = 1

        logger.info(f"Worker {self.worker_id} executing coding job {job_id} (task {task_id})")

        # Set up workspace and agent
        with get_db_context() as db:
            workspace = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == workspace_id).first()
            user = db.query(User).filter(User.id == user_id).first()
            if not workspace or not user:
                job_rec = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                if job_rec:
                    job_rec.status = "FAILED"
                    job_rec.error = "Workspace or user record not found"
                    job_rec.completed_at = utc_now()
                    db.commit()
                return

            task = db.query(CodingTask).filter(CodingTask.id == uuid.UUID(task_id)).first()
            if not task:
                task = CodingTask(
                    id=uuid.UUID(task_id),
                    workspace_id=workspace.id,
                    user_id=user.id,
                    title=f"Task {task_id[:8]}",
                    objective=job.instructions,
                    status="RUNNING"
                )
                db.add(task)
                db.commit()
                db.refresh(task)

        agent = CodingAgent(db, workspace, user, self.llm_router)

        lease_lost_event = asyncio.Event()

        # Background heartbeat loop
        async def _heartbeat_loop():
            while not lease_lost_event.is_set():
                try:
                    await asyncio.sleep(CODING_HEARTBEAT_INTERVAL_SECONDS)
                    if lease_lost_event.is_set():
                        break
                    with get_db_context() as db:
                        now = utc_now()
                        lease_exp = now + timedelta(seconds=CODING_LEASE_DURATION_SECONDS)
                        rows = db.query(CodingJob).filter(
                            CodingJob.id == job_id,
                            CodingJob.worker_id == self.worker_id,
                            CodingJob.execution_attempt_id == attempt_id,
                            CodingJob.status == "RUNNING"
                        ).update({
                            CodingJob.heartbeat_at: now,
                            CodingJob.lease_expires_at: lease_exp
                        })
                        db.commit()
                        if rows == 0:
                            logger.warning(f"Heartbeat failed: Worker {self.worker_id} lost ownership of job {job_id}.")
                            lease_lost_event.set()
                            break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Heartbeat update failed for coding job {job_id}: {e}")

        hb_task = asyncio.create_task(_heartbeat_loop())

        try:
            self.record_event(
                task_id=task_id,
                job_id=job_id,
                seq=seq,
                phase="START",
                event_type="status",
                message=f"Coding agent worker {self.worker_id} claimed job."
            )
            seq += 1

            async for update in agent.run_task_stream(task):
                # 1. Check if cancel was requested or lease lost
                if lease_lost_event.is_set():
                    logger.warning(f"Coding job {job_id} lease lost. Halting execution.")
                    return

                with get_db_context() as db:
                    check_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                    if check_job and check_job.cancel_requested:
                        logger.info(f"Coding job {job_id} received cancel request. Aborting.")
                        check_job.status = "CANCELLED"
                        check_job.completed_at = utc_now()
                        db.commit()
                        self.record_event(
                            task_id=task_id,
                            job_id=job_id,
                            seq=seq,
                            phase="CANCELLED",
                            event_type="status",
                            message="Task execution cancelled by user."
                        )
                        return

                phase = update.get("phase", "STEP")
                evt_type = "tool_start" if "args" in update else ("tool_finish" if "snippet" in update else "status")
                tool_name = update.get("tool")
                args_summary = json.dumps(update.get("args")) if "args" in update else None
                snippet = update.get("snippet")
                final_out = update.get("final_output") or update.get("message")
                verification = update.get("verification")
                diff_meta = {"files_modified": update.get("files_modified", [])} if "files_modified" in update else {}

                self.record_event(
                    task_id=task_id,
                    job_id=job_id,
                    seq=seq,
                    phase=phase,
                    event_type=evt_type,
                    tool_name=tool_name,
                    args_summary=args_summary,
                    stdout=snippet if snippet else final_out,
                    diff_metadata=diff_meta,
                    verification_metadata=verification,
                    message=final_out or snippet
                )
                seq += 1

            # Final status persist
            with get_db_context() as db:
                final_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                if final_job and final_job.status == "RUNNING":
                    final_job.status = task.status
                    final_job.completed_at = utc_now()
                    final_job.verification_state = task.verification_summary or {}
                    db.commit()

        except asyncio.CancelledError:
            logger.info(f"Coding job {job_id} was cancelled.")
        except Exception as e:
            logger.error(f"Error executing coding job {job_id}: {e}", exc_info=True)
            with get_db_context() as db:
                failed_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                if failed_job and failed_job.status == "RUNNING":
                    failed_job.status = "FAILED"
                    failed_job.error = str(e)
                    failed_job.completed_at = utc_now()
                    db.commit()
            self.record_event(
                task_id=task_id,
                job_id=job_id,
                seq=seq,
                phase="FAILED",
                event_type="status",
                message=f"Task failed: {str(e)}"
            )
        finally:
            lease_lost_event.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

    async def run(self, max_iterations: Optional[int] = None):
        """Worker main loop."""
        self._running = True
        self.recover_stale_jobs()
        logger.info(f"Sakura Coding Worker {self.worker_id} started and ready.")

        iteration = 0
        while self._running:
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            try:
                job = self.claim_next_job()
                if job:
                    await self.execute_job(job)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in coding worker loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)

        logger.info(f"Coding Worker {self.worker_id} stopped.")

    def stop(self):
        self._running = False


async def main():
    import signal
    worker = CodingJobWorker()

    def handle_signal():
        logger.info("Received termination signal, shutting down coding worker gracefully...")
        worker.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, AttributeError):
            pass

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
