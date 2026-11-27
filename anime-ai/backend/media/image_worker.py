"""
Sakura AI — Durable Image Generation Job Queue & Worker
Moves image generation onto a durable, restart-safe worker-backed lifecycle
with Redis queue consumption + DB polling fallback, lease heartbeat renewal,
execution fencing, active cancellation, bounded retries, and truthful
pipeline/provider/model recording.
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
IMAGE_HEARTBEAT_INTERVAL_SECONDS = 30
DEFAULT_MAX_IMAGE_ATTEMPTS = 3

SUPPORTED_IMAGE_PIPELINE_ALIASES: Dict[str, str] = {
    "": "auto",
    "auto": "auto",
    "anime": "anime",
    "photorealism": "photorealism",
    "photorealistic": "photorealism",
    "ui": "ui",
    "text_to_image": "text_to_image",
    "edit": "edit",
    "prompt_variation": "edit",
    "upscale": "upscale",
    "high_res_regeneration": "upscale",
}


def validate_requested_pipeline(requested_pipeline: Optional[str]) -> str:
    """
    Validates and normalizes requested_pipeline truthfully.
    Rejects unsupported pipelines (e.g. 'vector', 'svg', unknown values) with ValueError.
    """
    raw = (requested_pipeline or "auto").strip().lower()
    if raw in SUPPORTED_IMAGE_PIPELINE_ALIASES:
        return SUPPORTED_IMAGE_PIPELINE_ALIASES[raw]
    supported = ", ".join(sorted(set(SUPPORTED_IMAGE_PIPELINE_ALIASES.values())))
    raise ValueError(
        f"Unsupported image generation pipeline '{requested_pipeline}'. "
        f"Supported pipelines: {supported}."
    )


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def enqueue_image_job(job_id: uuid.UUID) -> bool:
    """Best-effort push to Redis queue (DB polling fallback guarantees durability)."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return False
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


def _pop_redis_image_job() -> Optional[str]:
    """Consumes one queued job ID from Redis so the Redis list never grows unboundedly."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    client = None
    try:
        import redis
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
        return client.lpop(IMAGE_JOB_QUEUE_NAME)
    except Exception:
        return None
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
    Validates requested_pipeline truthfully and enforces idempotency per (user_id, idempotency_key).
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Image prompt cannot be empty.")

    normalized_pipeline = validate_requested_pipeline(requested_pipeline)

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
        prompt=clean_prompt,
        requested_pipeline=normalized_pipeline,
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


async def wait_for_image_job(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    timeout_seconds: float = 45.0,
    poll_interval: float = 0.25,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Polls a durable ImageGenerationJob until it reaches a terminal state or timeout.
    Returns (job_dict, output_image_dict_or_none) without bypassing the worker queue.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.05, float(timeout_seconds))
    last_job_dict: Optional[Dict[str, Any]] = None

    while True:
        with get_db_context() as db:
            job = db.query(ImageGenerationJob).filter(
                ImageGenerationJob.id == job_id,
                ImageGenerationJob.user_id == user_id,
            ).first()
            if not job:
                return None, None
            last_job_dict = job.to_dict()
            if job.status in (
                ImageGenerationJobStatus.COMPLETED,
                ImageGenerationJobStatus.FAILED,
                ImageGenerationJobStatus.CANCELLED,
            ):
                img_dict = None
                if job.status == ImageGenerationJobStatus.COMPLETED and job.output_image_id:
                    img = db.query(GeneratedImage).filter(
                        GeneratedImage.id == job.output_image_id,
                        GeneratedImage.user_id == user_id,
                    ).first()
                    if img:
                        meta = img.metadata_json or {}
                        img_dict = {
                            "id": str(img.id),
                            "url": img.image_url,
                            "filename": f"image_{str(img.id)[:8]}.png",
                            "prompt": img.prompt,
                            "enhanced_prompt": img.enhanced_prompt,
                            "aspect_ratio": img.aspect_ratio,
                            "width": img.width,
                            "height": img.height,
                            "model": img.model,
                            "provider": job.actual_provider or meta.get("provider") or "pollinations",
                            "requested_pipeline": job.requested_pipeline,
                            "pipeline": meta.get("pipeline") or job.requested_pipeline,
                            "seed": img.seed,
                            "workflow": img.workflow,
                            "parent_image_id": str(img.parent_image_id) if img.parent_image_id else None,
                            "lineage_depth": img.lineage_depth or 0,
                            "job_id": str(job.id),
                        }
                return last_job_dict, img_dict

        if loop.time() >= deadline:
            return last_job_dict, None
        await asyncio.sleep(poll_interval)


class ImageJobWorker:
    """
    Durable worker claiming and executing ImageGenerationJob records with
    Redis queue consumption + DB fallback, live heartbeat renewal,
    execution fencing, active cancellation, and bounded retries.
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        lease_duration: float = IMAGE_LEASE_DURATION_SECONDS,
        heartbeat_interval: float = IMAGE_HEARTBEAT_INTERVAL_SECONDS,
    ):
        self.worker_id = worker_id or f"image_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.lease_duration = float(lease_duration)
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))

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
                (
                    j.id,
                    j.worker_id,
                    j.execution_attempt_id,
                    int(j.attempt_count or 0),
                    int(j.max_attempts or 3),
                    bool(j.cancel_requested),
                )
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

    def _atomic_claim_job_id(
        self,
        db: Session,
        cand_id: uuid.UUID,
        now: datetime,
        lease_exp: datetime,
        attempt_id: uuid.UUID,
    ) -> Optional[ImageGenerationJob]:
        cand = db.query(ImageGenerationJob).filter(
            ImageGenerationJob.id == cand_id,
            ImageGenerationJob.status == ImageGenerationJobStatus.QUEUED,
            ImageGenerationJob.cancel_requested == False,  # noqa: E712
        ).first()
        if not cand:
            return None
        next_attempt = int(cand.attempt_count or 0) + 1
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

    def claim_next_job(self) -> Optional[ImageGenerationJob]:
        """
        Atomically claims one QUEUED non-cancelled ImageGenerationJob.
        Consumes Redis queue entries first (preventing unbounded list growth),
        with authoritative DB polling fallback (using FOR UPDATE SKIP LOCKED on PostgreSQL).
        """
        now = utc_now()
        lease_exp = now + timedelta(seconds=self.lease_duration)
        attempt_id = uuid.uuid4()

        # 1. Drain up to 5 stale/duplicate Redis queue entries looking for a claimable job
        for _ in range(5):
            raw_id = _pop_redis_image_job()
            if not raw_id:
                break
            try:
                cand_uuid = uuid.UUID(str(raw_id).strip())
            except ValueError:
                continue
            with get_db_context() as db:
                claimed = self._atomic_claim_job_id(db, cand_uuid, now, lease_exp, attempt_id)
                if claimed:
                    return claimed

        # 2. Authoritative DB polling fallback
        with get_db_context() as db:
            is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
            if is_postgres:
                candidate = (
                    db.query(ImageGenerationJob)
                    .filter(
                        ImageGenerationJob.status == ImageGenerationJobStatus.QUEUED,
                        ImageGenerationJob.cancel_requested == False,  # noqa: E712
                    )
                    .order_by(ImageGenerationJob.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .first()
                )
                if not candidate:
                    return None
                candidate.status = ImageGenerationJobStatus.RUNNING
                candidate.worker_id = self.worker_id
                candidate.execution_attempt_id = attempt_id
                candidate.attempt_count = int(candidate.attempt_count or 0) + 1
                candidate.started_at = now
                candidate.heartbeat_at = now
                candidate.lease_expires_at = lease_exp
                candidate.updated_at = now
                db.commit()
                db.refresh(candidate)
                db.expunge(candidate)
                return candidate

            for _ in range(3):
                candidate = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.status == ImageGenerationJobStatus.QUEUED,
                    ImageGenerationJob.cancel_requested == False,  # noqa: E712
                ).order_by(ImageGenerationJob.created_at.asc()).first()

                if not candidate:
                    return None

                claimed = self._atomic_claim_job_id(db, candidate.id, now, lease_exp, attempt_id)
                if claimed:
                    return claimed
        return None

    async def execute_job(self, job: ImageGenerationJob, generator_fn=None) -> bool:
        """
        Executes a claimed ImageGenerationJob with:
        - entry lease & fencing verification
        - active background heartbeat renewal loop
        - active cancellation & lease-loss termination
        - bounded retries with non-retryable error classification
        - truthful pipeline/provider/model/output persistence
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
                db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.id == job_id,
                    ImageGenerationJob.worker_id == self.worker_id,
                    ImageGenerationJob.execution_attempt_id == attempt_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                ).update(
                    {
                        ImageGenerationJob.status: ImageGenerationJobStatus.CANCELLED,
                        ImageGenerationJob.completed_at: now,
                        ImageGenerationJob.lease_expires_at: None,
                        ImageGenerationJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
                db.commit()
                return False

            prompt = db_job.prompt
            user_id = db_job.user_id
            requested_pipeline = db_job.requested_pipeline or "auto"
            params = dict(db_job.parameters or {})
            attempt_count = int(db_job.attempt_count or 1)
            max_attempts = int(db_job.max_attempts or DEFAULT_MAX_IMAGE_ATTEMPTS)

        stop_hb = asyncio.Event()
        abort_state = {"reason": None}  # "cancelled" | "lease_lost"
        gen_task: Optional[asyncio.Task] = None

        async def _heartbeat_loop():
            while not stop_hb.is_set():
                try:
                    await asyncio.wait_for(stop_hb.wait(), timeout=self.heartbeat_interval)
                    break
                except asyncio.TimeoutError:
                    pass

                try:
                    with get_db_context() as db:
                        hb_now = utc_now()
                        hb_lease = hb_now + timedelta(seconds=self.lease_duration)
                        rows = db.query(ImageGenerationJob).filter(
                            ImageGenerationJob.id == job_id,
                            ImageGenerationJob.worker_id == self.worker_id,
                            ImageGenerationJob.execution_attempt_id == attempt_id,
                            ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                            ImageGenerationJob.cancel_requested == False,  # noqa: E712
                        ).update(
                            {
                                ImageGenerationJob.heartbeat_at: hb_now,
                                ImageGenerationJob.lease_expires_at: hb_lease,
                                ImageGenerationJob.updated_at: hb_now,
                            },
                            synchronize_session=False,
                        )
                        db.commit()
                        if rows == 0:
                            current = db.query(ImageGenerationJob).filter(
                                ImageGenerationJob.id == job_id
                            ).first()
                            if (
                                current
                                and current.worker_id == self.worker_id
                                and current.execution_attempt_id == attempt_id
                                and (current.cancel_requested or current.status == ImageGenerationJobStatus.CANCELLED)
                            ):
                                abort_state["reason"] = "cancelled"
                            else:
                                abort_state["reason"] = "lease_lost"
                            if gen_task and not gen_task.done():
                                gen_task.cancel()
                            break
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    logger.warning(f"Image job heartbeat failed for {job_id}: {ex}")

        async def _run_generation():
            normalized_pipeline = validate_requested_pipeline(requested_pipeline)
            run_params = dict(params)
            run_params["requested_pipeline"] = normalized_pipeline
            if generator_fn is not None:
                return await generator_fn(user_id=user_id, prompt=prompt, params=run_params)

            from media.image_engine import ImageGenerationEngine
            conv_raw = run_params.get("conversation_id")
            conv_uuid = uuid.UUID(str(conv_raw)) if conv_raw else None
            parent_raw = run_params.get("parent_image_id")
            parent_uuid = uuid.UUID(str(parent_raw)) if parent_raw else None
            workflow = (run_params.get("workflow") or "TEXT_TO_IMAGE").upper()

            with get_db_context() as db:
                engine = ImageGenerationEngine(db, user_id)
                if workflow == "PROMPT_VARIATION" and parent_uuid:
                    return await engine.edit_image(
                        parent_image_id=parent_uuid,
                        edit_instruction=run_params.get("edit_instruction") or prompt,
                        conversation_id=conv_uuid,
                        intensity=run_params.get("intensity") or "medium",
                    )
                if workflow == "HIGH_RES_REGENERATION" and parent_uuid:
                    return await engine.upscale_image(
                        parent_image_id=parent_uuid,
                        scale=int(run_params.get("scale") or 2),
                        conversation_id=conv_uuid,
                    )
                return await engine.generate_image(
                    prompt=prompt,
                    conversation_id=conv_uuid,
                    aspect_ratio=run_params.get("aspect_ratio") or "1:1",
                    intensity=run_params.get("intensity") or "medium",
                    parent_image_id=parent_uuid,
                    workflow=workflow,
                    requested_pipeline=normalized_pipeline,
                )

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            gen_task = asyncio.create_task(_run_generation())
            result = await gen_task

            if abort_state["reason"] == "lease_lost":
                return False

            out_img_id = uuid.UUID(str(result["id"])) if result and result.get("id") else None
            actual_provider = (result or {}).get("provider") or "pollinations"
            actual_model = (result or {}).get("model") or (result or {}).get("actual_model") or "flux"
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

        except asyncio.CancelledError:
            if abort_state["reason"] == "lease_lost":
                # Stale worker must perform zero writes after lease loss
                return False
            cancel_at = utc_now()
            with get_db_context() as db:
                rows = db.query(ImageGenerationJob).filter(
                    ImageGenerationJob.id == job_id,
                    ImageGenerationJob.worker_id == self.worker_id,
                    ImageGenerationJob.execution_attempt_id == attempt_id,
                    ImageGenerationJob.status == ImageGenerationJobStatus.RUNNING,
                ).update(
                    {
                        ImageGenerationJob.status: ImageGenerationJobStatus.CANCELLED,
                        ImageGenerationJob.completed_at: cancel_at,
                        ImageGenerationJob.lease_expires_at: None,
                        ImageGenerationJob.updated_at: cancel_at,
                    },
                    synchronize_session=False,
                )
                db.commit() if rows == 1 else db.rollback()
            return False

        except Exception as e:
            if abort_state["reason"] == "lease_lost":
                return False
            from media.image_engine import ImageNonTransientError
            err_msg = str(e)
            fail_at = utc_now()
            is_retryable = attempt_count < max_attempts
            if isinstance(e, (ValueError, ImageNonTransientError)):
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
        finally:
            stop_hb.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
