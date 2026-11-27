"""
Sakura AI — Account Lifecycle Service (Deletion & Async User Data Export)
Provides:
1. Self-service account deletion with active job cancellation, workspace disk cleanup,
   storage object purging (with durable outbox fallback on transient storage errors),
   DB record cleanup, and non-sensitive audit logging.
2. Async durable user data export packaged as a user-isolated ZIP archive in StorageBackend.
"""

import io
import os
import json
import uuid
import shutil
import zipfile
import logging
from datetime import timedelta
from typing import Dict, Any, Optional
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


def build_export_storage_key(user_id: uuid.UUID, export_id: uuid.UUID) -> str:
    """Canonical user-isolated storage key for a user data export bundle."""
    return f"users/{user_id}/exports/{export_id}/sakura_export.zip"


def delete_user_account(
    db: Session,
    user: User,
    *,
    storage_override=None,
) -> Dict[str, Any]:
    """
    Executes full authenticated self-service account deletion:
    1. Cancels all queued/running CodingJob, BackgroundTask, and ImageGenerationJob records.
    2. Removes user RepositoryWorkspace directories from disk safely.
    3. Deletes all user-owned objects in StorageBackend (and records durable outbox entries
       for any transient storage deletion failure so nothing leaks silently).
    4. Removes all user-owned DB records cleanly.
    5. Persists a safe non-sensitive AccountAuditEvent (no secrets, no PII).
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

    # 2. Clean up workspace directories on disk
    workspaces = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.user_id == user_id).all()
    workspaces_cleaned = 0
    for ws in workspaces:
        ws_path = ws.workspace_path
        if ws_path and os.path.isdir(ws_path):
            try:
                shutil.rmtree(ws_path, ignore_errors=True)
                workspaces_cleaned += 1
            except Exception as e:
                logger.warning(f"Workspace directory cleanup error for {ws.id}: {e}")

    # 3. Collect and delete all user-owned storage keys (Documents, GeneratedImages, Exports, Outbox, prefix scan)
    storage = storage_override or get_storage_backend()
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

    # Also scan canonical user prefix in StorageBackend
    try:
        for listed_key in storage.list_keys(prefix=f"users/{user_id}/"):
            keys_to_delete.setdefault(listed_key, None)
    except Exception as e:
        logger.warning(f"Storage prefix list warning during account deletion: {e}")

    objects_deleted = 0
    outbox_deferred = 0
    for key, legacy_path in keys_to_delete.items():
        deleted_ok = True
        err_detail = None
        if not key.startswith("__legacy__:"):
            try:
                assert_user_storage_key(user_id, key)
                if not storage.delete(key):
                    deleted_ok = False
                    err_detail = f"Backend returned False deleting {key}"
            except Exception as e:
                deleted_ok = False
                err_detail = str(e)

        if deleted_ok and legacy_path and os.path.exists(legacy_path):
            try:
                safe_legacy = resolve_legacy_local_path(legacy_path)
                if os.path.exists(safe_legacy):
                    os.remove(safe_legacy)
            except Exception as e:
                deleted_ok = False
                err_detail = str(e)

        if deleted_ok:
            objects_deleted += 1
        else:
            outbox_deferred += 1
            if not key.startswith("__legacy__:"):
                db.add(
                    StorageDeletionOutbox(
                        id=uuid.uuid4(),
                        user_id=None,
                        document_id=None,
                        storage_backend=getattr(storage, "backend_type", "local"),
                        storage_key=key,
                        legacy_path=legacy_path,
                        status="PENDING",
                        attempt_count=1,
                        max_attempts=5,
                        last_error=err_detail,
                        next_retry_at=now + timedelta(seconds=60),
                        created_at=now,
                        updated_at=now,
                    )
                )

    # Mark previously pending user outbox rows completed if deleted
    for ob in pending_outbox:
        if ob.storage_key and ob.storage_key in keys_to_delete and outbox_deferred == 0:
            ob.status = "COMPLETED"
            ob.completed_at = now
            ob.user_id = None
        else:
            ob.user_id = None

    # 4. Delete dependent DB rows cleanly (ensures full cleanup even when SQLite FK cascade is off)
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

    # 5. Record safe non-sensitive audit log (counts only, zero PII/secrets)
    audit = AccountAuditEvent(
        id=uuid.uuid4(),
        subject_user_id=user_id,
        event_type="ACCOUNT_DELETED",
        details_json={
            "cancelled_coding_jobs": int(cancelled_coding or 0),
            "cancelled_background_tasks": int(cancelled_bg or 0),
            "cancelled_image_jobs": int(cancelled_images or 0),
            "workspaces_cleaned": workspaces_cleaned,
            "storage_objects_deleted": objects_deleted,
            "storage_outbox_deferred": outbox_deferred,
        },
        created_at=now,
    )
    db.add(audit)
    db.commit()

    return {
        "status": "deleted",
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
