"""
Sakura AI — Consolidated Document & Knowledge Base Service Layer
Provides canonical business logic for document lifecycle, RAG indexing,
storage persistence, and generation fencing across all API modules.
"""

import os
import shutil
import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database.db import get_db_context
from database.models import (
    Document,
    DocumentChunk,
    DocumentIndexingStatus,
    BackgroundTask,
    GeneratedImage,
    StorageDeletionOutbox,
    utc_now
)
from services.storage import (
    get_storage_backend,
    build_document_storage_key,
    assert_user_storage_key,
    resolve_legacy_local_path,
    StorageObjectNotFoundError,
    StorageSecurityError
)
from services.upload import save_uploaded_file, get_file_category

logger = logging.getLogger("sakura.services.documents")

OUTBOX_LEASE_DURATION_SECONDS = 120
OUTBOX_WAKEUP_REDIS_KEY = "sakura:outbox:wakeup"


def notify_outbox_worker(outbox_id: uuid.UUID) -> bool:
    """Best-effort Redis wakeup signal so DurableTaskWorker processes pending deletions immediately."""
    try:
        import redis as sync_redis
        client = sync_redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.3,
        )
        try:
            client.rpush(OUTBOX_WAKEUP_REDIS_KEY, str(outbox_id))
            return True
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception:
        return False


def serialize_document(doc: Document) -> Dict[str, Any]:
    """
    Serializes Document reading canonical DB fields as authoritative sources of truth.
    """
    meta = doc.metadata_json or {}
    category = meta.get("category") or get_file_category(doc.mime_type, doc.filename)

    is_kb = bool(doc.is_knowledge_base)
    idx_status = doc.indexing_status or DocumentIndexingStatus.NOT_INDEXED
    size_bytes = doc.storage_size if doc.storage_size is not None else meta.get("size", 0)
    del_status = getattr(doc, "deletion_status", None) or "ACTIVE"

    return {
        "id": str(doc.id),
        "name": doc.filename,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "category": category,
        "source": meta.get("source", "upload"),
        "status": idx_status,
        "indexing_status": idx_status,
        "deletion_status": del_status,
        "deletion_error": meta.get("deletion_error"),
        "size_bytes": size_bytes,
        "size": size_bytes,
        "is_knowledge_base": is_kb,
        "index_generation": getattr(doc, "index_generation", 0),
        "chunks": meta.get("chunks", 0),
        "created_at": doc.created_at.isoformat() if doc.created_at else datetime.now(timezone.utc).isoformat(),
        "modified_at": meta.get("modified_at", doc.created_at.isoformat() if doc.created_at else datetime.now(timezone.utc).isoformat()),
        "error": meta.get("error", None),
        "storage_backend": getattr(doc, "storage_backend", "local") or "local",
        "storage_key": getattr(doc, "storage_key", None),
        "metadata": meta
    }


async def upload_document(
    file: UploadFile,
    user_id: uuid.UUID,
    db: Session,
    auto_index: bool = True,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> Document:
    """
    Saves uploaded file to configured StorageBackend, creates authoritative Document row,
    and enqueues durable document_index BackgroundTask when auto_index is True.
    """
    doc = await save_uploaded_file(
        file=file,
        user_id=user_id,
        db=db,
        auto_index=auto_index,
        extra_metadata=extra_metadata
    )

    category = (doc.metadata_json or {}).get("category", "")
    if auto_index and category in ["documents", "code", "data"]:
        enqueue_index(doc.id, user_id, db, force_reindex=False)
    elif doc.indexing_status == DocumentIndexingStatus.QUEUED:
        doc.indexing_status = DocumentIndexingStatus.NOT_INDEXED
        doc.metadata_json = {
            **(doc.metadata_json or {}),
            "status": "READY",
            "indexing_status": "Not indexed",
        }
        db.commit()
        db.refresh(doc)

    return doc


def enqueue_index(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
    force_reindex: bool = False
) -> BackgroundTask:
    """
    Atomically increments Document.index_generation and enqueues durable document_index BackgroundTask
    within the same database transaction.
    """
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Increment generation to invalidate any stale index workers
    current_gen = getattr(doc, "index_generation", 0) or 0
    new_gen = current_gen + 1
    doc.index_generation = new_gen
    doc.is_knowledge_base = False
    doc.indexing_status = DocumentIndexingStatus.QUEUED
    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "status": "QUEUED",
        "indexing_status": "Queued",
        "error": None
    }

    from tasks.task_manager import TaskManager
    task = TaskManager.create_task_in_session(
        db=db,
        user_id=user_id,
        task_type="document_index",
        title=f"Index {doc.filename}",
        payload={
            "document_id": str(doc.id),
            "requested_by_user_id": str(user_id),
            "index_generation": new_gen,
            "force_reindex": force_reindex
        }
    )
    db.commit()
    db.refresh(doc)
    db.refresh(task)

    try:
        from tasks.worker import enqueue_task
        enqueue_task(task.id)
    except Exception as e:
        logger.warning(f"Failed to enqueue task {task.id} to Redis: {e}")

    return task


def create_document(
    filename: str,
    content: str,
    user_id: uuid.UUID,
    db: Session,
    category: Optional[str] = "documents"
) -> Document:
    """
    Creates a text/markdown/code document directly from content, stores in StorageBackend,
    indexes chunk immediately, and sets is_knowledge_base = True.
    """
    clean_name = filename.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    file_id = uuid.uuid4()
    ext = os.path.splitext(clean_name)[1] or ".txt"
    mime_type = "text/markdown" if ext == ".md" else ("text/x-python" if ext == ".py" else "text/plain")
    cat = category or get_file_category(mime_type, clean_name)

    storage = get_storage_backend()
    storage_key = build_document_storage_key(user_id, file_id, clean_name)
    content_bytes = content.encode("utf-8")
    put_res = storage.put(storage_key, content_bytes, content_type=mime_type, user_id=user_id)
    file_size = len(content_bytes)

    doc = Document(
        id=file_id,
        user_id=user_id,
        filename=clean_name,
        mime_type=mime_type,
        storage_path=put_res.get("storage_path") or storage_key,
        storage_backend=put_res.get("storage_backend", storage.backend_type),
        storage_key=storage_key,
        storage_size=file_size,
        is_knowledge_base=True,
        index_generation=1,
        indexing_status=DocumentIndexingStatus.READY,
        metadata_json={
            "status": "READY",
            "indexing_status": "Ready",
            "size": file_size,
            "category": cat,
            "source": "ai_document",
            "is_knowledge_base": True,
            "modified_at": datetime.now(timezone.utc).isoformat(),
            "chunks": 1,
            "error": None
        }
    )
    db.add(doc)
    db.commit()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        metadata_json={"source": clean_name}
    )
    db.add(chunk)
    db.commit()
    db.refresh(doc)
    return doc


def remove_from_kb(doc_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Document:
    """
    Removes document from Knowledge Base:
    1. Increments index_generation (invalidating any running index worker)
    2. Sets is_knowledge_base = False, indexing_status = NOT_INDEXED
    3. Deletes existing chunks
    4. Requests cancellation of any queued or running index tasks for this document
    """
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Increment generation
    current_gen = getattr(doc, "index_generation", 0) or 0
    doc.index_generation = current_gen + 1
    doc.is_knowledge_base = False
    doc.indexing_status = DocumentIndexingStatus.NOT_INDEXED

    # Delete chunks
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

    meta = dict(doc.metadata_json or {})
    meta.update({
        "is_knowledge_base": False,
        "chunks": 0,
        "indexing_status": "Not indexed",
        "status": "READY"
    })
    doc.metadata_json = meta

    # Cancel active/queued tasks for this document
    tasks = db.query(BackgroundTask).filter(
        BackgroundTask.user_id == user_id,
        BackgroundTask.type == "document_index",
        BackgroundTask.status.in_(["Queued", "Starting", "Running"])
    ).all()
    for t in tasks:
        payload = dict(t.payload or {})
        if payload.get("document_id") == str(doc.id):
            t.cancel_requested = True
            t.status = "Cancelled"
            t.completed_at = utc_now()

    db.commit()
    db.refresh(doc)
    return doc


def _delete_physical_object(
    storage_backend_name: str,
    storage_key: Optional[str],
    legacy_path: Optional[str] = None,
    storage_override=None,
    timeout_seconds: Optional[float] = None,
) -> tuple[bool, Optional[str]]:
    """
    Deletes an object from StorageBackend (and legacy local path if distinct).
    Returns (True, None) ONLY when deletion is verified successful or object no longer exists.
    Returns (False, error_message) on any storage error.
    """
    storage = storage_override or get_storage_backend(storage_backend_name or "local")
    if storage_key:
        try:
            if timeout_seconds is not None:
                import inspect
                sig = inspect.signature(storage.delete)
                if "timeout_seconds" in sig.parameters:
                    deleted = storage.delete(storage_key, timeout_seconds=timeout_seconds)
                else:
                    deleted = storage.delete(storage_key)
            else:
                deleted = storage.delete(storage_key)
            if not deleted:
                return False, f"Storage backend '{storage.backend_type}' returned False deleting '{storage_key}'"
        except Exception as e:
            return False, f"Storage deletion error for '{storage_key}': {str(e)}"

    if legacy_path and os.path.exists(legacy_path):
        try:
            safe_path = resolve_legacy_local_path(legacy_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
        except Exception as e:
            return False, f"Legacy file deletion error for '{legacy_path}': {str(e)}"

    return True, None


def request_document_deletion(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
) -> Dict[str, Any]:
    """
    Authoritative asynchronous document deletion request (preferred API lifecycle):
    1. Verifies user ownership.
    2. Atomically bumps index_generation, removes from KB, marks deletion_status='DELETING',
       clears any prior deletion_error, and cancels active document_index tasks.
    3. Creates or reuses a durable non-completed StorageDeletionOutbox entry WITHOUT ever
       stealing or overwriting an unexpired PROCESSING claim.
    4. Wakes the background outbox worker via Redis and returns an honest async payload.
    Physical deletion, DB row removal, and `library_update: deleted` broadcasts happen strictly
    in the lease-fenced outbox worker after physical storage deletion succeeds.
    """
    is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    doc_query = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id)
    if is_postgres:
        # Serialize concurrent deletion requests for the same document on PostgreSQL so
        # two simultaneous requests can NEVER insert duplicate active outbox rows.
        doc_query = doc_query.with_for_update()
    doc = doc_query.first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    now = utc_now()
    backend_name = getattr(doc, "storage_backend", "local") or "local"
    storage_key = doc.storage_key
    legacy_path = doc.storage_path if (doc.storage_path and doc.storage_path != storage_key) else None

    doc.index_generation = (getattr(doc, "index_generation", 0) or 0) + 1
    doc.is_knowledge_base = False
    doc.deletion_status = "DELETING"
    meta = dict(doc.metadata_json or {})
    meta.pop("deletion_error", None)
    doc.metadata_json = meta

    active_index_tasks = db.query(BackgroundTask).filter(
        BackgroundTask.user_id == user_id,
        BackgroundTask.type == "document_index",
        BackgroundTask.status.in_(["Queued", "Starting", "Running"]),
    ).all()
    cancelled_tasks = 0
    for t in active_index_tasks:
        if (t.payload or {}).get("document_id") == str(doc.id):
            t.cancel_requested = True
            t.status = "Cancelled"
            t.completed_at = now
            cancelled_tasks += 1

    outbox = (
        db.query(StorageDeletionOutbox)
        .filter(
            StorageDeletionOutbox.document_id == doc.id,
            StorageDeletionOutbox.status != "COMPLETED",
        )
        .order_by(StorageDeletionOutbox.created_at.asc())
        .first()
    )

    already_in_progress = False
    if not outbox:
        outbox = StorageDeletionOutbox(
            id=uuid.uuid4(),
            user_id=user_id,
            document_id=doc.id,
            storage_backend=backend_name,
            storage_key=storage_key or (legacy_path or f"document:{doc.id}"),
            legacy_path=legacy_path,
            status="PENDING",
            attempt_count=0,
            max_attempts=5,
            next_retry_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(outbox)
        db.commit()
        db.refresh(outbox)
        outbox_id = outbox.id
    else:
        outbox_id = outbox.id
        # NEVER steal or overwrite an active unexpired PROCESSING claim!
        if outbox.status == "PROCESSING":
            lease_exp = outbox.lease_expires_at
            if lease_exp is not None:
                if lease_exp.tzinfo is None:
                    lease_exp = lease_exp.replace(tzinfo=timezone.utc)
                if lease_exp > now:
                    already_in_progress = True
        elif outbox.status == "PENDING":
            outbox.next_retry_at = now
            outbox.updated_at = now
        elif outbox.status == "FAILED":
            outbox.status = "PENDING"
            outbox.attempt_count = 0
            outbox.worker_id = None
            outbox.claim_token = None
            outbox.claimed_at = None
            outbox.lease_expires_at = None
            outbox.last_error = None
            outbox.next_retry_at = now
            outbox.updated_at = now
        db.commit()

    db.refresh(doc)
    serialized = serialize_document(doc)
    if not already_in_progress:
        notify_outbox_worker(outbox_id)

    return {
        "status": "deleting",
        "deletion_status": "DELETING",
        "id": str(doc.id),
        "outbox_id": str(outbox_id),
        "cancelled_index_tasks": cancelled_tasks,
        "already_in_progress": already_in_progress,
        "file": serialized,
    }


def delete_document(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
    *,
    storage_override=None,
    raise_on_storage_error: bool = True,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
    renew_interval: Optional[float] = None,
    operation_timeout_seconds: float = 120.0,
    timeout_grace_seconds: float = 2.0,
    use_subprocess: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Synchronous compatibility wrapper over the EXACT same authoritative deletion lifecycle:
    1. Calls request_document_deletion() to record durable DELETING intent + outbox row.
    2. Recovers only expired claims and attempts conditional claim via claim_specific_outbox_entry().
    3. Executes physical deletion through _run_leased_outbox_deletion() with lease renewal,
       bounded termination/quarantine, and fenced finalization.
    """
    req_res = request_document_deletion(doc_id, user_id, db)
    outbox_id = uuid.UUID(req_res["outbox_id"])
    cancelled_tasks = req_res["cancelled_index_tasks"]

    # Recover only if an existing PROCESSING claim has actually expired
    recover_stale_outbox_claims(db)

    # Atomically acquire lease ownership through the same CAS/SKIP LOCKED claim path
    sync_worker_id = f"api_sync_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    entry = claim_specific_outbox_entry(
        session=db,
        outbox_id=outbox_id,
        worker_id=sync_worker_id,
        lease_seconds=lease_seconds,
    )
    if entry is None:
        # Another API call or background worker currently holds an active unexpired lease
        # (or already completed deletion). Do NOT start a duplicate physical deletion!
        db.expire_all()
        cur_outbox = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).first()
        if cur_outbox and cur_outbox.status == "COMPLETED":
            return {
                "status": "deleted",
                "deletion_status": "COMPLETED",
                "outbox_id": str(outbox_id),
                "cancelled_index_tasks": cancelled_tasks,
                "already_completed": True,
            }
        return {
            "status": "deleting",
            "deletion_status": "DELETING",
            "outbox_id": str(outbox_id),
            "cancelled_index_tasks": cancelled_tasks,
            "already_in_progress": True,
        }

    # Execute physical deletion under lease renewal & timeout safety, then finalize fenced
    run_res = _run_leased_outbox_deletion(
        session=db,
        entry=entry,
        worker_id=sync_worker_id,
        storage_override=storage_override,
        lease_seconds=lease_seconds,
        renew_interval=renew_interval,
        operation_timeout_seconds=operation_timeout_seconds,
        timeout_grace_seconds=timeout_grace_seconds,
        use_subprocess=use_subprocess,
    )
    outcome = run_res["outcome"]
    err_msg = run_res.get("error")

    if outcome == "completed":
        return {
            "status": "deleted",
            "deletion_status": "COMPLETED",
            "outbox_id": str(outbox_id),
            "cancelled_index_tasks": cancelled_tasks,
            "lease_renewals": run_res.get("renewals", 0),
        }

    if outcome == "stale":
        if raise_on_storage_error:
            raise HTTPException(
                status_code=409,
                detail=f"Deletion lease expired or was reassigned before completion (outbox_id={outbox_id}).",
            )
        return {
            "status": "deleting",
            "deletion_status": "DELETING",
            "outbox_id": str(outbox_id),
            "cancelled_index_tasks": cancelled_tasks,
            "lease_lost": True,
        }

    if outcome == "timed_out_quarantined":
        if raise_on_storage_error:
            raise HTTPException(
                status_code=504,
                detail=f"Storage deletion timed out; document retained for safe retry (outbox_id={outbox_id}).",
            )
        return {
            "status": "delete_failed",
            "deletion_status": "DELETE_FAILED",
            "outbox_id": str(outbox_id),
            "cancelled_index_tasks": cancelled_tasks,
            "error": err_msg,
            "timed_out": True,
        }

    # outcome is 'retried' or 'failed' (storage failed; Document preserved with DELETE_FAILED)
    if raise_on_storage_error:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to delete file from storage; document retained for retry (outbox_id={outbox_id}).",
        )
    return {
        "status": "delete_failed",
        "deletion_status": "DELETE_FAILED",
        "outbox_id": str(outbox_id),
        "cancelled_index_tasks": cancelled_tasks,
        "error": err_msg,
    }


def recover_stale_outbox_claims(db: Optional[Session] = None) -> int:
    """
    Atomically recovers StorageDeletionOutbox rows stuck in PROCESSING whose lease has expired.
    Fences recovery by (id, status='PROCESSING', worker_id, claim_token, expired lease)
    so an active worker's fresh claim is never disrupted.
    """
    now = utc_now()

    def _run(session: Session) -> int:
        stale = session.query(StorageDeletionOutbox).filter(
            StorageDeletionOutbox.status == "PROCESSING",
            or_(
                StorageDeletionOutbox.lease_expires_at.is_(None),
                StorageDeletionOutbox.lease_expires_at < now,
            ),
        ).all()

        snaps = [
            (
                row.id,
                row.user_id,
                row.document_id,
                row.worker_id,
                row.claim_token,
                int(row.attempt_count or 0),
                int(row.max_attempts or 5),
                row.last_error,
            )
            for row in stale
        ]
        recovered = 0
        for oid, uid, doc_id, old_worker, old_token, attempts, max_att, prev_err in snaps:
            filters = [
                StorageDeletionOutbox.id == oid,
                StorageDeletionOutbox.status == "PROCESSING",
                StorageDeletionOutbox.worker_id == old_worker,
                StorageDeletionOutbox.claim_token == old_token,
                or_(
                    StorageDeletionOutbox.lease_expires_at.is_(None),
                    StorageDeletionOutbox.lease_expires_at < now,
                ),
            ]
            next_attempts = attempts + 1
            if next_attempts >= max_att:
                fail_err = prev_err or "Outbox lease expired after max attempts."
                rows = session.query(StorageDeletionOutbox).filter(*filters).update(
                    {
                        StorageDeletionOutbox.status: "FAILED",
                        StorageDeletionOutbox.attempt_count: next_attempts,
                        StorageDeletionOutbox.worker_id: None,
                        StorageDeletionOutbox.claim_token: None,
                        StorageDeletionOutbox.claimed_at: None,
                        StorageDeletionOutbox.lease_expires_at: None,
                        StorageDeletionOutbox.next_retry_at: None,
                        StorageDeletionOutbox.last_error: fail_err,
                        StorageDeletionOutbox.updated_at: now,
                    },
                    synchronize_session=False,
                )
                if rows == 1:
                    failed_doc_payload = None
                    if doc_id:
                        doc_rec = session.query(Document).filter(Document.id == doc_id).first()
                        if doc_rec:
                            doc_rec.deletion_status = "DELETE_FAILED"
                            doc_rec.metadata_json = {**(doc_rec.metadata_json or {}), "deletion_error": fail_err}
                            failed_doc_payload = serialize_document(doc_rec)
                    session.commit()
                    session.expire_all()
                    if failed_doc_payload and uid:
                        try:
                            from realtime.manager import publish_user_realtime_event_sync
                            publish_user_realtime_event_sync(
                                str(uid),
                                {"type": "library_update", "action": "updated", "data": failed_doc_payload},
                            )
                        except Exception:
                            pass
                else:
                    session.rollback()
            else:
                rows = session.query(StorageDeletionOutbox).filter(*filters).update(
                    {
                        StorageDeletionOutbox.status: "PENDING",
                        StorageDeletionOutbox.attempt_count: next_attempts,
                        StorageDeletionOutbox.worker_id: None,
                        StorageDeletionOutbox.claim_token: None,
                        StorageDeletionOutbox.claimed_at: None,
                        StorageDeletionOutbox.lease_expires_at: None,
                        StorageDeletionOutbox.next_retry_at: now,
                        StorageDeletionOutbox.updated_at: now,
                    },
                    synchronize_session=False,
                )
                if rows == 1:
                    session.commit()
                    session.expire_all()
                    recovered += 1
                else:
                    session.rollback()
        return recovered

    if db is not None:
        return _run(db)
    with get_db_context() as session:
        return _run(session)


def claim_storage_deletion_outbox_entries(
    session: Session,
    worker_id: str,
    limit: int = 50,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Atomically claims up to `limit` due PENDING StorageDeletionOutbox rows by transitioning
    them to PROCESSING with a unique claim_token and lease_expires_at.
    Uses PostgreSQL FOR UPDATE SKIP LOCKED when on PostgreSQL, and atomic per-row
    conditional UPDATE on SQLite so concurrent workers never double-claim the same row.
    """
    now = utc_now()
    lease_exp = now + timedelta(seconds=max(0.2, float(lease_seconds)))
    is_postgres = bool(session.bind and session.bind.dialect.name == "postgresql")
    claimed: List[Dict[str, Any]] = []

    if is_postgres:
        rows = (
            session.query(StorageDeletionOutbox)
            .filter(
                StorageDeletionOutbox.status == "PENDING",
                or_(
                    StorageDeletionOutbox.next_retry_at.is_(None),
                    StorageDeletionOutbox.next_retry_at <= now,
                ),
            )
            .order_by(StorageDeletionOutbox.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for row in rows:
            token = uuid.uuid4()
            row.status = "PROCESSING"
            row.worker_id = worker_id
            row.claim_token = token
            row.claimed_at = now
            row.lease_expires_at = lease_exp
            row.updated_at = now
            claimed.append({
                "id": row.id,
                "user_id": row.user_id,
                "document_id": row.document_id,
                "storage_backend": row.storage_backend,
                "storage_key": row.storage_key,
                "legacy_path": row.legacy_path,
                "attempt_count": int(row.attempt_count or 0),
                "max_attempts": int(row.max_attempts or 5),
                "claim_token": token,
            })
        session.commit()
        session.expire_all()
        return claimed

    # SQLite / fallback: per-row atomic conditional CAS UPDATE
    candidates = (
        session.query(StorageDeletionOutbox)
        .filter(
            StorageDeletionOutbox.status == "PENDING",
            or_(
                StorageDeletionOutbox.next_retry_at.is_(None),
                StorageDeletionOutbox.next_retry_at <= now,
            ),
        )
        .order_by(StorageDeletionOutbox.created_at.asc())
        .limit(limit)
        .all()
    )
    cand_snaps = [
        (
            c.id,
            c.user_id,
            c.document_id,
            c.storage_backend,
            c.storage_key,
            c.legacy_path,
            int(c.attempt_count or 0),
            int(c.max_attempts or 5),
        )
        for c in candidates
    ]

    for cid, uid, doc_id, backend, skey, lpath, attempts, max_att in cand_snaps:
        token = uuid.uuid4()
        updated = session.query(StorageDeletionOutbox).filter(
            StorageDeletionOutbox.id == cid,
            StorageDeletionOutbox.status == "PENDING",
            or_(
                StorageDeletionOutbox.next_retry_at.is_(None),
                StorageDeletionOutbox.next_retry_at <= now,
            ),
        ).update(
            {
                StorageDeletionOutbox.status: "PROCESSING",
                StorageDeletionOutbox.worker_id: worker_id,
                StorageDeletionOutbox.claim_token: token,
                StorageDeletionOutbox.claimed_at: now,
                StorageDeletionOutbox.lease_expires_at: lease_exp,
                StorageDeletionOutbox.updated_at: now,
            },
            synchronize_session=False,
        )
        if updated == 1:
            session.commit()
            session.expire_all()
            claimed.append({
                "id": cid,
                "user_id": uid,
                "document_id": doc_id,
                "storage_backend": backend,
                "storage_key": skey,
                "legacy_path": lpath,
                "attempt_count": attempts,
                "max_attempts": max_att,
                "claim_token": token,
            })
        else:
            session.rollback()
    return claimed


def _execute_outbox_physical_deletion(
    entry: Dict[str, Any],
    storage_override=None,
    timeout_seconds: Optional[float] = None,
) -> tuple[bool, Optional[str]]:
    """Performs the physical storage/workspace deletion described by a claimed outbox snapshot."""
    skey = entry.get("storage_key") or ""
    backend = entry.get("storage_backend") or "local"
    lpath = entry.get("legacy_path")

    if backend == "workspace" or skey.startswith("workspace:"):
        ok = True
        err_msg = None
        if lpath and os.path.exists(lpath):
            try:
                shutil.rmtree(lpath)
            except Exception as e:
                err_msg = str(e)
            if os.path.exists(lpath):
                ok = False
                err_msg = err_msg or f"Workspace directory still exists: {lpath}"
        return ok, err_msg

    if skey.startswith("prefix_scan:"):
        scan_prefix = skey[len("prefix_scan:"):]
        storage = storage_override or get_storage_backend(backend)
        try:
            remaining_keys = storage.list_keys(prefix=scan_prefix)
            failed_sub = []
            for k in remaining_keys:
                try:
                    if not storage.delete(k):
                        failed_sub.append(k)
                except Exception:
                    failed_sub.append(k)
            if failed_sub:
                return False, f"Failed to delete {len(failed_sub)} object(s) under {scan_prefix}"
            return True, None
        except Exception as e:
            return False, f"Prefix scan retry failed for '{scan_prefix}': {e}"

    if skey.startswith("legacy:"):
        return _delete_physical_object(
            storage_backend_name=backend,
            storage_key=None,
            legacy_path=lpath,
            storage_override=storage_override,
            timeout_seconds=timeout_seconds,
        )

    return _delete_physical_object(
        storage_backend_name=backend,
        storage_key=skey if not skey.startswith("document:") else None,
        legacy_path=lpath,
        storage_override=storage_override,
        timeout_seconds=timeout_seconds,
    )


def claim_specific_outbox_entry(
    session: Session,
    outbox_id: uuid.UUID,
    worker_id: str,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
) -> Optional[Dict[str, Any]]:
    """
    Atomically claims a single PENDING StorageDeletionOutbox row by ID.
    NEVER steals or overwrites an unexpired PROCESSING claim!
    Uses PostgreSQL FOR UPDATE SKIP LOCKED when on PostgreSQL and conditional CAS UPDATE on SQLite.
    """
    now = utc_now()
    lease_exp = now + timedelta(seconds=max(0.2, float(lease_seconds)))
    is_postgres = bool(session.bind and session.bind.dialect.name == "postgresql")

    if is_postgres:
        row = (
            session.query(StorageDeletionOutbox)
            .filter(
                StorageDeletionOutbox.id == outbox_id,
                StorageDeletionOutbox.status == "PENDING",
            )
            .with_for_update(skip_locked=True)
            .first()
        )
        if not row:
            return None
        token = uuid.uuid4()
        row.status = "PROCESSING"
        row.worker_id = worker_id
        row.claim_token = token
        row.claimed_at = now
        row.lease_expires_at = lease_exp
        row.updated_at = now
        snap = {
            "id": row.id,
            "user_id": row.user_id,
            "document_id": row.document_id,
            "storage_backend": row.storage_backend,
            "storage_key": row.storage_key,
            "legacy_path": row.legacy_path,
            "attempt_count": int(row.attempt_count or 0),
            "max_attempts": int(row.max_attempts or 5),
            "claim_token": token,
        }
        session.commit()
        session.expire_all()
        return snap

    cand = session.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.id == outbox_id,
        StorageDeletionOutbox.status == "PENDING",
    ).first()
    if not cand:
        return None

    snap_base = (
        cand.id,
        cand.user_id,
        cand.document_id,
        cand.storage_backend,
        cand.storage_key,
        cand.legacy_path,
        int(cand.attempt_count or 0),
        int(cand.max_attempts or 5),
    )
    token = uuid.uuid4()
    updated = session.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.id == outbox_id,
        StorageDeletionOutbox.status == "PENDING",
    ).update(
        {
            StorageDeletionOutbox.status: "PROCESSING",
            StorageDeletionOutbox.worker_id: worker_id,
            StorageDeletionOutbox.claim_token: token,
            StorageDeletionOutbox.claimed_at: now,
            StorageDeletionOutbox.lease_expires_at: lease_exp,
            StorageDeletionOutbox.updated_at: now,
        },
        synchronize_session=False,
    )
    if updated == 1:
        session.commit()
        session.expire_all()
        return {
            "id": snap_base[0],
            "user_id": snap_base[1],
            "document_id": snap_base[2],
            "storage_backend": snap_base[3],
            "storage_key": snap_base[4],
            "legacy_path": snap_base[5],
            "attempt_count": snap_base[6],
            "max_attempts": snap_base[7],
            "claim_token": token,
        }
    session.rollback()
    return None


def renew_outbox_claim_lease(
    session: Session,
    entry_id: uuid.UUID,
    worker_id: str,
    claim_token: uuid.UUID,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
) -> bool:
    """
    Atomically renews an active PROCESSING lease for a long-running storage deletion.
    Fenced by (id, status='PROCESSING', worker_id, claim_token, unexpired lease).
    Returns True ONLY if this worker still holds a valid unexpired lease.
    """
    now = utc_now()
    new_exp = now + timedelta(seconds=max(0.2, float(lease_seconds)))
    rows = session.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.id == entry_id,
        StorageDeletionOutbox.status == "PROCESSING",
        StorageDeletionOutbox.worker_id == worker_id,
        StorageDeletionOutbox.claim_token == claim_token,
        StorageDeletionOutbox.lease_expires_at.isnot(None),
        StorageDeletionOutbox.lease_expires_at > now,
    ).update(
        {
            StorageDeletionOutbox.lease_expires_at: new_exp,
            StorageDeletionOutbox.updated_at: now,
        },
        synchronize_session=False,
    )
    if rows == 1:
        session.commit()
        session.expire_all()
        return True
    session.rollback()
    return False


def finalize_claimed_outbox_entry(
    session: Session,
    entry: Dict[str, Any],
    worker_id: str,
    ok: bool,
    err_msg: Optional[str],
) -> str:
    """
    Fenced finalization of a claimed StorageDeletionOutbox row.
    Verifies (id, status='PROCESSING', worker_id, claim_token, unexpired lease) BEFORE
    writing or deleting any DB records so a stale or expired worker can NEVER overwrite
    a recovered entry or delete Document/GeneratedImage rows after lease expiration.
    Also updates Document.deletion_status='DELETE_FAILED' on storage failure while retaining the row.
    Returns one of: 'completed', 'retried', 'failed', 'stale'.
    """
    step_now = utc_now()
    next_attempts = int(entry["attempt_count"]) + 1
    max_att = int(entry["max_attempts"] or 5)
    fence = [
        StorageDeletionOutbox.id == entry["id"],
        StorageDeletionOutbox.status == "PROCESSING",
        StorageDeletionOutbox.worker_id == worker_id,
        StorageDeletionOutbox.claim_token == entry["claim_token"],
        StorageDeletionOutbox.lease_expires_at.isnot(None),
        StorageDeletionOutbox.lease_expires_at > step_now,
    ]

    if ok:
        try:
            rows = session.query(StorageDeletionOutbox).filter(*fence).update(
                {
                    StorageDeletionOutbox.status: "COMPLETED",
                    StorageDeletionOutbox.attempt_count: next_attempts,
                    StorageDeletionOutbox.last_error: None,
                    StorageDeletionOutbox.completed_at: step_now,
                    StorageDeletionOutbox.next_retry_at: None,
                    StorageDeletionOutbox.worker_id: None,
                    StorageDeletionOutbox.claim_token: None,
                    StorageDeletionOutbox.lease_expires_at: None,
                    StorageDeletionOutbox.updated_at: step_now,
                },
                synchronize_session=False,
            )
            if rows != 1:
                session.rollback()
                return "stale"

            if entry.get("document_id"):
                session.query(GeneratedImage).filter(
                    GeneratedImage.document_id == entry["document_id"]
                ).delete(synchronize_session=False)
                doc_rec = session.query(Document).filter(Document.id == entry["document_id"]).first()
                if doc_rec:
                    session.delete(doc_rec)
            session.commit()
            session.expire_all()
        except Exception:
            session.rollback()
            raise

        # Broadcast completed deletion ONLY AFTER physical deletion AND DB commit succeeded!
        if entry.get("document_id") and entry.get("user_id"):
            try:
                from realtime.manager import publish_user_realtime_event_sync
                publish_user_realtime_event_sync(
                    str(entry["user_id"]),
                    {
                        "type": "library_update",
                        "action": "deleted",
                        "data": {
                            "id": str(entry["document_id"]),
                            "deletion_status": "COMPLETED",
                        },
                    },
                )
            except Exception:
                pass
        return "completed"

    if next_attempts >= max_att:
        target_status = "FAILED"
        next_retry = None
        outcome = "failed"
    else:
        backoff = min(60 * (2 ** (next_attempts - 1)), 3600)
        target_status = "PENDING"
        next_retry = step_now + timedelta(seconds=backoff)
        outcome = "retried"

    try:
        rows = session.query(StorageDeletionOutbox).filter(*fence).update(
            {
                StorageDeletionOutbox.status: target_status,
                StorageDeletionOutbox.attempt_count: next_attempts,
                StorageDeletionOutbox.last_error: err_msg,
                StorageDeletionOutbox.next_retry_at: next_retry,
                StorageDeletionOutbox.worker_id: None,
                StorageDeletionOutbox.claim_token: None,
                StorageDeletionOutbox.claimed_at: None,
                StorageDeletionOutbox.lease_expires_at: None,
                StorageDeletionOutbox.updated_at: step_now,
            },
            synchronize_session=False,
        )
        if rows != 1:
            session.rollback()
            return "stale"

        failed_doc_payload = None
        if entry.get("document_id"):
            doc_rec = session.query(Document).filter(Document.id == entry["document_id"]).first()
            if doc_rec:
                doc_rec.deletion_status = "DELETE_FAILED"
                doc_rec.metadata_json = {**(doc_rec.metadata_json or {}), "deletion_error": err_msg}
                failed_doc_payload = serialize_document(doc_rec)
        session.commit()
        session.expire_all()
    except Exception:
        session.rollback()
        raise

    if failed_doc_payload and entry.get("user_id"):
        try:
            from realtime.manager import publish_user_realtime_event_sync
            publish_user_realtime_event_sync(
                str(entry["user_id"]),
                {
                    "type": "library_update",
                    "action": "updated",
                    "data": failed_doc_payload,
                },
            )
        except Exception:
            pass
    return outcome


def _run_leased_outbox_deletion_subprocess(
    session: Session,
    entry: Dict[str, Any],
    worker_id: str,
    *,
    effective_lease: float,
    effective_renew: float,
    effective_timeout: float,
    effective_grace: float,
    worker_cancel_event=None,
    subprocess_test_delay_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Executes physical storage deletion inside a killable isolated OS subprocess
    (`python -m services.storage_delete_runner`) while periodically renewing the DB lease.
    On timeout, lease loss, or worker cancellation: terminates -> kills -> reaps the OS
    subprocess definitively before returning, guaranteeing zero uncontrolled storage mutation.
    """
    import json
    import sys
    import time
    import signal
    import threading
    import subprocess

    max_capture_chars = 65536
    serializable_entry = {
        "id": str(entry.get("id") or ""),
        "user_id": str(entry.get("user_id") or ""),
        "document_id": str(entry.get("document_id") or "") if entry.get("document_id") else None,
        "storage_backend": entry.get("storage_backend") or "local",
        "storage_key": entry.get("storage_key") or "",
        "legacy_path": entry.get("legacy_path"),
    }
    stdin_payload = json.dumps(
        {
            "entry": serializable_entry,
            "timeout_seconds": effective_timeout,
            "test_delay_seconds": subprocess_test_delay_seconds,
        }
    )

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    popen_kwargs: Dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": backend_dir,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [sys.executable, "-m", "services.storage_delete_runner"],
        **popen_kwargs,
    )
    if proc.stdin is not None:
        try:
            proc.stdin.write(stdin_payload)
            proc.stdin.close()
        except Exception:
            pass

    # Concurrently drain stdout/stderr into bounded tail/head buffers so large output can NEVER
    # fill OS pipe buffers and deadlock the child process while waiting.
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    def _drain_pipe(pipe, target_list: List[str], keep_tail: bool) -> None:
        if pipe is None:
            return
        captured_len = 0
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                if keep_tail:
                    target_list.append(chunk)
                    captured_len += len(chunk)
                    while captured_len > max_capture_chars and len(target_list) > 1:
                        removed = target_list.pop(0)
                        captured_len -= len(removed)
                    if captured_len > max_capture_chars and target_list:
                        target_list[0] = target_list[0][-max_capture_chars:]
                        captured_len = len(target_list[0])
                elif captured_len < max_capture_chars:
                    remaining_cap = max_capture_chars - captured_len
                    target_list.append(chunk[:remaining_cap])
                    captured_len += min(len(chunk), remaining_cap)
        except Exception:
            pass

    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(proc.stdout, stdout_chunks, True),
        name=f"outbox-stdout-{str(entry['id'])[:8]}",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(proc.stderr, stderr_chunks, False),
        name=f"outbox-stderr-{str(entry['id'])[:8]}",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    def _terminate_win32_tree(root_pid: int) -> None:
        import ctypes
        from ctypes import wintypes

        class _PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snap in (0, -1, wintypes.HANDLE(-1).value):
            return
        children_by_parent: Dict[int, List[int]] = {}
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok_walk = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok_walk:
                children_by_parent.setdefault(int(entry.th32ParentProcessID), []).append(int(entry.th32ProcessID))
                ok_walk = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)

        # Collect descendants BFS, then terminate leaves-first before root_pid
        ordered: List[int] = []
        queue = [int(root_pid)]
        seen = {int(root_pid)}
        while queue:
            cur = queue.pop(0)
            ordered.append(cur)
            for child in children_by_parent.get(cur, ()):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)

        for target_pid in reversed(ordered):
            handle = kernel32.OpenProcess(0x0001, False, target_pid)  # PROCESS_TERMINATE
            if handle:
                try:
                    kernel32.TerminateProcess(handle, 1)
                finally:
                    kernel32.CloseHandle(handle)

    def _kill_process_tree(pid: int, force: bool) -> None:
        if os.name == "nt":
            # Use Win32 Toolhelp snapshot to walk and terminate descendants + root in <2ms
            # without spawning taskkill (which can hang or miss children if parent dies first).
            try:
                _terminate_win32_tree(pid)
            except Exception:
                pass
            if force:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            # Because start_new_session=True sets pgid == proc.pid, killpg(pid, sig) reaches
            # all descendants even if the leader already exited.
            try:
                if pid != os.getpgrp():
                    os.killpg(pid, sig)
                else:
                    os.kill(pid, sig)
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    proc.kill() if force else proc.terminate()
                except Exception:
                    pass

    def _terminate_and_reap():
        if proc.poll() is None:
            if os.name == "nt":
                # On Windows, immediately terminate the full tree with /F /T so grandchildren
                # are never orphaned by parent-only termination.
                _kill_process_tree(proc.pid, force=True)
                try:
                    proc.wait(timeout=max(effective_grace, 2.0))
                except Exception:
                    pass
            else:
                _kill_process_tree(proc.pid, force=False)
                try:
                    proc.wait(timeout=effective_grace)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc.pid, force=True)
                    try:
                        proc.wait(timeout=5.0)
                    except Exception:
                        pass
                # Final sweep of any surviving descendants in the session's process group
                _kill_process_tree(proc.pid, force=True)
        else:
            if os.name != "nt":
                _kill_process_tree(proc.pid, force=True)

    start_mono = time.monotonic()
    last_renew_mono = start_mono
    renewals = 0
    lease_lost = False
    timed_out = False
    cancelled = False

    try:
        while proc.poll() is None:
            if worker_cancel_event is not None and worker_cancel_event.is_set():
                cancelled = True
                break
            elapsed = time.monotonic() - start_mono
            remaining = effective_timeout - elapsed
            if remaining <= 0:
                timed_out = True
                break
            wait_slice = min(effective_renew, remaining, 0.15)
            try:
                proc.wait(timeout=wait_slice)
                break
            except subprocess.TimeoutExpired:
                pass

            now_mono = time.monotonic()
            if now_mono - last_renew_mono >= effective_renew * 0.9:
                renewed = renew_outbox_claim_lease(
                    session=session,
                    entry_id=entry["id"],
                    worker_id=worker_id,
                    claim_token=entry["claim_token"],
                    lease_seconds=effective_lease,
                )
                if not renewed:
                    lease_lost = True
                    break
                renewals += 1
                last_renew_mono = now_mono

        if lease_lost:
            _terminate_and_reap()
            return {
                "outcome": "stale",
                "renewals": renewals,
                "error": "Lease ownership lost during deletion; subprocess terminated",
                "subprocess_terminated": True,
            }

        if cancelled:
            _terminate_and_reap()
            # Subprocess is definitively dead; release claim back to PENDING strictly under unexpired lease fence
            step_now = utc_now()
            released = session.query(StorageDeletionOutbox).filter(
                StorageDeletionOutbox.id == entry["id"],
                StorageDeletionOutbox.status == "PROCESSING",
                StorageDeletionOutbox.worker_id == worker_id,
                StorageDeletionOutbox.claim_token == entry["claim_token"],
                StorageDeletionOutbox.lease_expires_at.isnot(None),
                StorageDeletionOutbox.lease_expires_at > step_now,
            ).update(
                {
                    StorageDeletionOutbox.status: "PENDING",
                    StorageDeletionOutbox.worker_id: None,
                    StorageDeletionOutbox.claim_token: None,
                    StorageDeletionOutbox.claimed_at: None,
                    StorageDeletionOutbox.lease_expires_at: None,
                    StorageDeletionOutbox.next_retry_at: step_now,
                    StorageDeletionOutbox.last_error: "Worker cancelled before deletion completed",
                    StorageDeletionOutbox.updated_at: step_now,
                },
                synchronize_session=False,
            )
            if released != 1:
                session.rollback()
                return {
                    "outcome": "stale",
                    "renewals": renewals,
                    "error": "Lease expired or reassigned before cancellation release",
                    "subprocess_terminated": True,
                }
            session.commit()
            session.expire_all()
            return {
                "outcome": "cancelled",
                "renewals": renewals,
                "error": "Worker cancelled before deletion completed",
                "subprocess_terminated": True,
            }

        if timed_out:
            _terminate_and_reap()
            timeout_err = f"Storage deletion subprocess timed out after {effective_timeout:.2f}s and was terminated"
            outcome = finalize_claimed_outbox_entry(session, entry, worker_id, False, timeout_err)
            return {
                "outcome": outcome,
                "renewals": renewals,
                "error": timeout_err,
                "subprocess_terminated": True,
            }

        stdout_thread.join(timeout=2.0)
        stderr_thread.join(timeout=2.0)
        stdout_data = "".join(stdout_chunks)
        stderr_data = "".join(stderr_chunks)
        ok_val = False
        err_val = None
        parsed = None
        for line in reversed(stdout_data.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and isinstance(candidate.get("ok"), bool):
                        parsed = candidate
                        break
                except Exception:
                    pass

        if proc.returncode != 0:
            ok_val = False
            parsed_err = parsed.get("error") if isinstance(parsed, dict) else None
            err_val = (
                str(parsed_err)
                if parsed_err
                else (stderr_data.strip() or f"Deletion subprocess exited with non-zero code {proc.returncode}")
            )[:500]
        elif parsed is not None:
            ok_val = bool(parsed["ok"])
            err_val = parsed.get("error")
        else:
            ok_val = False
            err_val = (
                stderr_data.strip()
                or f"Deletion subprocess produced malformed or missing JSON result (code {proc.returncode})"
            )[:500]

        outcome = finalize_claimed_outbox_entry(session, entry, worker_id, ok_val, err_val)
        return {"outcome": outcome, "renewals": renewals, "error": err_val, "subprocess_terminated": False}
    finally:
        _terminate_and_reap()
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass


def _run_leased_outbox_deletion(
    session: Session,
    entry: Dict[str, Any],
    worker_id: str,
    *,
    storage_override=None,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
    renew_interval: Optional[float] = None,
    operation_timeout_seconds: float = 300.0,
    timeout_grace_seconds: float = 2.0,
    worker_cancel_event=None,
    use_subprocess: Optional[bool] = None,
    subprocess_test_delay_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Unified lease-renewing, timeout-safe executor for a claimed outbox entry.
    - When `use_subprocess` is enabled (default for standard storage backends when no in-process
      `storage_override` is injected and `SAKURA_OUTBOX_SUBPROCESS != "0"`): runs physical
      deletion inside a killable isolated OS subprocess so timeout, lease loss, or worker
      cancellation definitively terminates the operation (`SIGTERM` -> `SIGKILL` + `wait()`).
    - When running in-process (custom `storage_override` or `use_subprocess=False`): runs on a
      single thread with cooperative `cancel_event`, periodic lease renewal, immediate abort on
      lease loss (`stale`, zero DB writes), and exclusive `PROCESSING` quarantine if uninterruptible
      I/O is still running after grace so no concurrent second worker can race it.
    """
    import time
    import threading

    effective_lease = max(0.2, float(lease_seconds))
    effective_renew = float(renew_interval) if renew_interval is not None else max(0.05, effective_lease * 0.4)
    effective_timeout = max(0.05, float(operation_timeout_seconds))
    effective_grace = max(0.05, float(timeout_grace_seconds))

    should_use_subprocess = (
        bool(use_subprocess)
        if use_subprocess is not None
        else (storage_override is None and os.getenv("SAKURA_OUTBOX_SUBPROCESS", "1").strip() != "0")
    )
    if should_use_subprocess and storage_override is None:
        return _run_leased_outbox_deletion_subprocess(
            session=session,
            entry=entry,
            worker_id=worker_id,
            effective_lease=effective_lease,
            effective_renew=effective_renew,
            effective_timeout=effective_timeout,
            effective_grace=effective_grace,
            worker_cancel_event=worker_cancel_event,
            subprocess_test_delay_seconds=subprocess_test_delay_seconds,
        )

    cancel_event = threading.Event()
    result_box: Dict[str, Any] = {"done": False, "ok": False, "error": None}

    def _target():
        try:
            if storage_override is not None and hasattr(storage_override, "set_cancel_event"):
                try:
                    storage_override.set_cancel_event(cancel_event)
                except Exception:
                    pass
            ok_val, err_val = _execute_outbox_physical_deletion(
                entry,
                storage_override=storage_override,
                timeout_seconds=effective_timeout,
            )
            result_box["ok"] = ok_val
            result_box["error"] = err_val
        except Exception as exc:
            result_box["ok"] = False
            result_box["error"] = str(exc)
        finally:
            result_box["done"] = True

    worker_thread = threading.Thread(
        target=_target,
        name=f"outbox-del-{str(entry['id'])[:8]}",
        daemon=True,
    )
    start_mono = time.monotonic()
    last_renew_mono = start_mono
    renewals = 0
    lease_lost = False
    timed_out = False
    cancelled = False

    worker_thread.start()
    while worker_thread.is_alive():
        if worker_cancel_event is not None and worker_cancel_event.is_set():
            cancelled = True
            cancel_event.set()
            break
        elapsed = time.monotonic() - start_mono
        remaining = effective_timeout - elapsed
        if remaining <= 0:
            timed_out = True
            cancel_event.set()
            break
        wait_slice = min(effective_renew, remaining, 0.15)
        worker_thread.join(timeout=wait_slice)
        if not worker_thread.is_alive():
            break
        now_mono = time.monotonic()
        if now_mono - last_renew_mono >= effective_renew * 0.9:
            renewed = renew_outbox_claim_lease(
                session=session,
                entry_id=entry["id"],
                worker_id=worker_id,
                claim_token=entry["claim_token"],
                lease_seconds=effective_lease,
            )
            if not renewed:
                lease_lost = True
                cancel_event.set()
                break
            renewals += 1
            last_renew_mono = now_mono

    if lease_lost:
        worker_thread.join(timeout=min(effective_grace, 0.25))
        return {"outcome": "stale", "renewals": renewals, "error": "Lease ownership lost during deletion"}

    if cancelled:
        worker_thread.join(timeout=effective_grace)
        if not worker_thread.is_alive():
            step_now = utc_now()
            released = session.query(StorageDeletionOutbox).filter(
                StorageDeletionOutbox.id == entry["id"],
                StorageDeletionOutbox.status == "PROCESSING",
                StorageDeletionOutbox.worker_id == worker_id,
                StorageDeletionOutbox.claim_token == entry["claim_token"],
                StorageDeletionOutbox.lease_expires_at.isnot(None),
                StorageDeletionOutbox.lease_expires_at > step_now,
            ).update(
                {
                    StorageDeletionOutbox.status: "PENDING",
                    StorageDeletionOutbox.worker_id: None,
                    StorageDeletionOutbox.claim_token: None,
                    StorageDeletionOutbox.claimed_at: None,
                    StorageDeletionOutbox.lease_expires_at: None,
                    StorageDeletionOutbox.next_retry_at: step_now,
                    StorageDeletionOutbox.last_error: "Worker cancelled before deletion completed",
                    StorageDeletionOutbox.updated_at: step_now,
                },
                synchronize_session=False,
            )
            if released != 1:
                session.rollback()
                return {"outcome": "stale", "renewals": renewals, "error": "Lease expired or reassigned before cancellation release"}
            session.commit()
            session.expire_all()
            return {"outcome": "cancelled", "renewals": renewals, "error": "Worker cancelled before deletion completed"}
        # Thread is still alive -> quarantine in PROCESSING so no second worker can race it!
        return {"outcome": "timed_out_quarantined", "renewals": renewals, "error": "Worker cancelled while storage I/O still active (quarantined)"}

    if timed_out:
        timeout_err = f"Storage deletion operation timed out after {effective_timeout:.2f}s"
        worker_thread.join(timeout=effective_grace)
        if worker_thread.is_alive():
            step_now = utc_now()
            quarantine_exp = step_now + timedelta(seconds=max(effective_lease, effective_grace))
            updated = session.query(StorageDeletionOutbox).filter(
                StorageDeletionOutbox.id == entry["id"],
                StorageDeletionOutbox.status == "PROCESSING",
                StorageDeletionOutbox.worker_id == worker_id,
                StorageDeletionOutbox.claim_token == entry["claim_token"],
                StorageDeletionOutbox.lease_expires_at.isnot(None),
                StorageDeletionOutbox.lease_expires_at > step_now,
            ).update(
                {
                    StorageDeletionOutbox.last_error: f"{timeout_err} (quarantined pending operation stop)",
                    StorageDeletionOutbox.attempt_count: int(entry["attempt_count"]) + 1,
                    StorageDeletionOutbox.lease_expires_at: quarantine_exp,
                    StorageDeletionOutbox.updated_at: step_now,
                },
                synchronize_session=False,
            )
            if updated == 1:
                failed_doc_payload = None
                if entry.get("document_id"):
                    doc_rec = session.query(Document).filter(Document.id == entry["document_id"]).first()
                    if doc_rec:
                        doc_rec.deletion_status = "DELETE_FAILED"
                        doc_rec.metadata_json = {**(doc_rec.metadata_json or {}), "deletion_error": timeout_err}
                        failed_doc_payload = serialize_document(doc_rec)
                session.commit()
                session.expire_all()
                if failed_doc_payload and entry.get("user_id"):
                    try:
                        from realtime.manager import publish_user_realtime_event_sync
                        publish_user_realtime_event_sync(
                            str(entry["user_id"]),
                            {"type": "library_update", "action": "updated", "data": failed_doc_payload},
                        )
                    except Exception:
                        pass
                return {"outcome": "timed_out_quarantined", "renewals": renewals, "error": timeout_err}
            session.rollback()
            return {"outcome": "stale", "renewals": renewals, "error": timeout_err}

        outcome = finalize_claimed_outbox_entry(session, entry, worker_id, False, timeout_err)
        return {"outcome": outcome, "renewals": renewals, "error": timeout_err}

    outcome = finalize_claimed_outbox_entry(
        session,
        entry,
        worker_id,
        bool(result_box["ok"]),
        result_box.get("error"),
    )
    return {"outcome": outcome, "renewals": renewals, "error": result_box.get("error")}


def process_storage_deletion_outbox(
    db: Optional[Session] = None,
    limit: int = 50,
    storage_override=None,
    worker_id: Optional[str] = None,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
    renew_interval: Optional[float] = None,
    operation_timeout_seconds: float = 300.0,
    timeout_grace_seconds: float = 2.0,
    worker_cancel_event=None,
    use_subprocess: Optional[bool] = None,
    subprocess_test_delay_seconds: Optional[float] = None,
) -> Dict[str, int]:
    """
    Multi-worker-safe processor for StorageDeletionOutbox:
    1. Recovers any stale PROCESSING claims whose leases expired.
    2. Atomically claims due PENDING rows one-by-one with worker_id + claim_token + lease_expires_at.
    3. Executes physical deletion under the unified lease-renewing, timeout-safe runner
       (killable isolated subprocess by default for real storage backends).
    4. Fences every completion/retry/failure update by (id, PROCESSING, worker_id, claim_token,
       unexpired lease) so expired or displaced workers never write DB state.
    """
    effective_worker = worker_id or f"outbox_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    stats = {
        "recovered": 0,
        "processed": 0,
        "completed": 0,
        "retried": 0,
        "failed": 0,
        "stale": 0,
        "cancelled": 0,
        "timed_out_quarantined": 0,
        "renewals": 0,
        "subprocess_terminated": 0,
    }

    def _run(session: Session):
        stats["recovered"] = recover_stale_outbox_claims(session)
        for _ in range(max(0, int(limit))):
            if worker_cancel_event is not None and worker_cancel_event.is_set():
                break
            claimed = claim_storage_deletion_outbox_entries(
                session=session,
                worker_id=effective_worker,
                limit=1,
                lease_seconds=lease_seconds,
            )
            if not claimed:
                break
            entry = claimed[0]
            stats["processed"] += 1
            res = _run_leased_outbox_deletion(
                session=session,
                entry=entry,
                worker_id=effective_worker,
                storage_override=storage_override,
                lease_seconds=lease_seconds,
                renew_interval=renew_interval,
                operation_timeout_seconds=operation_timeout_seconds,
                timeout_grace_seconds=timeout_grace_seconds,
                worker_cancel_event=worker_cancel_event,
                use_subprocess=use_subprocess,
                subprocess_test_delay_seconds=subprocess_test_delay_seconds,
            )
            stats["renewals"] += int(res.get("renewals", 0))
            if res.get("subprocess_terminated"):
                stats["subprocess_terminated"] += 1
            outcome = res["outcome"]
            stats[outcome] = stats.get(outcome, 0) + 1

    if db is not None:
        _run(db)
    else:
        with get_db_context() as session:
            _run(session)
    return stats


def cleanup_orphaned_storage_objects(
    user_id: uuid.UUID,
    db: Session,
    storage_override=None,
) -> Dict[str, Any]:
    """
    User-isolated orphan garbage collection:
    Lists storage keys strictly under `users/{user_id}/`, identifies objects with no
    live Document or GeneratedImage reference, deletes them, and records audited outbox rows.
    """
    storage = storage_override or get_storage_backend()
    prefix = f"users/{user_id}/"
    stored_keys = storage.list_keys(prefix)

    referenced_doc_keys = {
        row[0]
        for row in db.query(Document.storage_key).filter(
            Document.user_id == user_id,
            Document.storage_key.isnot(None),
        ).all()
        if row[0]
    }
    referenced_img_keys = {
        row[0]
        for row in db.query(GeneratedImage.storage_key).filter(
            GeneratedImage.user_id == user_id,
            GeneratedImage.storage_key.isnot(None),
        ).all()
        if row[0]
    }
    live_keys = referenced_doc_keys | referenced_img_keys

    deleted_keys: List[str] = []
    failed_keys: List[str] = []
    now = utc_now()

    for key in stored_keys:
        norm_key = key.replace("\\", "/").lstrip("/")
        if not norm_key.startswith(prefix):
            continue
        if norm_key in live_keys:
            continue

        ok = False
        err_msg = None
        try:
            ok = bool(storage.delete(norm_key))
            if not ok:
                err_msg = f"Failed to delete orphan key '{norm_key}'"
        except Exception as e:
            err_msg = str(e)

        outbox = StorageDeletionOutbox(
            id=uuid.uuid4(),
            user_id=user_id,
            document_id=None,
            storage_backend=storage.backend_type,
            storage_key=norm_key,
            status="COMPLETED" if ok else "PENDING",
            attempt_count=1,
            max_attempts=5,
            last_error=err_msg,
            completed_at=now if ok else None,
            next_retry_at=None if ok else now + timedelta(seconds=60),
            created_at=now,
            updated_at=now,
        )
        db.add(outbox)
        if ok:
            deleted_keys.append(norm_key)
        else:
            failed_keys.append(norm_key)

    db.commit()
    return {
        "user_id": str(user_id),
        "scanned": len(stored_keys),
        "orphans_deleted": len(deleted_keys),
        "orphans_failed": len(failed_keys),
        "deleted_keys": deleted_keys,
    }


def retry_indexing(doc_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> BackgroundTask:
    """
    Re-enqueues document indexing through durable BackgroundTask queue.
    """
    return enqueue_index(doc_id, user_id, db, force_reindex=True)


def get_document_content(doc_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
    """
    Reads text content safely from StorageBackend for preview.
    """
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
    content_bytes = None

    if doc.storage_key and storage.exists(doc.storage_key):
        try:
            content_bytes = storage.get_bytes(doc.storage_key)
        except Exception:
            pass

    if content_bytes is None and doc.storage_path and os.path.exists(doc.storage_path):
        try:
            safe_path = resolve_legacy_local_path(doc.storage_path)
            with open(safe_path, "rb") as f:
                content_bytes = f.read(500000)
        except Exception:
            pass

    if content_bytes is None:
        raise HTTPException(status_code=404, detail="Physical file missing from storage")

    category = (doc.metadata_json or {}).get("category", get_file_category(doc.mime_type, doc.filename))
    try:
        content_text = content_bytes[:500000].decode("utf-8", errors="replace")
        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "category": category,
            "content": content_text,
            "is_text": True
        }
    except Exception as e:
        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "category": category,
            "content": None,
            "is_text": False,
            "error": str(e)
        }
