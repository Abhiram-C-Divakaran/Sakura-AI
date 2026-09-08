"""
Sakura AI — Canonical File Upload & Durable Storage Service

Provides unified file stream saving with:
1. Strict filename sanitization against path traversal (os.path.basename)
2. Streaming size enforcement (max 50MB) with automatic cleanup on overflow
3. Pluggable StorageBackend persistence (LocalFilesystemStorage / S3CompatibleStorage)
4. Canonical storage keys: users/<user_id>/documents/<doc_id>/<filename>
5. Authoritative Document database record creation
"""
import os
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from database.models import Document, DocumentIndexingStatus
from services.storage import (
    get_storage_backend,
    build_document_storage_key,
    assert_user_storage_key
)

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def get_file_category(mime_type: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if mime_type.startswith("image/") or ext in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp"]:
        return "images"
    if ext in [".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".rs", ".go", ".cpp", ".c", ".java", ".sql", ".sh", ".yaml", ".yml", ".json"]:
        return "code"
    if ext in [".csv", ".tsv", ".xlsx", ".xls"] or mime_type in ["text/csv", "application/vnd.ms-excel"]:
        return "data"
    if mime_type in ["application/pdf", "text/plain", "text/markdown"] or ext in [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"]:
        return "documents"
    return "other"


async def save_uploaded_file(
    file: UploadFile,
    user_id: uuid.UUID,
    db: Session,
    auto_index: bool = True,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> Document:
    """
    Saves an uploaded file to durable storage backend (Local or S3) with size limits
    and user isolation, creating the authoritative Document record in the database.
    """
    clean_filename = os.path.basename(file.filename or "upload.bin")
    file_id = uuid.uuid4()
    storage_key = build_document_storage_key(user_id, file_id, clean_filename)
    assert_user_storage_key(user_id, storage_key)

    storage = get_storage_backend()
    mime_type = file.content_type or "application/octet-stream"

    # Stream file into temp buffer with hard size limit (max 1MB in RAM before spooling to disk)
    import tempfile
    spooled = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    bytes_read = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > MAX_UPLOAD_SIZE_BYTES:
                spooled.close()
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size of 50MB")
            spooled.write(chunk)
    except HTTPException:
        spooled.close()
        raise
    except Exception as e:
        spooled.close()
        raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {str(e)}")

    spooled.seek(0)
    try:
        put_result = storage.put(
            storage_key=storage_key,
            data=spooled,
            content_type=mime_type,
            user_id=user_id
        )
    except Exception as e:
        spooled.close()
        raise HTTPException(status_code=500, detail=f"Failed to write file to storage: {str(e)}")
    finally:
        spooled.close()

    category = get_file_category(mime_type, clean_filename)
    idx_status = DocumentIndexingStatus.QUEUED if auto_index else DocumentIndexingStatus.NOT_INDEXED

    meta = {
        "status": "PROCESSING" if auto_index else "READY",
        "indexing_status": "Queued" if auto_index else "Not indexed",
        "size": bytes_read,
        "category": category,
        "source": "upload",
        "is_knowledge_base": False,
        "modified_at": datetime.now(timezone.utc).isoformat(),
        "chunks": 0,
        "error": None
    }
    if extra_metadata:
        meta.update(extra_metadata)

    doc = Document(
        id=file_id,
        user_id=user_id,
        filename=clean_filename,
        mime_type=mime_type,
        storage_path=put_result.get("storage_path") or storage_key,
        storage_backend=put_result.get("storage_backend", storage.backend_type),
        storage_key=storage_key,
        storage_size=bytes_read,
        is_knowledge_base=False,
        indexing_status=idx_status,
        metadata_json=meta
    )
    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as e:
        db.rollback()
        # Compensate storage: delete orphaned object
        try:
            storage.delete(storage_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Database error saving document record: {str(e)}")

    return doc
