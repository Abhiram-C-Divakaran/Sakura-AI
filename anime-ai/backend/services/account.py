"""
Sakura AI — Account Lifecycle Service (Deletion, Async User Data Export & Retention Cleanup)
Provides:
1. Self-service account deletion with verified workspace removal, durable storage outbox
   fallback for object/legacy/prefix-scan/workspace failures, honest cleanup_status reporting,
   DB record cleanup, and non-sensitive audit logging.
2. Async durable user data export packaged as a user-isolated ZIP archive in StorageBackend
   with enforced expiry and scheduled StorageDeletionOutbox cleanup.
3. Periodic retention pruning for expired exports, password-reset tokens, WebSocket tickets,
   and sandbox network authorizations.
"""

import io
import os
import json
import uuid
import shutil
import zipfile
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from database.db import get_db_context
from database.models import (
    User,
    Conversation,
    Message,
    MessageFeedback,
    ConversationShare,
    UserMemory,
    Document,
    DocumentChunk,
    GeneratedImage,
    Project,
    ProjectRepository,
    ProjectFile,
    ProjectConversation,
    ScheduledTask,
    ScheduledTaskRun,
    UserIntegration,
    RepositoryWorkspace,
    CodingTask,
    CodingJob,
    CodingTaskEvent,
    ToolExecution,
    SandboxNetworkAuthorization,
    BackgroundTask,
    ImageGenerationJob,
    ImageGenerationJobStatus,
    StorageDeletionOutbox,
    PasswordResetToken,
    WebSocketTicket,
    UserUsageQuota,
    UserDataExport,
    AccountAuditEvent,
    utc_now,
)
from services.storage import (
    get_storage_backend,
    assert_user_storage_key,
    resolve_legacy_local_path,
)

logger = logging.getLogger("sakura.account")


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_export_expired(exp: UserDataExport, now: Optional[datetime] = None) -> bool:
    """Returns True if export status is EXPIRED or expires_at <= now."""
    if not exp:
        return True
    if (exp.status or "").upper() == "EXPIRED":
        return True
    if exp.expires_at is None:
        return False
    ref = _as_utc(now or utc_now())
    return _as_utc(exp.expires_at) <= ref


def build_export_storage_key(user_id: uuid.UUID, export_id: uuid.UUID) -> str:
    """Canonical user-isolated storage key for a user data export bundle."""
    return f"users/{user_id}/exports/{export_id}/sakura_export.zip"


def _enqueue_outbox_entry(
    db: Session,
    *,
    storage_backend: str,
    storage_key: str,
    legacy_path: Optional[str] = None,
    last_error: Optional[str] = None,
    now: Optional[datetime] = None,
) -> StorageDeletionOutbox:
    ts = now or utc_now()
    existing = db.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.storage_key == storage_key,
        StorageDeletionOutbox.status == "PENDING",
    ).first()
    if existing:
        existing.last_error = last_error or existing.last_error
        existing.updated_at = ts
        return existing

    entry = StorageDeletionOutbox(
        id=uuid.uuid4(),
        user_id=None,
        document_id=None,
        storage_backend=storage_backend,
        storage_key=storage_key,
        legacy_path=legacy_path,
        status="PENDING",
        attempt_count=1,
        max_attempts=5,
        last_error=last_error,
        next_retry_at=ts + timedelta(seconds=60),
        created_at=ts,
        updated_at=ts,
    )
    db.add(entry)
    return entry


def delete_user_account(
    db: Session,
    user: User,
    *,
    storage_override=None,
) -> Dict[str, Any]:
    """
    Executes full authenticated self-service account deletion:
    1. Cancels all queued/running CodingJob, BackgroundTask, and ImageGenerationJob records.
    2. Verifies actual removal of user RepositoryWorkspace directories from disk (records durable
       outbox entries and failures honestly if removal fails).
    3. Deletes all user-owned objects & legacy files in StorageBackend; records durable outbox
       entries for any storage delete failure, legacy file failure, or prefix-listing failure.
    4. Removes all user-owned DB records cleanly.
    5. Persists a safe non-sensitive AccountAuditEvent and reports honest cleanup_status
       ('COMPLETE' vs 'PENDING_ASYNC_CLEANUP').
    """
    user_id = user.id
    now = utc_now()

    # 1. Cancel active jobs across all durable workers
    cancelled_coding = db.query(CodingJob).filter(
        CodingJob.user_id == user_id,
        CodingJob.status.in_(["QUEUED", "RUNNING"]),
    ).update(
        {
            CodingJob.cancel_requested: True,
            CodingJob.status: "CANCELLED",
            CodingJob.completed_at: now,
            CodingJob.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    db.query(CodingTask).filter(
        CodingTask.user_id == user_id,
        CodingTask.status.in_(["PENDING", "QUEUED", "RUNNING", "PLANNING", "EXECUTING"]),
    ).update(
        {
            CodingTask.status: "CANCELLED",
            CodingTask.completed_at: now,
            CodingTask.updated_at: now,
        },
        synchronize_session=False,
    )

    cancelled_bg = db.query(BackgroundTask).filter(
        BackgroundTask.user_id == user_id,
        BackgroundTask.status.in_(["Queued", "Starting", "Running"]),
    ).update(
        {
            BackgroundTask.cancel_requested: True,
            BackgroundTask.status: "Cancelled",
            BackgroundTask.completed_at: now,
            BackgroundTask.lease_expires_at: None,
        },
        synchronize_session=False,
    )

    cancelled_images = db.query(ImageGenerationJob).filter(
        ImageGenerationJob.user_id == user_id,
        ImageGenerationJob.status.in_([ImageGenerationJobStatus.QUEUED, ImageGenerationJobStatus.RUNNING]),
    ).update(
        {
            ImageGenerationJob.cancel_requested: True,
            ImageGenerationJob.status: ImageGenerationJobStatus.CANCELLED,
            ImageGenerationJob.completed_at: now,
            ImageGenerationJob.lease_expires_at: None,
            ImageGenerationJob.updated_at: now,
        },
        synchronize_session=False,
    )
    db.commit()

    # 2. Clean up workspace directories on disk with strict post-deletion verification
    workspaces = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.user_id == user_id).all()
    workspaces_cleaned = 0
    workspace_cleanup_failures = 0
    for ws in workspaces:
        ws_path = ws.workspace_path
        if ws_path and os.path.exists(ws_path):
            ws_err: Optional[str] = None
            try:
                shutil.rmtree(ws_path)
            except Exception as e:
                ws_err = str(e)
            if os.path.exists(ws_path):
                workspace_cleanup_failures += 1
                logger.warning(f"Workspace directory cleanup incomplete for {ws.id}: {ws_err or 'directory still exists'}")
                _enqueue_outbox_entry(
                    db,
                    storage_backend="workspace",
                    storage_key=f"workspace:{ws.id}",
                    legacy_path=ws_path,
                    last_error=ws_err or "Workspace directory remained on disk after rmtree",
                    now=now,
                )
            else:
                workspaces_cleaned += 1

    # 3. Collect and delete all user-owned storage keys & legacy files
    storage = storage_override or get_storage_backend()
    backend_name = getattr(storage, "backend_type", "local")
    keys_to_delete: Dict[str, Optional[str]] = {}  # storage_key -> legacy_path

    docs = db.query(Document).filter(Document.user_id == user_id).all()
    for d in docs:
        if d.storage_key:
            keys_to_delete[d.storage_key] = d.storage_path if d.storage_path != d.storage_key else None
        elif d.storage_path:
            keys_to_delete[f"__legacy__:{d.id}"] = d.storage_path

    images = db.query(GeneratedImage).filter(GeneratedImage.user_id == user_id).all()
    for img in images:
        if img.storage_key:
            keys_to_delete.setdefault(img.storage_key, img.storage_path if img.storage_path != img.storage_key else None)
        elif img.storage_path:
            keys_to_delete.setdefault(f"__legacy__:img:{img.id}", img.storage_path)

    exports = db.query(UserDataExport).filter(UserDataExport.user_id == user_id).all()
    for exp in exports:
        if exp.storage_key:
            keys_to_delete.setdefault(exp.storage_key, None)

    pending_outbox = db.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.user_id == user_id,
        StorageDeletionOutbox.status == "PENDING",
    ).all()
    for ob in pending_outbox:
        if ob.storage_key:
            keys_to_delete.setdefault(ob.storage_key, ob.legacy_path)

    # Scan canonical user prefix in StorageBackend; NEVER ignore enumeration failures
    storage_prefix_scan_failed = False
    user_prefix = f"users/{user_id}/"
    try:
        for listed_key in storage.list_keys(prefix=user_prefix):
            keys_to_delete.setdefault(listed_key, None)
    except Exception as e:
        storage_prefix_scan_failed = True
        logger.warning(f"Storage prefix listing failed during account deletion for {user_id}: {e}")
        _enqueue_outbox_entry(
            db,
            storage_backend=backend_name,
            storage_key=f"prefix_scan:{user_prefix}",
            legacy_path=None,
            last_error=f"Prefix enumeration failed during account deletion: {e}",
            now=now,
        )

    objects_deleted = 0
    outbox_deferred = 0
    failed_keys: set[str] = set()

    for key, legacy_path in keys_to_delete.items():
        key_ok = True
        key_err: Optional[str] = None
        is_legacy_only = key.startswith("__legacy__:")

        if not is_legacy_only:
            try:
                assert_user_storage_key(user_id, key)
                if not storage.delete(key):
                    key_ok = False
                    key_err = f"Backend returned False deleting {key}"
            except Exception as e:
                key_ok = False
                key_err = str(e)

        legacy_ok = True
        legacy_err: Optional[str] = None
        if legacy_path and os.path.exists(legacy_path):
            try:
                safe_legacy = resolve_legacy_local_path(legacy_path)
                if os.path.exists(safe_legacy):
                    os.remove(safe_legacy)
                if os.path.exists(safe_legacy):
                    legacy_ok = False
                    legacy_err = f"Legacy file persisted after remove: {safe_legacy}"
            except Exception as e:
                legacy_ok = False
                legacy_err = str(e)

        if key_ok and legacy_ok:
            objects_deleted += 1
        else:
            outbox_deferred += 1
            failed_keys.add(key)
            combined_err = "; ".join(x for x in (key_err, legacy_err) if x)
            outbox_key = (
                f"legacy:{user_id}:{uuid.uuid4().hex[:10]}"
                if is_legacy_only
                else key
            )
            _enqueue_outbox_entry(
                db,
                storage_backend=backend_name,
                storage_key=outbox_key,
                legacy_path=legacy_path if not legacy_ok else None,
                last_error=combined_err or "Storage cleanup deferred",
                now=now,
            )

    # Reconcile previously pending outbox rows belonging to this user
    for ob in pending_outbox:
        if ob.storage_key and ob.storage_key in keys_to_delete and ob.storage_key not in failed_keys:
            ob.status = "COMPLETED"
            ob.completed_at = now
            ob.next_retry_at = None
            ob.user_id = None
        else:
            ob.user_id = None

    # 4. Delete dependent DB rows cleanly
    conv_ids = [c.id for c in db.query(Conversation.id).filter(Conversation.user_id == user_id).all()]
    doc_ids = [d.id for d in docs]
    proj_ids = [p.id for p in db.query(Project.id).filter(Project.user_id == user_id).all()]
    sched_ids = [s.id for s in db.query(ScheduledTask.id).filter(ScheduledTask.user_id == user_id).all()]
    coding_task_ids = [t.id for t in db.query(CodingTask.id).filter(CodingTask.user_id == user_id).all()]
    coding_job_ids = [j.id for j in db.query(CodingJob.id).filter(CodingJob.user_id == user_id).all()]

    if conv_ids:
        msg_ids = [m.id for m in db.query(Message.id).filter(Message.conversation_id.in_(conv_ids)).all()]
        if msg_ids:
            db.query(MessageFeedback).filter(MessageFeedback.message_id.in_(msg_ids)).delete(synchronize_session=False)
        db.query(ConversationShare).filter(ConversationShare.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(ProjectConversation).filter(ProjectConversation.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)

    db.query(MessageFeedback).filter(MessageFeedback.user_id == user_id).delete(synchronize_session=False)
    db.query(ConversationShare).filter(ConversationShare.user_id == user_id).delete(synchronize_session=False)

    if doc_ids:
        db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db.query(ProjectFile).filter(ProjectFile.document_id.in_(doc_ids)).delete(synchronize_session=False)

    if proj_ids:
        db.query(ProjectRepository).filter(ProjectRepository.project_id.in_(proj_ids)).delete(synchronize_session=False)
        db.query(ProjectFile).filter(ProjectFile.project_id.in_(proj_ids)).delete(synchronize_session=False)
        db.query(ProjectConversation).filter(ProjectConversation.project_id.in_(proj_ids)).delete(synchronize_session=False)

    if sched_ids:
        db.query(ScheduledTaskRun).filter(ScheduledTaskRun.task_id.in_(sched_ids)).delete(synchronize_session=False)

    if coding_job_ids:
        db.query(CodingTaskEvent).filter(CodingTaskEvent.job_id.in_(coding_job_ids)).delete(synchronize_session=False)
    if coding_task_ids:
        db.query(ToolExecution).filter(ToolExecution.coding_task_id.in_(coding_task_ids)).delete(synchronize_session=False)

    db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == user_id).delete(synchronize_session=False)
    db.query(GeneratedImage).filter(GeneratedImage.user_id == user_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.user_id == user_id).delete(synchronize_session=False)
    db.query(UserMemory).filter(UserMemory.user_id == user_id).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.user_id == user_id).delete(synchronize_session=False)
    db.query(Project).filter(Project.user_id == user_id).delete(synchronize_session=False)
    db.query(ScheduledTask).filter(ScheduledTask.user_id == user_id).delete(synchronize_session=False)
    db.query(UserIntegration).filter(UserIntegration.user_id == user_id).delete(synchronize_session=False)
    db.query(SandboxNetworkAuthorization).filter(SandboxNetworkAuthorization.user_id == user_id).delete(synchronize_session=False)
    db.query(CodingJob).filter(CodingJob.user_id == user_id).delete(synchronize_session=False)
    db.query(CodingTask).filter(CodingTask.user_id == user_id).delete(synchronize_session=False)
    db.query(RepositoryWorkspace).filter(RepositoryWorkspace.user_id == user_id).delete(synchronize_session=False)
    db.query(BackgroundTask).filter(BackgroundTask.user_id == user_id).delete(synchronize_session=False)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).delete(synchronize_session=False)
    db.query(WebSocketTicket).filter(WebSocketTicket.user_id == user_id).delete(synchronize_session=False)
    db.query(UserUsageQuota).filter(UserUsageQuota.user_id == user_id).delete(synchronize_session=False)
    db.query(UserDataExport).filter(UserDataExport.user_id == user_id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)

    pending_async_total = outbox_deferred + workspace_cleanup_failures + (1 if storage_prefix_scan_failed else 0)
    cleanup_complete = (pending_async_total == 0)
    cleanup_status = "COMPLETE" if cleanup_complete else "PENDING_ASYNC_CLEANUP"

    # 5. Record safe non-sensitive audit log (counts/status only, zero PII/secrets)
    audit = AccountAuditEvent(
        id=uuid.uuid4(),
        subject_user_id=user_id,
        event_type="ACCOUNT_DELETED",
        details_json={
            "cleanup_status": cleanup_status,
            "cancelled_coding_jobs": int(cancelled_coding or 0),
            "cancelled_background_tasks": int(cancelled_bg or 0),
            "cancelled_image_jobs": int(cancelled_images or 0),
            "workspaces_cleaned": workspaces_cleaned,
            "workspace_cleanup_failures": workspace_cleanup_failures,
            "storage_objects_deleted": objects_deleted,
            "storage_outbox_deferred": outbox_deferred,
            "storage_prefix_scan_failed": storage_prefix_scan_failed,
            "pending_async_cleanup_count": pending_async_total,
        },
        created_at=now,
    )
    db.add(audit)
    db.commit()

    return {
        "status": "deleted",
        "cleanup_status": cleanup_status,
        "cleanup_complete": cleanup_complete,
        "user_id": str(user_id),
        "audit_event_id": str(audit.id),
        "cleanup": audit.details_json,
    }


def build_and_store_user_export(
    export_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    storage_override=None,
) -> Dict[str, Any]:
    """
    Executes a user-isolated data export job:
    - Collects all user-owned data (never including hashed passwords or secrets)
    - Packages canonical JSON into a ZIP archive stored under users/{user_id}/exports/{export_id}/
    - Updates UserDataExport status to COMPLETED (or FAILED on error).
    """
    now = utc_now()
    with get_db_context() as db:
        exp = db.query(UserDataExport).filter(
            UserDataExport.id == export_id,
            UserDataExport.user_id == user_id,
        ).first()
        if not exp:
            raise ValueError(f"Export {export_id} not found for user {user_id}")
        exp.status = "RUNNING"
        exp.started_at = now
        db.commit()

    try:
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError("User account no longer exists.")

            convs = db.query(Conversation).filter(Conversation.user_id == user_id).order_by(Conversation.created_at.asc()).all()
            conv_payload = []
            for c in convs:
                msgs = db.query(Message).filter(Message.conversation_id == c.id).order_by(Message.created_at.asc()).all()
                conv_payload.append({
                    "id": str(c.id),
                    "title": c.title,
                    "character_id": c.character_id,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "messages": [
                        {
                            "id": str(m.id),
                            "role": m.role,
                            "content": m.content,
                            "created_at": m.created_at.isoformat() if m.created_at else None,
                        }
                        for m in msgs
                    ],
                })

            memories = db.query(UserMemory).filter(UserMemory.user_id == user_id).all()
            docs = db.query(Document).filter(Document.user_id == user_id).all()
            images = db.query(GeneratedImage).filter(GeneratedImage.user_id == user_id).all()
            projects = db.query(Project).filter(Project.user_id == user_id).all()
            scheduled = db.query(ScheduledTask).filter(ScheduledTask.user_id == user_id).all()
            coding_tasks = db.query(CodingTask).filter(CodingTask.user_id == user_id).all()

            export_bundle = {
                "schema_version": "1.0",
                "exported_at": utc_now().isoformat(),
                "account": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                },
                "conversations": conv_payload,
                "memories": [
                    {
                        "id": str(m.id),
                        "memory_type": m.memory_type,
                        "content": m.content,
                        "confidence": m.confidence,
                    }
                    for m in memories
                ],
                "documents": [
                    {
                        "id": str(d.id),
                        "filename": d.filename,
                        "mime_type": d.mime_type,
                        "size_bytes": d.storage_size,
                        "is_knowledge_base": bool(d.is_knowledge_base),
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in docs
                ],
                "generated_images": [
                    {
                        "id": str(i.id),
                        "prompt": i.prompt,
                        "aspect_ratio": i.aspect_ratio,
                        "model": i.model,
                        "created_at": i.created_at.isoformat() if i.created_at else None,
                    }
                    for i in images
                ],
                "projects": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "description": p.description,
                        "instructions": p.instructions,
                    }
                    for p in projects
                ],
                "scheduled_tasks": [
                    {
                        "id": str(s.id),
                        "title": s.title,
                        "prompt": s.prompt,
                        "schedule": s.schedule,
                        "timezone": s.timezone,
                        "enabled": bool(s.enabled),
                    }
                    for s in scheduled
                ],
                "coding_tasks": [
                    {
                        "id": str(t.id),
                        "title": t.title,
                        "objective": t.objective,
                        "status": t.status,
                        "files_modified": t.files_modified or [],
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    }
                    for t in coding_tasks
                ],
            }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("export.json", json.dumps(export_bundle, indent=2, ensure_ascii=False))
        zip_bytes = buf.getvalue()

        storage = storage_override or get_storage_backend()
        storage_key = build_export_storage_key(user_id, export_id)
        put_res = storage.put(storage_key, zip_bytes, content_type="application/zip", user_id=user_id)

        done_at = utc_now()
        with get_db_context() as db:
            exp = db.query(UserDataExport).filter(
                UserDataExport.id == export_id,
                UserDataExport.user_id == user_id,
            ).first()
            if exp:
                exp.status = "COMPLETED"
                exp.storage_backend = put_res.get("storage_backend", storage.backend_type)
                exp.storage_key = storage_key
                exp.storage_size = len(zip_bytes)
                exp.error = None
                exp.completed_at = done_at
                exp.expires_at = done_at + timedelta(days=7)
                db.add(
                    AccountAuditEvent(
                        id=uuid.uuid4(),
                        subject_user_id=user_id,
                        event_type="DATA_EXPORT_COMPLETED",
                        details_json={"export_id": str(export_id), "size_bytes": len(zip_bytes)},
                        created_at=done_at,
                    )
                )
                db.commit()
                return exp.to_dict()
        return {"id": str(export_id), "status": "COMPLETED"}
    except Exception as e:
        fail_at = utc_now()
        with get_db_context() as db:
            exp = db.query(UserDataExport).filter(
                UserDataExport.id == export_id,
                UserDataExport.user_id == user_id,
            ).first()
            if exp:
                exp.status = "FAILED"
                exp.error = str(e)
                exp.completed_at = fail_at
                db.commit()
        raise


def cleanup_expired_exports_and_tokens(
    db: Optional[Session] = None,
    *,
    storage_override=None,
    token_grace_hours: int = 24,
    expired_export_retention_days: int = 30,
) -> Dict[str, int]:
    """
    Periodic durability & retention maintenance:
    1. Marks expired UserDataExport rows as EXPIRED and deletes their storage objects
       (enqueuing StorageDeletionOutbox rows on transient storage failures).
    2. Prunes expired UserDataExport rows past retention once their storage object is gone.
    3. Prunes expired PasswordResetToken, WebSocketTicket, and SandboxNetworkAuthorization rows.
    """
    stats = {
        "exports_expired": 0,
        "export_objects_deleted": 0,
        "export_outbox_enqueued": 0,
        "exports_pruned": 0,
        "reset_tokens_pruned": 0,
        "ws_tickets_pruned": 0,
        "network_auths_pruned": 0,
    }
    now = utc_now()
    token_cutoff = now - timedelta(hours=max(0, int(token_grace_hours)))
    export_prune_cutoff = now - timedelta(days=max(1, int(expired_export_retention_days)))

    def _run(session: Session):
        expired_candidates: List[UserDataExport] = session.query(UserDataExport).filter(
            UserDataExport.expires_at.isnot(None),
            UserDataExport.expires_at <= now,
            UserDataExport.status.in_(["COMPLETED", "EXPIRED"]),
        ).all()

        for exp in expired_candidates:
            was_completed = exp.status == "COMPLETED"
            exp.status = "EXPIRED"
            if was_completed:
                stats["exports_expired"] += 1

            if exp.storage_key:
                backend = storage_override or get_storage_backend(exp.storage_backend or "local")
                deleted_ok = False
                err_msg = None
                try:
                    deleted_ok = bool(backend.delete(exp.storage_key))
                    if not deleted_ok:
                        err_msg = f"Backend returned False deleting expired export '{exp.storage_key}'"
                except Exception as e:
                    err_msg = str(e)

                if deleted_ok:
                    exp.storage_key = None
                    stats["export_objects_deleted"] += 1
                else:
                    _enqueue_outbox_entry(
                        session,
                        storage_backend=getattr(backend, "backend_type", exp.storage_backend or "local"),
                        storage_key=exp.storage_key,
                        legacy_path=None,
                        last_error=err_msg,
                        now=now,
                    )
                    stats["export_outbox_enqueued"] += 1

            if not exp.storage_key and exp.expires_at and _as_utc(exp.expires_at) <= _as_utc(export_prune_cutoff):
                session.delete(exp)
                stats["exports_pruned"] += 1

        stats["reset_tokens_pruned"] = int(
            session.query(PasswordResetToken)
            .filter(PasswordResetToken.expires_at < token_cutoff)
            .delete(synchronize_session=False)
            or 0
        )
        stats["ws_tickets_pruned"] = int(
            session.query(WebSocketTicket)
            .filter(WebSocketTicket.expires_at < token_cutoff)
            .delete(synchronize_session=False)
            or 0
        )
        stats["network_auths_pruned"] = int(
            session.query(SandboxNetworkAuthorization)
            .filter(SandboxNetworkAuthorization.expires_at < token_cutoff)
            .delete(synchronize_session=False)
            or 0
        )
        session.commit()

    if db is not None:
        _run(db)
    else:
        with get_db_context() as session:
            _run(session)
    return stats
