import os
import shutil
import uuid
import json
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, asc
from pydantic import BaseModel

from database.db import get_db, get_db_context
from database.models import User, Document, DocumentChunk
from auth.manager import AuthManager
from rag.ingestion.parser import DocumentParser
from rag.embeddings.manager import EmbeddingManager

router = APIRouter(prefix="/library", tags=["library"])

UPLOAD_DIR = "./uploaded_documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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

# Background worker for RAG ingestion
async def async_index_document(doc_id: uuid.UUID, user_id: uuid.UUID):
    from api.routes import ws_manager
    with get_db_context() as db:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        try:
            # Update status to Parsing
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Parsing", "status": "INDEXING"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {
                "type": "library_update",
                "action": "updated",
                "data": serialize_document(doc)
            })
            await asyncio.sleep(0.3)

            # Parse file
            parser = DocumentParser()
            raw_text = parser.parse_file(doc.storage_path, doc.mime_type)

            # Chunking
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Chunking"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {
                "type": "library_update",
                "action": "updated",
                "data": serialize_document(doc)
            })
            await asyncio.sleep(0.3)

            chunks = parser.get_chunks(raw_text)

            # Embedding
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Embedding"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {
                "type": "library_update",
                "action": "updated",
                "data": serialize_document(doc)
            })
            await asyncio.sleep(0.3)

            embed_mgr = EmbeddingManager()
            contents = [c["content"] for c in chunks]
            embeddings = embed_mgr.get_embeddings(contents)

            # Clean any old chunks first if re-indexing
            db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

            for i, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    embedding=embeddings[i],
                    metadata_json=chunk["metadata"]
                )
                db.add(db_chunk)

            # Ready
            doc.metadata_json = {
                **doc.metadata_json,
                "indexing_status": "Ready",
                "status": "READY",
                "is_knowledge_base": True,
                "chunks": len(chunks)
            }
            db.commit()
            await ws_manager.send_to_user(str(user_id), {
                "type": "library_update",
                "action": "updated",
                "data": serialize_document(doc)
            })

        except Exception as e:
            # Failed
            doc.metadata_json = {
                **doc.metadata_json,
                "indexing_status": "Failed",
                "status": "FAILED",
                "error": str(e)
            }
            db.commit()
            await ws_manager.send_to_user(str(user_id), {
                "type": "library_update",
                "action": "updated",
                "data": serialize_document(doc)
            })

def serialize_document(doc: Document) -> Dict[str, Any]:
    meta = doc.metadata_json or {}
    category = meta.get("category") or get_file_category(doc.mime_type, doc.filename)
    status_val = meta.get("status") or meta.get("indexing_status") or "READY"
    is_kb = meta.get("is_knowledge_base", meta.get("chunks", 0) > 0)
    
    return {
        "id": str(doc.id),
        "name": doc.filename,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "category": category,
        "source": meta.get("source", "upload"),
        "status": status_val,
        "size_bytes": meta.get("size", 0),
        "size": meta.get("size", 0),
        "is_knowledge_base": is_kb,
        "chunks": meta.get("chunks", 0),
        "created_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
        "modified_at": meta.get("modified_at", doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat()),
        "error": meta.get("error", None),
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
    """
    Returns the authenticated user's real stored files with search, category filtering, and sorting.
    """
    query = db.query(Document).filter(Document.user_id == current_user.id)

    # Search query
    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query = query.filter(Document.filename.ilike(search_term))

    # Fetch results
    docs = query.all()

    # Category filter based on validated MIME type & extension
    if category and category.lower() != "all":
        cat_lower = category.lower()
        docs = [d for d in docs if (d.metadata_json or {}).get("category", get_file_category(d.mime_type, d.filename)) == cat_lower]

    serialized = [serialize_document(d) for d in docs]

    # Sorting
    reverse = (order.lower() == "desc")
    if sort_by == "name":
        serialized.sort(key=lambda x: x["name"].lower(), reverse=reverse)
    elif sort_by == "size":
        serialized.sort(key=lambda x: x["size_bytes"], reverse=reverse)
    elif sort_by == "type":
        serialized.sort(key=lambda x: (x["category"], x["mime_type"]), reverse=reverse)
    else:  # modified
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
    """Reads raw text / code / CSV content for in-browser preview."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    if not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="Physical file missing from storage")

    category = (doc.metadata_json or {}).get("category", get_file_category(doc.mime_type, doc.filename))
    
    # Read text content
    try:
        with open(doc.storage_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(500000)  # Max 500KB preview
        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "category": category,
            "content": content,
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
    """Streams physical file for download with strict ownership validation."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    current_user = authenticate_user_from_req(token, from_fastapi_req.headers, db)

    # 1. Check Document table owned by this user
    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if doc and os.path.exists(doc.storage_path):
        return FileResponse(
            path=doc.storage_path,
            media_type=doc.mime_type or "application/octet-stream",
            filename=doc.filename
        )

    # 2. Check GeneratedImage table owned by this user
    from database.models import GeneratedImage
    gen_img = db.query(GeneratedImage).filter(GeneratedImage.id == doc_uuid, GeneratedImage.user_id == current_user.id).first()
    if gen_img and os.path.exists(gen_img.storage_path):
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
    if not doc or not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="File not found or access denied")

    return FileResponse(path=doc.storage_path, media_type=doc.mime_type)

@router.post("/upload")
async def upload_library_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auto_index: bool = Form(True),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Uploads a real file to object storage, creates database record, 
    and triggers background RAG indexing if enabled. Enforces max size and path safety.
    """
    # Sanitize filename against directory traversal
    clean_filename = os.path.basename(file.filename or "upload.bin")
    file_id = uuid.uuid4()
    extension = os.path.splitext(clean_filename)[1]
    storage_path = os.path.join(UPLOAD_DIR, f"{file_id}{extension}")

    # Enforce 50MB file size limit
    max_size_bytes = 50 * 1024 * 1024
    bytes_read = 0
    with open(storage_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_size_bytes:
                buffer.close()
                if os.path.exists(storage_path):
                    os.remove(storage_path)
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size of 50MB")
            buffer.write(chunk)

    file_size = bytes_read
    mime_type = file.content_type or "application/octet-stream"
    category = get_file_category(mime_type, clean_filename)

    doc = Document(
        id=file_id,
        user_id=current_user.id,
        filename=clean_filename,
        mime_type=mime_type,
        storage_path=storage_path,
        metadata_json={
            "status": "PROCESSING" if auto_index else "READY",
            "indexing_status": "Uploaded" if auto_index else "Ready",
            "size": file_size,
            "category": category,
            "source": "upload",
            "is_knowledge_base": False,
            "modified_at": datetime.now(timezone.utc).isoformat(),
            "chunks": 0,
            "error": None
        }
    )
    db.add(doc)
    db.commit()

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "created",
        "data": serialized
    })

    if auto_index and category in ["documents", "code", "data"]:
        background_tasks.add_task(async_index_document, doc.id, current_user.id)

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
    """Creates a real text / code / markdown file from editor content."""
    clean_name = req.filename.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    file_id = uuid.uuid4()
    ext = os.path.splitext(clean_name)[1] or ".txt"
    storage_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")

    with open(storage_path, "w", encoding="utf-8") as f:
        f.write(req.content)

    file_size = os.path.getsize(storage_path)
    mime_type = "text/markdown" if ext == ".md" else ("text/x-python" if ext == ".py" else "text/plain")
    category = req.category or get_file_category(mime_type, clean_name)

    doc = Document(
        id=file_id,
        user_id=current_user.id,
        filename=clean_name,
        mime_type=mime_type,
        storage_path=storage_path,
        metadata_json={
            "status": "READY",
            "indexing_status": "Ready",
            "size": file_size,
            "category": category,
            "source": "ai_document",
            "is_knowledge_base": True,
            "modified_at": datetime.utcnow().isoformat(),
            "chunks": 1,
            "error": None
        }
    )
    db.add(doc)
    db.commit()

    # Index document chunk
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
    """Generates an image via neural rendering and saves it as a real library file."""
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Image prompt cannot be empty")

    file_id = uuid.uuid4()
    clean_title = req.filename or prompt[:30].replace(" ", "_").replace("/", "_") + ".png"
    storage_path = os.path.join(UPLOAD_DIR, f"{file_id}.png")

    encoded_prompt = urllib.parse.quote(prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed=42"

    def download_image():
        req_obj = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_obj, timeout=20) as resp:
            with open(storage_path, "wb") as out:
                out.write(resp.read())

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, download_image)
        file_size = os.path.getsize(storage_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

    doc = Document(
        id=file_id,
        user_id=current_user.id,
        filename=clean_title,
        mime_type="image/png",
        storage_path=storage_path,
        metadata_json={
            "status": "READY",
            "indexing_status": "Ready",
            "size": file_size,
            "category": "images",
            "source": "image_generation",
            "prompt": prompt,
            "is_knowledge_base": False,
            "modified_at": datetime.utcnow().isoformat(),
            "chunks": 0
        }
    )
    db.add(doc)
    db.commit()

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "created",
        "data": serialized
    })

    return {"status": "success", "file": serialized}

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
        "modified_at": datetime.utcnow().isoformat()
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

    # Delete physical file
    if os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass

    # Delete DB records
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Indexes or re-indexes a library file for AI retrieval."""
    try:
        doc_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "status": "PROCESSING",
        "indexing_status": "Uploaded",
        "error": None
    }
    db.commit()

    background_tasks.add_task(async_index_document, doc.id, current_user.id)
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
    doc.metadata_json = {
        **(doc.metadata_json or {}),
        "is_knowledge_base": False,
        "chunks": 0,
        "indexing_status": "Not indexed"
    }
    db.commit()

    from api.routes import ws_manager
    serialized = serialize_document(doc)
    await ws_manager.send_to_user(str(current_user.id), {
        "type": "library_update",
        "action": "updated",
        "data": serialized
    })

    return {"status": "removed_from_knowledge_base", "file": serialized}
