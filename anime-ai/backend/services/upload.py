"""
Sakura AI — Canonical File Upload & Storage Service

Provides unified file stream saving with:
1. Strict filename sanitization against path traversal (os.path.basename)
2. Streaming size enforcement (max 50MB) with automatic cleanup on overflow
3. Accurate MIME detection and categorizing
4. Atomic Document creation and persistence
"""
import os
import uuid
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from database.models import Document, User

UPLOAD_DIR = "./uploaded_documents"
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)

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
    Saves an uploaded file to storage with size limit and directory traversal guard,
    and creates the database Document record.
    """
    clean_filename = os.path.basename(file.filename or "upload.bin")
    file_id = uuid.uuid4()
    extension = os.path.splitext(clean_filename)[1]
    storage_path = os.path.join(UPLOAD_DIR, f"{file_id}{extension}")

    bytes_read = 0
    try:
        with open(storage_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > MAX_UPLOAD_SIZE_BYTES:
                    buffer.close()
                    if os.path.exists(storage_path):
                        os.remove(storage_path)
                    raise HTTPException(status_code=413, detail="File exceeds maximum allowed size of 50MB")
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(storage_path):
            os.remove(storage_path)
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    mime_type = file.content_type or "application/octet-stream"
    category = get_file_category(mime_type, clean_filename)

    meta = {
        "status": "PROCESSING" if auto_index else "READY",
        "indexing_status": "Uploaded" if auto_index else "Ready",
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
        storage_path=storage_path,
        metadata_json=meta
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
