"""
Sakura AI — Durable Coding Job Worker & Event Persistence Engine
Authoritative execution pipeline for repository-level coding tasks with strict
worker lease fencing, atomic stale recovery, active cancellation, CodingTask
persistence, monotonic event sequences, and secret redaction.
"""

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, func

from database.models import (
    CodingJob,
    CodingTaskEvent,
    RepositoryWorkspace,
    User,
    CodingTask,
    TaskOutcome,
    utc_now,
)
from database.db import get_db_context
from coding.agent import CodingAgent
from coding.security import redact_sensitive_data, redact_sensitive_text
from llm.router import LLMRouter

logger = logging.getLogger("sakura.coding.worker")

CODING_JOB_QUEUE_NAME = "sakura:coding:jobs"
CODING_EVENT_CHANNEL_PREFIX = "sakura:coding:events:"
CODING_LEASE_DURATION_SECONDS = 60
CODING_HEARTBEAT_INTERVAL_SECONDS = 5
STALE_RECOVERY_INTERVAL_SECONDS = 30
MAX_CODING_JOB_RETRIES = 2

TERMINAL_CODING_STATUSES = {
    "COMPLETED_VERIFIED",
    "COMPLETED_UNVERIFIED",
    "FAILED",
    "CANCELLED",
    "MAX_ITERATIONS",
    "BLOCKED",
}


def is_terminal_coding_status(status: Optional[str]) -> bool:
    """Case-insensitive check for terminal coding job / task statuses."""
    if not status:
        return False
    return str(status).strip().upper() in TERMINAL_CODING_STATUSES


def normalize_coding_status(status: Optional[str]) -> str:
    """Normalizes TaskOutcome / CodingJob status strings to canonical uppercase form."""
    if not status:
        return "FAILED"
    return str(status).strip().upper()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    """Enqueues job to Redis queue for immediate worker dispatch (DB poll fallback if unavailable)."""
    client = get_sync_redis()
    if client:
        try:
            client.rpush(CODING_JOB_QUEUE_NAME, str(job_id))
            return True
        except Exception as e:
            logger.debug(f"Redis rpush error for coding job: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass
    return False


def publish_coding_event(task_id: str, event_data: dict) -> None:
    """Publishes a redacted coding event to Redis pub/sub channel for live SSE streaming."""
    client = get_sync_redis()
    if client:
        try:
            channel = f"{CODING_EVENT_CHANNEL_PREFIX}{task_id}"
            client.publish(channel, json.dumps(event_data))
        except Exception as e:
            logger.debug(f"Failed to publish coding event to Redis: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass


def create_and_enqueue_coding_job(
    db: Session,
    user: User,
    workspace: RepositoryWorkspace,
    title: str,
    objective: str,
    intensity: str = "high",
    idempotency_key: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[CodingTask, CodingJob, bool]:
    """
    Authoritative transactional creation of CodingTask + CodingJob + durable enqueue.
    Idempotent when idempotency_key is provided (scoped per user).
    Returns (task, job, created).
    """
    clean_idem = idempotency_key.strip()[:128] if idempotency_key and idempotency_key.strip() else None

    if clean_idem:
        existing_job = db.query(CodingJob).filter(
            CodingJob.user_id == user.id,
            CodingJob.idempotency_key == clean_idem,
        ).first()
        if existing_job:
            existing_task = None
            try:
                existing_task = db.query(CodingTask).filter(
                    CodingTask.id == uuid.UUID(str(existing_job.task_id)),
                    CodingTask.user_id == user.id,
                ).first()
            except ValueError:
                existing_task = None
            if existing_task:
                return existing_task, existing_job, False

    task_id = uuid.uuid4()
    now = utc_now()
    task = CodingTask(
        id=task_id,
        workspace_id=workspace.id,
        user_id=user.id,
        title=title[:255],
        objective=objective,
        status="QUEUED",
        files_modified=[],
        verification_summary={},
        created_at=now,
        updated_at=now,
    )
    job = CodingJob(
        id=uuid.uuid4(),
        task_id=str(task_id),
        workspace_id=workspace.id,
        user_id=user.id,
        instructions=objective,
        intensity=(intensity or "high").lower(),
        idempotency_key=clean_idem,
        status="QUEUED",
        metadata_json=metadata or {},
        created_at=now,
    )

    try:
        db.add(task)
        db.add(job)
        db.commit()
        db.refresh(task)
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        if clean_idem:
            existing_job = db.query(CodingJob).filter(
                CodingJob.user_id == user.id,
                CodingJob.idempotency_key == clean_idem,
            ).first()
            if existing_job:
                existing_task = db.query(CodingTask).filter(
                    CodingTask.id == uuid.UUID(str(existing_job.task_id)),
                    CodingTask.user_id == user.id,
                ).first()
                if existing_task:
                    return existing_task, existing_job, False
        raise

    # Best-effort immediate enqueue; workers fall back to DB polling if Redis is down
    enqueue_coding_job(str(task.id), job.id)
    return task, job, True


def append_coding_task_event(
    task_id: str,
    job_id: Optional[uuid.UUID],
    phase: str,
    event_type: str,
    *,
    seq: Optional[int] = None,
    message: Optional[str] = None,
    tool_name: Optional[str] = None,
    args_summary: Optional[str] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    exit_code: Optional[int] = None,
    diff_metadata: Optional[dict] = None,
    verification_metadata: Optional[dict] = None,
    expected_worker_id: Optional[str] = None,
    expected_attempt_id: Optional[uuid.UUID] = None,
) -> Optional[CodingTaskEvent]:
    """
    Persists a CodingTaskEvent with strictly monotonic sequence numbers across retries
    and redacts sensitive values from tool arguments, outputs, and messages.
    If expected_worker_id & expected_attempt_id are provided, verifies active lease ownership
    before persisting so stale workers cannot emit events.
    """
    safe_message = redact_sensitive_text(message) if message else None
    safe_args = redact_sensitive_text(args_summary) if args_summary else None
    safe_stdout = redact_sensitive_text(stdout)[:1000] if stdout else None
    safe_stderr = redact_sensitive_text(stderr)[:1000] if stderr else None
    safe_diff = redact_sensitive_data(diff_metadata) if diff_metadata else {}
    safe_verif = redact_sensitive_data(verification_metadata) if verification_metadata else {}

    for _attempt in range(5):
        with get_db_context() as db:
            if expected_worker_id is not None and expected_attempt_id is not None and job_id is not None:
                owned = db.query(CodingJob).filter(
                    CodingJob.id == job_id,
                    CodingJob.worker_id == expected_worker_id,
                    CodingJob.execution_attempt_id == expected_attempt_id,
                    CodingJob.status == "RUNNING",
                ).first()
                if not owned:
                    return None

            max_seq = db.query(func.max(CodingTaskEvent.sequence_number)).filter(
                CodingTaskEvent.task_id == str(task_id)
            ).scalar()
            current_max = int(max_seq or 0)

            if seq is not None and seq > current_max:
                assigned_seq = int(seq)
            else:
                assigned_seq = current_max + 1

            evt = CodingTaskEvent(
                id=uuid.uuid4(),
                task_id=str(task_id),
                job_id=job_id,
                sequence_number=assigned_seq,
                phase=phase,
                event_type=event_type,
                message=safe_message,
                tool_name=tool_name,
                arguments_summary=safe_args,
                stdout_preview=safe_stdout,
                stderr_preview=safe_stderr,
                exit_code=exit_code,
                diff_metadata=safe_diff,
                verification_metadata=safe_verif,
                created_at=utc_now(),
            )
            db.add(evt)
            try:
                db.commit()
                db.refresh(evt)
                evt_dict = evt.to_dict()
                publish_coding_event(str(task_id), evt_dict)
                return evt
            except IntegrityError:
                db.rollback()
                # Sequence collision from concurrent append — retry with fresh MAX + 1
                seq = None
                continue

    raise RuntimeError(f"Failed to allocate monotonic sequence number for task {task_id}")


class CodingJobWorker:
    """
    Dedicated durable worker process responsible for claiming, executing,
    heartbeating, fencing, and recovering repository-level coding jobs.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        heartbeat_interval: float = CODING_HEARTBEAT_INTERVAL_SECONDS,
        lease_duration: int = CODING_LEASE_DURATION_SECONDS,
    ):
        self.worker_id = worker_id or f"coding_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.heartbeat_interval = heartbeat_interval
        self.lease_duration = lease_duration
        self._running = False
        self.llm_router = LLMRouter()

    def recover_stale_jobs(self) -> int:
        """
        Atomically recovers jobs orphaned in RUNNING status whose lease has expired.
        Uses per-job conditional CAS matching (id, status='RUNNING', worker_id,
        execution_attempt_id, expired lease) so it can NEVER race with a healthy heartbeat.
        """
        now = utc_now()
        recovered_count = 0

        with get_db_context() as db:
            stale_candidates = db.query(CodingJob).filter(
                CodingJob.status == "RUNNING",
                or_(
                    CodingJob.lease_expires_at.is_(None),
                    CodingJob.lease_expires_at < now,
                ),
            ).all()

            candidate_snapshots = [
                (
                    j.id,
                    str(j.task_id),
                    j.worker_id,
                    j.execution_attempt_id,
                    int(j.retry_count or 0),
                    bool(j.cancel_requested),
                )
                for j in stale_candidates
            ]

        for job_id, task_id, old_worker_id, old_attempt_id, current_retries, was_cancel_req in candidate_snapshots:
            with get_db_context() as db:
                base_filter = [
                    CodingJob.id == job_id,
                    CodingJob.status == "RUNNING",
                    CodingJob.worker_id == old_worker_id,
                    CodingJob.execution_attempt_id == old_attempt_id,
                    or_(
                        CodingJob.lease_expires_at.is_(None),
                        CodingJob.lease_expires_at < now,
                    ),
                ]

                if was_cancel_req:
                    rows = db.query(CodingJob).filter(*base_filter).update(
                        {
                            CodingJob.status: "CANCELLED",
                            CodingJob.completed_at: now,
                            CodingJob.lease_expires_at: None,
                        },
                        synchronize_session=False,
                    )
                    if rows == 1:
                        self._sync_coding_task_in_tx(db, task_id, status="CANCELLED", completed_at=now)
                        db.commit()
                        append_coding_task_event(
                            task_id=task_id,
                            job_id=job_id,
                            phase="CANCELLED",
                            event_type="status",
                            message="Job cancelled during stale lease recovery.",
                        )
                    else:
                        db.rollback()
                    continue

                if current_retries >= MAX_CODING_JOB_RETRIES:
                    err_msg = f"Job exceeded max retries ({MAX_CODING_JOB_RETRIES}). Worker lease expired."
                    rows = db.query(CodingJob).filter(*base_filter).update(
                        {
                            CodingJob.status: "FAILED",
                            CodingJob.error: err_msg,
                            CodingJob.completed_at: now,
                            CodingJob.lease_expires_at: None,
                        },
                        synchronize_session=False,
                    )
                    if rows == 1:
                        self._sync_coding_task_in_tx(db, task_id, status="FAILED", completed_at=now)
                        db.commit()
                        append_coding_task_event(
                            task_id=task_id,
                            job_id=job_id,
                            phase="FAILED",
                            event_type="status",
                            message=err_msg,
                        )
                        logger.warning(f"Coding job {job_id} failed after lease expired and max retries exceeded.")
                    else:
                        db.rollback()
                else:
                    rows = db.query(CodingJob).filter(*base_filter).update(
                        {
                            CodingJob.status: "QUEUED",
                            CodingJob.retry_count: current_retries + 1,
                            CodingJob.worker_id: None,
                            CodingJob.execution_attempt_id: None,
                            CodingJob.started_at: None,
                            CodingJob.heartbeat_at: None,
                            CodingJob.lease_expires_at: None,
                        },
                        synchronize_session=False,
                    )
                    if rows == 1:
                        self._sync_coding_task_in_tx(db, task_id, status="QUEUED")
                        db.commit()
                        recovered_count += 1
                        enqueue_coding_job(task_id, job_id)
                        logger.info(f"Coding job {job_id} recovered atomically to QUEUED (retry {current_retries + 1}).")
                    else:
                        db.rollback()

        return recovered_count

    @staticmethod
    def _sync_coding_task_in_tx(
        db: Session,
        task_id: str,
        *,
        status: Optional[str] = None,
        files_modified: Optional[list] = None,
        verification_summary: Optional[dict] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        try:
            t_uuid = uuid.UUID(str(task_id))
        except ValueError:
            return
        task_rec = db.query(CodingTask).filter(CodingTask.id == t_uuid).first()
        if not task_rec:
            return
        if status is not None:
            task_rec.status = status
        if files_modified is not None:
            task_rec.files_modified = list(files_modified)
        if verification_summary is not None:
            task_rec.verification_summary = dict(verification_summary)
        if completed_at is not None:
            task_rec.completed_at = completed_at
        task_rec.updated_at = utc_now()

    def claim_next_job(self) -> Optional[CodingJob]:
        """
        Atomically claims a queued, non-cancelled coding job for this worker
        with a fresh execution_attempt_id and lease window.
        """
        candidate_job_id_str: Optional[str] = None

        client = get_sync_redis()
        if client:
            try:
                candidate_job_id_str = client.lpop(CODING_JOB_QUEUE_NAME)
            except Exception:
                pass
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        now = utc_now()
        lease_exp = now + timedelta(seconds=self.lease_duration)
        attempt_id = uuid.uuid4()

        with get_db_context() as db:
            if candidate_job_id_str:
                try:
                    raw_str = candidate_job_id_str.decode("utf-8") if isinstance(candidate_job_id_str, bytes) else str(candidate_job_id_str)
                    c_uuid = uuid.UUID(raw_str)
                    rows = db.query(CodingJob).filter(
                        CodingJob.id == c_uuid,
                        CodingJob.status == "QUEUED",
                        CodingJob.cancel_requested == False,  # noqa: E712
                    ).update(
                        {
                            CodingJob.status: "RUNNING",
                            CodingJob.worker_id: self.worker_id,
                            CodingJob.execution_attempt_id: attempt_id,
                            CodingJob.started_at: now,
                            CodingJob.heartbeat_at: now,
                            CodingJob.lease_expires_at: lease_exp,
                        },
                        synchronize_session=False,
                    )
                    if rows > 0:
                        claimed = db.query(CodingJob).filter(CodingJob.id == c_uuid).first()
                        if claimed:
                            self._sync_coding_task_in_tx(db, str(claimed.task_id), status="RUNNING")
                            db.commit()
                            db.refresh(claimed)
                            db.expunge(claimed)
                            return claimed
                    db.rollback()
                except Exception as e:
                    db.rollback()
                    logger.debug(f"Failed claiming candidate job from Redis: {e}")

            is_postgres = (db.bind.dialect.name == "postgresql") if db.bind else False
            if is_postgres:
                candidate = db.query(CodingJob).filter(
                    CodingJob.status == "QUEUED",
                    CodingJob.cancel_requested == False,  # noqa: E712
                ).order_by(CodingJob.created_at.asc()).with_for_update(skip_locked=True).first()
                if candidate:
                    candidate.status = "RUNNING"
                    candidate.worker_id = self.worker_id
                    candidate.execution_attempt_id = attempt_id
                    candidate.started_at = now
                    candidate.heartbeat_at = now
                    candidate.lease_expires_at = lease_exp
                    self._sync_coding_task_in_tx(db, str(candidate.task_id), status="RUNNING")
                    db.commit()
                    db.refresh(candidate)
                    db.expunge(candidate)
                    return candidate
                return None

            # SQLite / generic CAS fallback with contention retries
            for _ in range(3):
                candidate = db.query(CodingJob).filter(
                    CodingJob.status == "QUEUED",
                    CodingJob.cancel_requested == False,  # noqa: E712
                ).order_by(CodingJob.created_at.asc()).first()

                if not candidate:
                    return None

                cand_id = candidate.id
                rows = db.query(CodingJob).filter(
                    CodingJob.id == cand_id,
                    CodingJob.status == "QUEUED",
                    CodingJob.cancel_requested == False,  # noqa: E712
                ).update(
                    {
                        CodingJob.status: "RUNNING",
                        CodingJob.worker_id: self.worker_id,
                        CodingJob.execution_attempt_id: attempt_id,
                        CodingJob.started_at: now,
                        CodingJob.heartbeat_at: now,
                        CodingJob.lease_expires_at: lease_exp,
                    },
                    synchronize_session=False,
                )
                if rows > 0:
                    claimed = db.query(CodingJob).filter(CodingJob.id == cand_id).first()
                    if claimed:
                        self._sync_coding_task_in_tx(db, str(claimed.task_id), status="RUNNING")
                        db.commit()
                        db.refresh(claimed)
                        db.expunge(claimed)
                        return claimed
                db.rollback()

        return None

    def record_event(
        self,
        task_id: str,
        job_id: uuid.UUID,
        seq: Optional[int] = None,
        phase: str = "STEP",
        event_type: str = "status",
        message: Optional[str] = None,
        tool_name: Optional[str] = None,
        args_summary: Optional[str] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        exit_code: Optional[int] = None,
        diff_metadata: Optional[dict] = None,
        verification_metadata: Optional[dict] = None,
        expected_attempt_id: Optional[uuid.UUID] = None,
    ) -> Optional[CodingTaskEvent]:
        """Persists a monotonic, redacted CodingTaskEvent and publishes to Redis pub/sub."""
        return append_coding_task_event(
            task_id=task_id,
            job_id=job_id,
            phase=phase,
            event_type=event_type,
            seq=seq,
            message=message,
            tool_name=tool_name,
            args_summary=args_summary,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            diff_metadata=diff_metadata,
            verification_metadata=verification_metadata,
            expected_worker_id=self.worker_id if expected_attempt_id is not None else None,
            expected_attempt_id=expected_attempt_id,
        )

    def _verify_lease_at_entry(self, job: CodingJob) -> Tuple[bool, str]:
        """
        Verifies job ownership before execution begins:
        - status is RUNNING
        - worker_id matches self.worker_id
        - execution_attempt_id is non-null and matches
        - lease is valid (not expired)
        - cancellation has not been requested
        """
        if not job or not job.execution_attempt_id:
            return False, "Missing job or execution_attempt_id"

        now = utc_now()
        with get_db_context() as db:
            db_job = db.query(CodingJob).filter(CodingJob.id == job.id).first()
            if not db_job:
                return False, "Job record not found"
            if db_job.status != "RUNNING":
                return False, f"Job status is '{db_job.status}', expected 'RUNNING'"
            if db_job.worker_id != self.worker_id:
                return False, f"Worker ID mismatch: DB has '{db_job.worker_id}', expected '{self.worker_id}'"
            if db_job.execution_attempt_id != job.execution_attempt_id:
                return False, "Execution attempt ID mismatch"
            lease_exp = _as_utc(db_job.lease_expires_at)
            if lease_exp is None or lease_exp <= now:
                return False, "Worker lease is missing or expired"
            if db_job.cancel_requested:
                return False, "Job cancellation already requested"
        return True, "ok"

    def _fenced_finalize(
        self,
        job_id: uuid.UUID,
        task_id: str,
        attempt_id: uuid.UUID,
        new_status: str,
        *,
        error: Optional[str] = None,
        files_modified: Optional[list] = None,
        verification_summary: Optional[dict] = None,
        allow_when_cancel_requested: bool = False,
    ) -> bool:
        """
        Fences every terminal status update by (job_id, worker_id, execution_attempt_id, status='RUNNING').
        Updates both CodingJob and CodingTask atomically in one transaction ONLY if the fence succeeds.
        """
        now = utc_now()
        canonical_status = normalize_coding_status(new_status)
        with get_db_context() as db:
            filters = [
                CodingJob.id == job_id,
                CodingJob.worker_id == self.worker_id,
                CodingJob.execution_attempt_id == attempt_id,
                CodingJob.status == "RUNNING",
            ]
            if not allow_when_cancel_requested:
                filters.append(CodingJob.cancel_requested == False)  # noqa: E712

            update_fields: Dict[str, Any] = {
                CodingJob.status: canonical_status,
                CodingJob.completed_at: now,
                CodingJob.lease_expires_at: None,
            }
            if error is not None:
                update_fields[CodingJob.error] = redact_sensitive_text(error)
            if verification_summary is not None:
                update_fields[CodingJob.verification_state] = redact_sensitive_data(verification_summary)

            rows = db.query(CodingJob).filter(*filters).update(update_fields, synchronize_session=False)
            if rows != 1:
                db.rollback()
                logger.warning(
                    f"Fenced finalization rejected for job {job_id} (worker={self.worker_id}, attempt={attempt_id}, target={canonical_status})"
                )
                return False

            self._sync_coding_task_in_tx(
                db,
                task_id,
                status=canonical_status,
                files_modified=files_modified,
                verification_summary=verification_summary,
                completed_at=now,
            )
            db.commit()
            return True

    def _fenced_update_task_progress(
        self,
        job_id: uuid.UUID,
        task_id: str,
        attempt_id: uuid.UUID,
        *,
        task_status: Optional[str] = None,
        files_modified: Optional[list] = None,
    ) -> bool:
        """Updates CodingTask progress ONLY if this worker still holds the RUNNING lease."""
        with get_db_context() as db:
            owned = db.query(CodingJob).filter(
                CodingJob.id == job_id,
                CodingJob.worker_id == self.worker_id,
                CodingJob.execution_attempt_id == attempt_id,
                CodingJob.status == "RUNNING",
                CodingJob.cancel_requested == False,  # noqa: E712
            ).first()
            if not owned:
                return False
            self._sync_coding_task_in_tx(
                db,
                task_id,
                status=normalize_coding_status(task_status) if task_status else None,
                files_modified=files_modified,
            )
            db.commit()
            return True

    async def execute_job(self, job: CodingJob) -> bool:
        """
        Executes a legitimately claimed coding job with:
        - Strict lease & fencing verification at entry and every write
        - Live CodingTask persistence
        - Active cancellation & lease-loss termination (kills running agent/sandbox)
        - Monotonic redacted CodingTaskEvent stream
        """
        ok, reason = self._verify_lease_at_entry(job)
        if not ok:
            logger.warning(
                f"Worker {self.worker_id} refused execution of job {getattr(job, 'id', None)}: {reason}"
            )
            return False

        job_id = job.id
        task_id = str(job.task_id)
        workspace_id = job.workspace_id
        user_id = job.user_id
        attempt_id = job.execution_attempt_id
        job_intensity = getattr(job, "intensity", None) or "high"

        logger.info(f"Worker {self.worker_id} executing coding job {job_id} (task {task_id}, attempt {attempt_id})")

        # Load detached value snapshots cleanly — never pass a closed session to CodingAgent
        with get_db_context() as db:
            workspace = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == workspace_id).first()
            user = db.query(User).filter(User.id == user_id).first()
            if not workspace or not user:
                self._fenced_finalize(
                    job_id=job_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    new_status="FAILED",
                    error="Workspace or user record not found",
                )
                return False

            task_uuid = uuid.UUID(task_id)
            task = db.query(CodingTask).filter(CodingTask.id == task_uuid).first()
            if not task:
                task = CodingTask(
                    id=task_uuid,
                    workspace_id=workspace.id,
                    user_id=user.id,
                    title=f"Task {task_id[:8]}",
                    objective=job.instructions,
                    status="RUNNING",
                )
                db.add(task)
                db.commit()
                db.refresh(task)
            else:
                task.status = "RUNNING"
                task.updated_at = utc_now()
                db.commit()
                db.refresh(task)

            db.expunge(workspace)
            db.expunge(user)
            db.expunge(task)

        agent = CodingAgent(
            db=None,
            workspace=workspace,
            user=user,
            llm_router=self.llm_router,
            intensity=job_intensity,
        )

        lease_lost_event = asyncio.Event()
        cancel_event = asyncio.Event()
        runner_task_holder: Dict[str, Optional[asyncio.Task]] = {"task": None}

        def should_stop() -> bool:
            return lease_lost_event.is_set() or cancel_event.is_set()

        def abort_active_runner() -> None:
            rt = runner_task_holder.get("task")
            if rt is not None and not rt.done():
                rt.cancel()

        async def _heartbeat_loop():
            while not should_stop():
                try:
                    await asyncio.sleep(self.heartbeat_interval)
                    if should_stop():
                        break
                    with get_db_context() as db:
                        now = utc_now()
                        lease_exp = now + timedelta(seconds=self.lease_duration)
                        rows = db.query(CodingJob).filter(
                            CodingJob.id == job_id,
                            CodingJob.worker_id == self.worker_id,
                            CodingJob.execution_attempt_id == attempt_id,
                            CodingJob.status == "RUNNING",
                            CodingJob.cancel_requested == False,  # noqa: E712
                        ).update(
                            {
                                CodingJob.heartbeat_at: now,
                                CodingJob.lease_expires_at: lease_exp,
                            },
                            synchronize_session=False,
                        )
                        db.commit()

                        if rows == 0:
                            cur = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                            if cur and (cur.cancel_requested or cur.status == "CANCELLED"):
                                logger.info(f"Heartbeat observed cancellation for coding job {job_id}.")
                                cancel_event.set()
                            else:
                                logger.warning(f"Heartbeat failed: Worker {self.worker_id} lost lease for job {job_id}.")
                                lease_lost_event.set()
                            abort_active_runner()
                            break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Heartbeat update failed for coding job {job_id}: {e}")

        async def _run_agent_pipeline():
            self.record_event(
                task_id=task_id,
                job_id=job_id,
                seq=None,
                phase="START",
                event_type="status",
                message=f"Coding agent worker {self.worker_id} claimed job.",
                expected_attempt_id=attempt_id,
            )

            async for update in agent.run_task_stream(task, should_stop=should_stop, persist_directly=False):
                if should_stop():
                    return

                # Fast DB cancellation / lease check between steps
                with get_db_context() as db:
                    check_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
                    if not check_job or check_job.worker_id != self.worker_id or check_job.execution_attempt_id != attempt_id or check_job.status != "RUNNING":
                        lease_lost_event.set()
                        return
                    if check_job.cancel_requested:
                        cancel_event.set()
                        return

                phase = update.get("phase", "STEP")
                evt_type = "tool_start" if "args" in update else ("tool_finish" if "snippet" in update else "status")
                tool_name = update.get("tool")
                args_summary = json.dumps(redact_sensitive_data(update.get("args"))) if "args" in update else None
                snippet = update.get("snippet")
                final_out = update.get("final_output") or update.get("message") or update.get("error")
                verification = update.get("verification")
                diff_meta = {"files_modified": update.get("files_modified", [])} if "files_modified" in update else {}

                # Update live CodingTask phase & modified files under fence
                if not is_terminal_coding_status(phase):
                    self._fenced_update_task_progress(
                        job_id=job_id,
                        task_id=task_id,
                        attempt_id=attempt_id,
                        task_status=task.status,
                        files_modified=agent.modified_files,
                    )

                self.record_event(
                    task_id=task_id,
                    job_id=job_id,
                    seq=None,
                    phase=normalize_coding_status(phase) if is_terminal_coding_status(phase) else str(phase),
                    event_type=evt_type,
                    tool_name=tool_name,
                    args_summary=args_summary,
                    stdout=snippet if snippet else final_out,
                    diff_metadata=diff_meta,
                    verification_metadata=verification,
                    message=final_out or snippet,
                    expected_attempt_id=attempt_id,
                )

        hb_task = asyncio.create_task(_heartbeat_loop())
        runner_task = asyncio.create_task(_run_agent_pipeline())
        runner_task_holder["task"] = runner_task

        try:
            await runner_task

            if lease_lost_event.is_set():
                logger.warning(f"Coding job {job_id} aborted due to lease loss; skipping terminal write.")
                return False

            if cancel_event.is_set():
                if self._fenced_finalize(
                    job_id=job_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    new_status="CANCELLED",
                    files_modified=agent.modified_files,
                    allow_when_cancel_requested=True,
                ):
                    append_coding_task_event(
                        task_id=task_id,
                        job_id=job_id,
                        phase="CANCELLED",
                        event_type="status",
                        message="Task execution cancelled by user.",
                    )
                return False

            # Normal completion: fenced finalization of both CodingJob and CodingTask
            final_status = normalize_coding_status(task.status)
            if not is_terminal_coding_status(final_status):
                final_status = "COMPLETED_UNVERIFIED"

            finalized = self._fenced_finalize(
                job_id=job_id,
                task_id=task_id,
                attempt_id=attempt_id,
                new_status=final_status,
                files_modified=agent.modified_files,
                verification_summary=task.verification_summary or {},
                allow_when_cancel_requested=False,
            )
            return finalized

        except asyncio.CancelledError:
            if lease_lost_event.is_set():
                logger.warning(f"Coding job {job_id} terminated immediately on lease loss.")
                return False
            if cancel_event.is_set():
                if self._fenced_finalize(
                    job_id=job_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    new_status="CANCELLED",
                    files_modified=agent.modified_files,
                    allow_when_cancel_requested=True,
                ):
                    append_coding_task_event(
                        task_id=task_id,
                        job_id=job_id,
                        phase="CANCELLED",
                        event_type="status",
                        message="Task execution cancelled by user.",
                    )
                return False
            # External worker shutdown cancellation
            raise

        except Exception as e:
            logger.error(f"Error executing coding job {job_id}: {e}", exc_info=True)
            if not lease_lost_event.is_set():
                finalized = self._fenced_finalize(
                    job_id=job_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    new_status="FAILED",
                    error=str(e),
                    files_modified=agent.modified_files,
                    verification_summary=task.verification_summary or {},
                    allow_when_cancel_requested=False,
                )
                if finalized:
                    append_coding_task_event(
                        task_id=task_id,
                        job_id=job_id,
                        phase="FAILED",
                        event_type="status",
                        message=f"Task failed: {str(e)}",
                    )
            return False

        finally:
            lease_lost_event.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

    async def run(self, max_iterations: Optional[int] = None):
        """Worker main loop with periodic atomic stale-job recovery."""
        self._running = True
        self.recover_stale_jobs()
        last_recovery = asyncio.get_running_loop().time()
        logger.info(f"Sakura Coding Worker {self.worker_id} started and ready.")

        iteration = 0
        while self._running:
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            try:
                now_mono = asyncio.get_running_loop().time()
                if now_mono - last_recovery >= STALE_RECOVERY_INTERVAL_SECONDS:
                    self.recover_stale_jobs()
                    last_recovery = now_mono

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
