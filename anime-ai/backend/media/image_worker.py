"""
Sakura AI — Durable Image Generation Job Queue & Worker
Moves image generation onto a durable, restart-safe worker-backed lifecycle
with lease fencing, bounded retries, cancellation, and truthful provider/model recording.
"""

import os
import uuid
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from database.db import get_db_context
from database.models import (
    ImageGenerationJob,
    ImageGenerationJobStatus,
    GeneratedImage,
    utc_now,
)

logger = logging.getLogger("sakura.media.worker")

IMAGE_JOB_QUEUE_NAME = "sakura:image:jobs"
IMAGE_LEASE_DURATION_SECONDS = 180
DEFAULT_MAX_IMAGE_ATTEMPTS = 3


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def enqueue_image_job(job_id: uuid.UUID) -> bool:
    """Best-effort push to Redis queue (DB polling fallback guarantees durability)."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = None
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.rpush(IMAGE_JOB_QUEUE_NAME, str(job_id))
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def create_image_generation_job(
    db: Session,
    user_id: uuid.UUID,
    prompt: str,
    requested_pipeline: str = "auto",
    parameters: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_IMAGE_ATTEMPTS,
) -> Tuple[ImageGenerationJob, bool]:
    """
    Persists a durable ImageGenerationJob in QUEUED state and enqueues it.
    Idempotent per (user_id, idempotency_key).
    """
    clean_idem = idempotency_key.strip()[:128] if idempotency_key and idempotency_key.strip() else None
    if clean_idem:
        existing = db.query(ImageGenerationJob).filter(
            ImageGenerationJob.user_id == user_id,
            ImageGenerationJob.idempotency_key == clean_idem,
        ).first()
        if existing:
            return existing, False

    now = utc_now()
    job = ImageGenerationJob(
        id=uuid.uuid4(),
        user_id=user_id,
        prompt=prompt.strip(),
        requested_pipeline=(requested_pipeline or "auto").strip(),
        status=ImageGenerationJobStatus.QUEUED,
        attempt_count=0,
        max_attempts=max(1, min(int(max_attempts), 5)),
        parameters=dict(parameters or {}),
        idempotency_key=clean_idem,
        cancel_requested=False,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        if clean_idem:
            existing = db.query(ImageGenerationJob).filter(
                ImageGenerationJob.user_id == user_id,
                ImageGenerationJob.idempotency_key == clean_idem,
            ).first()
            if existing:
                return existing, False
        raise

    enqueue_image_job(job.id)
    return job, True


class ImageJobWorker:
    """
    Durable worker claiming and executing ImageGenerationJob records with
    lease fencing, bounded retries, and cancellation semantics.
    """

    def __init__(self, worker_id: Optional[str] = None, lease_duration: int = IMAGE_LEASE_DURATION_SECONDS):
        self.worker_id = worker_id or f"image_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.lease_duration = lease_duration

    def recover_stale_jobs(self) -> int:
        """Atomically recovers RUNNING image jobs whose lease has expired."""
        now = utc_now()
        recovered = 0
        with get_db_context() as db:
            stale = db.query(ImageGenerationJob).filter(
                ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                or_(
                    ImageGenerationJob.lease_expires_at.is_(None),
                    ImageGenerationJob.lease_expires_at < now,
                ),
            ).all()
            snaps = [
                (j.id, j.worker_id, j.execution_attempt_id, int(j.attempt_count or 0), int(j.max_attempts or 3), bool(j.cancel_requested))
                for j in stale
            ]

        for job_id, old_worker, old_attempt, attempts, max_att, was_cancelled in snaps:
            with get_db_context() as db:
                base_filter = [
                    ImageGenerationJob.id == job_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                    ImageGenerationJob.worker_id == old_worker,
                    ImageGenerationJob.execution_attempt_id == old_attempt,
                    or_(
                        ImageGenerationJob.lease_expires_at.is_(None),
                        ImageGenerationJob.lease_expires_at < now,
                    ),
                ]
                if was_cancelled:
                    rows = db.query(ImageGenerationJob).filter(*base_filter).update(
                        {
                            ImageGenerationJob.status: ImageGenerationJobStatus.CANCELLED,
                            ImageGenerationJob.completed_at: now,
                            ImageGenerationJob.lease_expires_at: None,
                            ImageGenerationJob.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                    db.commit() if rows == 1 else db.rollback()
                elif attempts >= max_att:
                    rows = db.query(ImageGenerationJob).filter(*base_filter).update(
                        {
                            ImageGenerationJob.status: ImageGenerationJobStatus.FAILED,
                            ImageGenerationJob.error: f"Image generation failed after {attempts} attempts (worker lease expired).",
                            ImageGenerationJob.completed_at: now,
                            ImageGenerationJob.lease_expires_at: None,
                            ImageGenerationJob.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                    db.commit() if rows == 1 else db.rollback()
                else:
                    rows = db.query(ImageGenerationJob).filter(*base_filter).update(
                        {
                            ImageGenerationJob.status: ImageGenerationJobStatus.QUEUED,
                            ImageGenerationJob.worker_id: None,
                            ImageGenerationJob.execution_attempt_id: None,
                            ImageGenerationJob.lease_expires_at: None,
                            ImageGenerationJob.heartbeat_at: None,
                            ImageGenerationJob.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                    if rows == 1:
                        db.commit()
                        recovered += 1
                        enqueue_image_job(job_id)
                    else:
                        db.rollback()
        return recovered

    def claim_next_job(self) -> Optional[ImageGenerationJob]:
        """Atomically claims one QUEUED non-cancelled ImageGenerationJob."""
        now = utc_now()
        lease_exp = now + timedelta(seconds=self.lease_duration)
        attempt_id = uuid.uuid4()

        with get_db_context() as db:
            for _ in range(3):
                candidate = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.status == ImageGenerationJobStatus.QUEUED,
                    ImageGenerationJob.cancel_requested == False,  # noqa: E712
                ).order_by(ImageGenerationJob.created_at.asc()).first()

                if not candidate:
                    return None

                cand_id = candidate.id
                next_attempt = int(candidate.attempt_count or 0) + 1
                rows = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.id == cand_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.QUEUED,
                    ImageGenerationJob.cancel_requested == False,  # noqa: E712
                ).update(
                    {
                        ImageGenerationJob.status: ImageGenerationJobStatus.RUNNING,
                        ImageGenerationJob.worker_id: self.worker_id,
                        ImageGenerationJob.execution_attempt_id: attempt_id,
                        ImageGenerationJob.attempt_count: next_attempt,
                        ImageGenerationJob.started_at: now,
                        ImageGenerationJob.heartbeat_at: now,
                        ImageGenerationJob.lease_expires_at: lease_exp,
                        ImageGenerationJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
                if rows == 1:
                    claimed = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == cand_id).first()
                    db.commit()
                    if claimed:
                        db.refresh(claimed)
                        db.expunge(claimed)
                        return claimed
                db.rollback()
        return None

    async def execute_job(self, job: ImageGenerationJob, generator_fn=None) -> bool:
        """
        Executes a claimed ImageGenerationJob with lease verification, bounded retries,
        cancellation checks, and truthful provider/model/output persistence.
        """
        if not job or not job.execution_attempt_id:
            return False

        job_id = job.id
        attempt_id = job.execution_attempt_id
        now = utc_now()

        # Entry lease & cancellation verification
        with get_db_context() as db:
            db_job = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
            if (
                not db_job
                or db_job.status != ImageGenerationJobStatus.RUNNING
                or db_job.worker_id != self.worker_id
                or db_job.execution_attempt_id != attempt_id
                or (_as_utc(db_job.lease_expires_at) is None or _as_utc(db_job.lease_expires_at) <= now)
            ):
                return False

            if db_job.cancel_requested:
                db_job.status = ImageGenerationJobStatus.CANCELLED
                db_job.completed_at = now
                db_job.lease_expires_at = None
                db_job.updated_at = now
                db.commit()
                return False

            prompt = db_job.prompt
            user_id = db_job.user_id
            params = dict(db_job.parameters or {})
            attempt_count = int(db_job.attempt_count or 1)
            max_attempts = int(db_job.max_attempts or DEFAULT_MAX_IMAGE_ATTEMPTS)

        try:
            if generator_fn is not None:
                result = await generator_fn(user_id=user_id, prompt=prompt, params=params)
            else:
                from media.image_engine import ImageGenerationEngine
                conv_raw = params.get("conversation_id")
                conv_uuid = uuid.UUID(str(conv_raw)) if conv_raw else None
                with get_db_context() as db:
                    engine = ImageGenerationEngine(db, user_id)
                    result = await engine.generate_image(
                        prompt=prompt,
                        conversation_id=conv_uuid,
                        aspect_ratio=params.get("aspect_ratio") or "1:1",
                        intensity=params.get("intensity") or "medium",
                    )

            out_img_id = uuid.UUID(str(result["id"])) if result and result.get("id") else None
            actual_provider = result.get("provider") or "pollinations"
            actual_model = result.get("model") or result.get("actual_model") or "flux"
            done_at = utc_now()

            with get_db_context() as db:
                rows = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.id == job_id,
                    ImageGenerationJob.worker_id == self.worker_id,
                    ImageGenerationJob.execution_attempt_id == attempt_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                    ImageGenerationJob.cancel_requested == False,  # noqa: E712
                ).update(
                    {
                        ImageGenerationJob.status: ImageGenerationJobStatus.COMPLETED,
                        ImageGenerationJob.actual_provider: actual_provider,
                        ImageGenerationJob.actual_model: actual_model,
                        ImageGenerationJob.output_image_id: out_img_id,
                        ImageGenerationJob.error: None,
                        ImageGenerationJob.completed_at: done_at,
                        ImageGenerationJob.lease_expires_at: None,
                        ImageGenerationJob.updated_at: done_at,
                    },
                    synchronize_session=False,
                )
                if rows == 1:
                    db.commit()
                    return True
                # If cancelled while executing, finalize CANCELLED cleanly
                cancel_rows = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.id == job_id,
                    ImageGenerationJob.worker_id == self.worker_id,
                    ImageGenerationJob.execution_attempt_id == attempt_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                    ImageGenerationJob.cancel_requested == True,  # noqa: E712
                ).update(
                    {
                        ImageGenerationJob.status: ImageGenerationJobStatus.CANCELLED,
                        ImageGenerationJob.completed_at: done_at,
                        ImageGenerationJob.lease_expires_at: None,
                        ImageGenerationJob.updated_at: done_at,
                    },
                    synchronize_session=False,
                )
                db.commit() if cancel_rows == 1 else db.rollback()
                return False

        except Exception as e:
            err_msg = str(e)
            fail_at = utc_now()
            is_retryable = attempt_count < max_attempts
            # Non-retryable validation errors should fail immediately
            if isinstance(e, ValueError):
                is_retryable = False

            with get_db_context() as db:
                if is_retryable:
                    rows = db.query(ImageGenerationJob).filter(
                        ImageGenerationJob.id == job_id,
                        ImageGenerationJob.worker_id == self.worker_id,
                        ImageGenerationJob.execution_attempt_id == attempt_id,
                        ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                        ImageGenerationJob.cancel_requested == False,  # noqa: E712
                    ).update(
                        {
                            ImageGenerationJob.status: ImageGenerationJobStatus.QUEUED,
                            ImageGenerationJob.error: err_msg,
                            ImageGenerationJob.worker_id: None,
                            ImageGenerationJob.execution_attempt_id: None,
                            ImageGenerationJob.lease_expires_at: None,
                            ImageGenerationJob.heartbeat_at: None,
                            ImageGenerationJob.updated_at: fail_at,
                        },
                        synchronize_session=False,
                    )
                    if rows == 1:
                        db.commit()
                        enqueue_image_job(job_id)
                        return False
                    db.rollback()
                else:
                    rows = db.query(ImageGenerationJob).filter(
                        ImageGenerationJob.id == job_id,
                        ImageGenerationJob.worker_id == self.worker_id,
                        ImageGenerationJob.execution_attempt_id == attempt_id,
                        ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                    ).update(
                        {
                            ImageGenerationJob.status: ImageGenerationJobStatus.FAILED,
                            ImageGenerationJob.error: err_msg,
                            ImageGenerationJob.completed_at: fail_at,
                            ImageGenerationJob.lease_expires_at: None,
                            ImageGenerationJob.updated_at: fail_at,
                        },
                        synchronize_session=False,
                    )
                    db.commit() if rows == 1 else db.rollback()
            return False
