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


def serialize_document(doc: Document) -> Dict[str, Any]:
    """
    Serializes Document reading canonical DB fields as authoritative sources of truth.
    """
    meta = doc.metadata_json or {}
    category = meta.get("category") or get_file_category(doc.mime_type, doc.filename)

    is_kb = bool(doc.is_knowledge_base)
    idx_status = doc.indexing_status or DocumentIndexingStatus.NOT_INDEXED
    size_bytes = doc.storage_size if doc.storage_size is not None else meta.get("size", 0)

    return {
        "id": str(doc.id),
        "name": doc.filename,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "category": category,
        "source": meta.get("source", "upload"),
        "status": idx_status,
        "indexing_status": idx_status,
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
) -> tuple[bool, Optional[str]]:
    """
    Deletes an object from StorageBackend (and legacy local path if distinct).
    Returns (True, None) ONLY when deletion is verified successful or object no longer exists.
    Returns (False, error_message) on any storage error.
    """
    storage = storage_override or get_storage_backend(storage_backend_name or "local")
    if storage_key:
        try:
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


def delete_document(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
    *,
    storage_override=None,
    raise_on_storage_error: bool = True,
) -> Dict[str, Any]:
    """
    Durable outbox-backed document deletion lifecycle:
    1. Transaction 1: Verify ownership, bump index_generation, cancel any queued/running
       document_index BackgroundTasks, mark doc.deletion_status='DELETING', and persist
       (or reuse) a PENDING StorageDeletionOutbox record.
    2. Physical deletion: Attempt storage object deletion (never touching DB deletion first).
    3. Transaction 2:
       - On storage success: delete linked GeneratedImage, Document (and chunks), mark outbox COMPLETED.
       - On storage failure: keep Document row intact with deletion_status='DELETE_FAILED',
         record error + retry backoff on outbox (never silently drop DB row while object remains!).
    """
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    now = utc_now()
    backend_name = getattr(doc, "storage_backend", "local") or "local"
    storage_key = doc.storage_key
    legacy_path = doc.storage_path if (doc.storage_path and doc.storage_path != storage_key) else None

    # Step 1: Record durable deletion intent & cancel in-flight indexing atomically
    doc.index_generation = (getattr(doc, "index_generation", 0) or 0) + 1
    doc.is_knowledge_base = False
    doc.deletion_status = "DELETING"

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

    # Idempotent repeated deletion: reuse existing non-completed outbox row for this document
    inline_claim_token = uuid.uuid4()
    inline_lease_exp = now + timedelta(seconds=OUTBOX_LEASE_DURATION_SECONDS)
    outbox = db.query(StorageDeletionOutbox).filter(
        StorageDeletionOutbox.document_id == doc.id,
        StorageDeletionOutbox.status != "COMPLETED",
    ).first()
    if not outbox:
        outbox = StorageDeletionOutbox(
            id=uuid.uuid4(),
            user_id=user_id,
            document_id=doc.id,
            storage_backend=backend_name,
            storage_key=storage_key or (legacy_path or f"document:{doc.id}"),
            legacy_path=legacy_path,
            status="PROCESSING",
            worker_id="api_sync",
            claim_token=inline_claim_token,
            claimed_at=now,
            lease_expires_at=inline_lease_exp,
            attempt_count=0,
            max_attempts=5,
            next_retry_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(outbox)
    else:
        outbox.status = "PROCESSING"
        outbox.worker_id = "api_sync"
        outbox.claim_token = inline_claim_token
        outbox.claimed_at = now
        outbox.lease_expires_at = inline_lease_exp
        outbox.next_retry_at = now
        outbox.updated_at = now

    # Commit intent BEFORE touching physical storage (if DB fails here, object stays untouched)
    db.commit()
    db.refresh(outbox)
    outbox_id = outbox.id

    # Step 2: Execute physical object deletion
    ok, err_msg = _delete_physical_object(
        storage_backend_name=backend_name,
        storage_key=storage_key,
        legacy_path=legacy_path,
        storage_override=storage_override,
    )

    done_at = utc_now()
    if not ok:
        # Storage deletion FAILED: preserve Document row in DB with honest DELETE_FAILED status
        outbox_rec = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).first()
        doc_rec = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
        if outbox_rec:
            outbox_rec.attempt_count = int(outbox_rec.attempt_count or 0) + 1
            outbox_rec.last_error = err_msg
            outbox_rec.worker_id = None
            outbox_rec.claim_token = None
            outbox_rec.claimed_at = None
            outbox_rec.lease_expires_at = None
            outbox_rec.updated_at = done_at
            if outbox_rec.attempt_count >= int(outbox_rec.max_attempts or 5):
                outbox_rec.status = "FAILED"
                outbox_rec.next_retry_at = None
            else:
                backoff_secs = min(60 * (2 ** (outbox_rec.attempt_count - 1)), 3600)
                outbox_rec.status = "PENDING"
                outbox_rec.next_retry_at = done_at + timedelta(seconds=backoff_secs)
        if doc_rec:
            doc_rec.deletion_status = "DELETE_FAILED"
            doc_rec.metadata_json = {**(doc_rec.metadata_json or {}), "deletion_error": err_msg}
        db.commit()

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

    # Step 3: Storage deletion succeeded -> finalize DB deletion + outbox COMPLETED atomically
    try:
        db.query(GeneratedImage).filter(
            GeneratedImage.document_id == doc_id,
            GeneratedImage.user_id == user_id,
        ).delete(synchronize_session=False)

        doc_rec = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
        if doc_rec:
            db.delete(doc_rec)

        outbox_rec = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == outbox_id).first()
        if outbox_rec:
            outbox_rec.attempt_count = int(outbox_rec.attempt_count or 0) + 1
            outbox_rec.status = "COMPLETED"
            outbox_rec.last_error = None
            outbox_rec.worker_id = None
            outbox_rec.claim_token = None
            outbox_rec.lease_expires_at = None
            outbox_rec.completed_at = done_at
            outbox_rec.updated_at = done_at
            outbox_rec.next_retry_at = None

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "deleted",
        "deletion_status": "COMPLETED",
        "outbox_id": str(outbox_id),
        "cancelled_index_tasks": cancelled_tasks,
    }


OUTBOX_LEASE_DURATION_SECONDS = 120


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
                row.worker_id,
                row.claim_token,
                int(row.attempt_count or 0),
                int(row.max_attempts or 5),
                row.last_error,
            )
            for row in stale
        ]
        recovered = 0
        for oid, old_worker, old_token, attempts, max_att, prev_err in snaps:
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
            if attempts >= max_att:
                rows = session.query(StorageDeletionOutbox).filter(*filters).update(
                    {
                        StorageDeletionOutbox.status: "FAILED",
                        StorageDeletionOutbox.worker_id: None,
                        StorageDeletionOutbox.claim_token: None,
                        StorageDeletionOutbox.claimed_at: None,
                        StorageDeletionOutbox.lease_expires_at: None,
                        StorageDeletionOutbox.next_retry_at: None,
                        StorageDeletionOutbox.last_error: prev_err or "Outbox lease expired after max attempts.",
                        StorageDeletionOutbox.updated_at: now,
                    },
                    synchronize_session=False,
                )
                session.commit() if rows == 1 else session.rollback()
            else:
                rows = session.query(StorageDeletionOutbox).filter(*filters).update(
                    {
                        StorageDeletionOutbox.status: "PENDING",
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


def _execute_outbox_physical_deletion(entry: Dict[str, Any], storage_override=None) -> tuple[bool, Optional[str]]:
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
        )

    return _delete_physical_object(
        storage_backend_name=backend,
        storage_key=skey if not skey.startswith("document:") else None,
        legacy_path=lpath,
        storage_override=storage_override,
    )


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
    session.commit()
    return outcome


def process_storage_deletion_outbox(
    db: Optional[Session] = None,
    limit: int = 50,
    storage_override=None,
    worker_id: Optional[str] = None,
    lease_seconds: float = OUTBOX_LEASE_DURATION_SECONDS,
    renew_interval: Optional[float] = None,
    operation_timeout_seconds: float = 300.0,
) -> Dict[str, int]:
    """
    Multi-worker-safe processor for StorageDeletionOutbox:
    1. Recovers any stale PROCESSING claims whose leases expired.
    2. Atomically claims due PENDING rows with worker_id + claim_token + lease_expires_at.
    3. Executes physical deletion outside DB row locks while renewing the lease periodically
       on the main thread for long-running deletions (bounded by operation_timeout_seconds).
    4. Fences every completion/retry/failure update by (id, PROCESSING, worker_id, claim_token,
       unexpired lease) so expired or displaced workers never write DB state.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

    effective_worker = worker_id or f"outbox_worker_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    effective_lease = max(0.2, float(lease_seconds))
    effective_renew = float(renew_interval) if renew_interval is not None else max(0.05, effective_lease * 0.4)
    effective_timeout = max(effective_lease, float(operation_timeout_seconds))
    stats = {"recovered": 0, "processed": 0, "completed": 0, "retried": 0, "failed": 0, "stale": 0, "renewals": 0}

    def _run(session: Session):
        stats["recovered"] = recover_stale_outbox_claims(session)
        # Claim entries one-by-one up to `limit` so a slow deletion never causes
        # head-of-line lease expiration on subsequent entries and multiple workers
        # load-balance naturally.
        for _ in range(max(0, int(limit))):
            claimed = claim_storage_deletion_outbox_entries(
                session=session,
                worker_id=effective_worker,
                limit=1,
                lease_seconds=effective_lease,
            )
            if not claimed:
                break
            entry = claimed[0]
            stats["processed"] += 1
            start_mono = time.monotonic()
            last_renew_mono = start_mono
            lease_lost = False
            ok = False
            err_msg: Optional[str] = None

            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(_execute_outbox_physical_deletion, entry, storage_override)
            try:
                while True:
                    remaining_timeout = effective_timeout - (time.monotonic() - start_mono)
                    if remaining_timeout <= 0:
                        err_msg = f"Storage deletion operation timed out after {effective_timeout:.1f}s"
                        ok = False
                        break
                    wait_slice = min(effective_renew, remaining_timeout)
                    try:
                        ok, err_msg = future.result(timeout=wait_slice)
                        break
                    except FutureTimeoutError:
                        now_mono = time.monotonic()
                        if now_mono - last_renew_mono >= effective_renew * 0.9:
                            renewed = renew_outbox_claim_lease(
                                session=session,
                                entry_id=entry["id"],
                                worker_id=effective_worker,
                                claim_token=entry["claim_token"],
                                lease_seconds=effective_lease,
                            )
                            if not renewed:
                                lease_lost = True
                                break
                            stats["renewals"] += 1
                            last_renew_mono = now_mono
            finally:
                pool.shutdown(wait=False)

            if lease_lost:
                stats["stale"] += 1
                continue

            outcome = finalize_claimed_outbox_entry(session, entry, effective_worker, ok, err_msg)
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
