import os
import shutil
import uuid
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.db import get_db, get_db_context
from database.models import User, Document, DocumentChunk, DocumentIndexingStatus, GeneratedImage
from auth.manager import AuthManager
from services.storage import (
    get_storage_backend,
    build_document_storage_key,
    build_image_storage_key,
    assert_user_storage_key,
)

router = APIRouter(prefix="/library", tags=["library"])


# Helper to categorize MIME types & extensions
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


def serialize_document(doc: Document) -> Dict[str, Any]:
    """
    Serializes Document reading canonical DB fields (Document.is_knowledge_base and Document.indexing_status)
    as authoritative sources of truth.
    """
    meta = doc.metadata_json or {}
    category = meta.get("category") or get_file_category(doc.mime_type, doc.filename)

    # Real database fields are authoritative
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
        "chunks": meta.get("chunks", 0),
        "created_at": doc.created_at.isoformat() if doc.created_at else datetime.now(timezone.utc).isoformat(),
        "modified_at": meta.get("modified_at", doc.created_at.isoformat() if doc.created_at else datetime.now(timezone.utc).isoformat()),
        "error": meta.get("error", None),
        "storage_backend": getattr(doc, "storage_backend", "local") or "local",
        "storage_key": getattr(doc, "storage_key", None),
        "metadata": meta
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/files", response_model=List[Dict[str, Any]])
def list_library_files(
    category: Optional[str] = Query("all"),
    q: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("modified"),
    order: Optional[str] = Query("desc"),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Returns the authenticated user's real stored files with search, category filtering, and sorting."""
    query = db.query(Document).filter(Document.user_id == current_user.id)

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query = query.filter(Document.filename.ilike(search_term))

    docs = query.all()

    if category and category.lower() != "all":
        cat_lower = category.lower()
        docs = [d for d in docs if (d.metadata_json or {}).get("category", get_file_category(d.mime_type, d.filename)) == cat_lower]

    serialized = [serialize_document(d) for d in docs]

    reverse = (order.lower() == "desc")
    if sort_by == "name":
        serialized.sort(key=lambda x: x["name"].lower(), reverse=reverse)
    elif sort_by == "size":
        serialized.sort(key=lambda x: x["size_bytes"], reverse=reverse)
    elif sort_by == "type":
        serialized.sort(key=lambda x: (x["category"], x["mime_type"]), reverse=reverse)
    else:
        serialized.sort(key=lambda x: x["modified_at"], reverse=reverse)

    return serialized


@router.get("/files/{file_id}")
def get_library_file(
    file_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches full metadata and details for a single real file."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found in your library")

    return serialize_document(doc)


@router.get("/files/{file_id}/content")
def get_library_file_content(
    file_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Reads raw text / code / CSV content for in-browser preview from durable storage backend."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
    content_bytes = None

    if doc.storage_key and storage.exists(doc.storage_key):
        try:
            content_bytes = storage.get_bytes(doc.storage_key)
        except Exception:
            pass

    if content_bytes is None and doc.storage_path and os.path.exists(doc.storage_path):
        try:
            with open(doc.storage_path, "rb") as f:
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


def authenticate_user_from_req(token: Optional[str], req_headers: Any, db: Session) -> User:
    """Extracts and verifies user from query token or Authorization header."""
    raw_token = token
    auth_header = req_headers.get("authorization") if hasattr(req_headers, "get") else None
    if not raw_token and auth_header and auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()

    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication credentials required")

    try:
        payload = AuthManager.decode_token(raw_token)
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired authentication token")


@router.get("/files/{file_id}/download")
def download_library_file(
    file_id: str,
    from_fastapi_req: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Streams physical file for download with strict ownership validation from StorageBackend."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    current_user = authenticate_user_from_req(token, from_fastapi_req.headers, db)

    # 1. Check Document table owned by this user
    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if doc:
        storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
        if doc.storage_key and storage.exists(doc.storage_key):
            return storage.generate_download_response(doc.storage_key, doc.filename, doc.mime_type)
        if doc.storage_path and os.path.exists(doc.storage_path):
            return FileResponse(
                path=doc.storage_path,
                media_type=doc.mime_type or "application/octet-stream",
                filename=doc.filename
            )

    # 2. Check GeneratedImage table owned by this user
    gen_img = db.query(GeneratedImage).filter(GeneratedImage.id == doc_uuid, GeneratedImage.user_id == current_user.id).first()
    if gen_img:
        storage = get_storage_backend(getattr(gen_img, "storage_backend", "local"))
        if getattr(gen_img, "storage_key", None) and storage.exists(gen_img.storage_key):
            return storage.generate_download_response(gen_img.storage_key, f"image_{file_id[:8]}.png", "image/png")
        if gen_img.storage_path and os.path.exists(gen_img.storage_path):
            return FileResponse(
                path=gen_img.storage_path,
                media_type="image/png",
                filename=f"image_{file_id[:8]}.png"
            )

    raise HTTPException(status_code=404, detail="File not found in storage or access denied")


@router.get("/files/{file_id}/thumbnail")
def get_library_file_thumbnail(
    file_id: str,
    from_fastapi_req: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Serves thumbnail or direct image preview with strict ownership validation."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    current_user = authenticate_user_from_req(token, from_fastapi_req.headers, db)

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if doc:
        storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
        if doc.storage_key and storage.exists(doc.storage_key):
            return storage.generate_download_response(doc.storage_key, doc.filename, doc.mime_type)
        if doc.storage_path and os.path.exists(doc.storage_path):
            return FileResponse(path=doc.storage_path, media_type=doc.mime_type)

    gen_img = db.query(GeneratedImage).filter(GeneratedImage.id == doc_uuid, GeneratedImage.user_id == current_user.id).first()
    if gen_img:
        storage = get_storage_backend(getattr(gen_img, "storage_backend", "local"))
        if getattr(gen_img, "storage_key", None) and storage.exists(gen_img.storage_key):
            return storage.generate_download_response(gen_img.storage_key, f"image_{file_id[:8]}.png", "image/png")
        if gen_img.storage_path and os.path.exists(gen_img.storage_path):
            return FileResponse(path=gen_img.storage_path, media_type="image/png")

    raise HTTPException(status_code=404, detail="File not found or access denied")


@router.post("/upload")
async def upload_library_file(
    file: UploadFile = File(...),
    auto_index: bool = Form(True),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from services.upload import save_uploaded_file
    doc = await save_uploaded_file(
        file=file,
        user_id=current_user.id,
        db=db,
        auto_index=auto_index
    )

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "created",
        "data": serialized
    })

    category = (doc.metadata_json or {}).get("category", "")
    if auto_index and category in ["documents", "code", "data"]:
        from tasks.task_manager import TaskManager
        TaskManager.create_task(
            user_id=current_user.id,
            task_type="document_index",
            title=f"Index {doc.filename}",
            payload={
                "document_id": str(doc.id),
                "requested_by_user_id": str(current_user.id),
                "force_reindex": False
            }
        )

    return {"status": "success", "file": serialized}


class CreateDocumentRequest(BaseModel):
    filename: str
    content: str
    category: Optional[str] = "documents"


@router.post("/create-document")
async def create_document(
    req: CreateDocumentRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a real text / code / markdown file from editor content stored in StorageBackend."""
    clean_name = req.filename.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    file_id = uuid.uuid4()
    ext = os.path.splitext(clean_name)[1] or ".txt"
    mime_type = "text/markdown" if ext == ".md" else ("text/x-python" if ext == ".py" else "text/plain")
    category = req.category or get_file_category(mime_type, clean_name)

    storage = get_storage_backend()
    storage_key = build_document_storage_key(current_user.id, file_id, clean_name)
    content_bytes = req.content.encode("utf-8")
    put_res = storage.put(storage_key, content_bytes, content_type=mime_type, user_id=current_user.id)
    file_size = len(content_bytes)

    doc = Document(
        id=file_id,
        user_id=current_user.id,
        filename=clean_name,
        mime_type=mime_type,
        storage_path=put_res.get("storage_path") or storage_key,
        storage_backend=put_res.get("storage_backend", storage.backend_type),
        storage_key=storage_key,
        storage_size=file_size,
        is_knowledge_base=True,
        indexing_status=DocumentIndexingStatus.READY,
        metadata_json={
            "status": "READY",
            "indexing_status": "Ready",
            "size": file_size,
            "category": category,
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
        content=req.content,
        metadata_json={"source": clean_name}
    )
    db.add(chunk)
    db.commit()

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "created",
        "data": serialized
    })

    return {"status": "success", "file": serialized}


class GenerateImageRequest(BaseModel):
    prompt: str
    filename: Optional[str] = None


@router.post("/generate-image")
async def generate_image_to_library(
    req: GenerateImageRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Generates an image via canonical ImageGenerationEngine and saves it as a real library file."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Image prompt cannot be empty")

    from media.image_engine import ImageGenerationEngine
    engine = ImageGenerationEngine(db, current_user.id)
    try:
        res = await engine.generate_image(
            prompt=prompt,
            aspect_ratio="1:1"
        )
        return {"status": "success", "file": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


class RenameFileRequest(BaseModel):
    name: str


@router.patch("/files/{file_id}")
async def rename_library_file(
    file_id: str,
    req: RenameFileRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Renames file and updates modified timestamp."""
    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    doc.filename = new_name
    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "modified_at": datetime.now(timezone.utc).isoformat()
    }
    db.commit()

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "updated",
        "data": serialized
    })

    return {"status": "success", "file": serialized}


@router.delete("/files/{file_id}")
async def delete_library_file(
    file_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes real file from storage and database."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete physical file from storage backend
    storage = get_storage_backend(getattr(doc, "storage_backend", "local"))
    if doc.storage_key:
        storage.delete(doc.storage_key)
    if doc.storage_path and os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass

    db.delete(doc)
    db.commit()

    from api.routes import ws_manager
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "deleted",
        "data": {"id": file_id}
    })

    return {"status": "deleted", "id": file_id}


@router.post("/files/{file_id}/index")
async def add_file_to_knowledge_base(
    file_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Indexes or re-indexes a library file for AI retrieval using durable worker queue."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    doc.is_knowledge_base = False
    doc.indexing_status = DocumentIndexingStatus.QUEUED
    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "status": "QUEUED",
        "indexing_status": "Queued",
        "error": None
    }
    db.commit()

    from tasks.task_manager import TaskManager
    TaskManager.create_task(
        user_id=current_user.id,
        task_type="document_index",
        title=f"Index {doc.filename}",
        payload={
            "document_id": str(doc.id),
            "requested_by_user_id": str(current_user.id),
            "force_reindex": True
        }
    )

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "updated",
        "data": serialized
    })

    return {"status": "indexing_started", "id": file_id}


@router.delete("/files/{file_id}/index")
async def remove_file_from_knowledge_base(
    file_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Removes file embeddings from knowledge base without deleting the physical library file."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
    doc.is_knowledge_base = False
    doc.indexing_status = DocumentIndexingStatus.NOT_INDEXED
    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "is_knowledge_base": False,
        "chunks": 0,
        "indexing_status": "Not indexed",
        "status": "READY"
    }
    db.commit()
    db.refresh(doc)

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "updated",
        "data": serialized
    })

    return {"status": "removed_from_knowledge_base", "file": serialized}
