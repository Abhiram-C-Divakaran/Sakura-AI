"""
Sakura AI — Consolidated Document & Knowledge Base Service Layer
Provides canonical business logic for document lifecycle, RAG indexing,
storage persistence, and generation fencing across all API modules.
"""

import os
import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from database.models import (
    Document,
    DocumentChunk,
    DocumentIndexingStatus,
    BackgroundTask,
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

    return doc


def enqueue_index(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
    force_reindex: bool = False
) -> BackgroundTask:
    """
    Atomically increments Document.index_generation and enqueues durable document_index BackgroundTask.
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
    db.commit()
    db.refresh(doc)

    from tasks.task_manager import TaskManager
    task = TaskManager.create_task(
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


def delete_document(doc_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> bool:
    """
    Deletes document from database and StorageBackend.
    """
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
    if doc.storage_key:
        try:
            storage.delete(doc.storage_key)
        except Exception as e:
            logger.warning(f"Failed to delete storage key '{doc.storage_key}': {e}")

    if doc.storage_path and os.path.exists(doc.storage_path):
        try:
            safe_path = resolve_legacy_local_path(doc.storage_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
        except Exception as e:
            logger.warning(f"Failed to remove legacy storage path '{doc.storage_path}': {e}")

    # Delete related tasks
    tasks = db.query(BackgroundTask).filter(BackgroundTask.user_id == user_id, BackgroundTask.type == "document_index").all()
    for t in tasks:
        if (t.payload or {}).get("document_id") == str(doc.id):
            db.delete(t)

    db.delete(doc)
    db.commit()
    return True


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
