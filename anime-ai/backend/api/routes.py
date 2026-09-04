import os
import shutil
import uuid
import json
import psutil
import time
import asyncio
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.db import get_db
from database.models import (
    User, Document, DocumentChunk, Conversation, Message, UserMemory, Character, GeneratedImage,
    MessageFeedback, ConversationShare
)
from auth.manager import AuthManager
from rag.ingestion.parser import DocumentParser
from rag.embeddings.manager import EmbeddingManager
from rag.retrieval import HybridRetriever
from memory.manager import MemoryManager
from characters.engine import CharacterEngine
from llm.router import LLMRouter
from api.audio import router as audio_router
from api.library import router as library_router
from api.coding import router as coding_router
from api.projects import router as projects_router
from api.scheduled import router as scheduled_router
from api.integrations import router as integrations_router

# Import NLP classifiers
from ml_pipeline import SentimentAnalyzer, IntentClassifier

# Global telemetry & connection variables
START_TIME = time.time()
LATENCY_SAMPLES = []
current_context_used_by_user = {}
tokens_per_second_by_user = {}
user_tokens_count = __import__("collections").defaultdict(int)
ACTIVE_TASKS = {}
RUNNING_TASKS = {}

class ConnectionManager:
    def __init__(self):
        self.user_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def send_to_user(self, user_id: str, message: dict):
        if user_id in self.user_connections:
            for connection in self.user_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

ws_manager = ConnectionManager()

router = APIRouter(prefix="/api/v1")
router.include_router(audio_router)
router.include_router(library_router)
router.include_router(coding_router)
router.include_router(projects_router)
router.include_router(scheduled_router)
router.include_router(integrations_router)

# Initialize shared components
llm_router = LLMRouter()
sentiment_analyzer = SentimentAnalyzer()
intent_classifier = IntentClassifier()

# Pydantic Schemas
class UserRegister(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    intensity: Optional[str] = "medium"
    tools: Optional[List[str]] = []
    attachments: Optional[List[Dict[str, Any]]] = []


# ─── Auth Endpoints ─────────────────────────────────────────────────────────

@router.post("/auth/register", response_model=Dict[str, str])
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    new_user = User(
        username=user_data.username,
        hashed_password=AuthManager.hash_password(user_data.password)
    )
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}

@router.post("/auth/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not AuthManager.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token = AuthManager.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


# ─── Conversation Endpoints ──────────────────────────────────────────────────

def serialize_conversation(c: Conversation) -> Dict[str, Any]:
    return {
        "id": str(c.id),
        "title": c.title,
        "character_id": c.character_id,
        "pinned": bool(c.pinned),
        "pinned_at": c.pinned_at.isoformat() if c.pinned_at else None,
        "archived_at": c.archived_at.isoformat() if c.archived_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None
    }

@router.get("/conversations", response_model=List[Dict[str, Any]])
def list_conversations(current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    convs = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.archived_at.is_(None)
    ).order_by(Conversation.updated_at.desc()).all()
    return [serialize_conversation(c) for c in convs]

@router.post("/conversations", response_model=Dict[str, Any])
async def create_conversation(character_id: str = "sakura", current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    conv = Conversation(user_id=current_user.id, character_id=character_id, title=f"Chat with {character_id.capitalize()}")
    db.add(conv)
    db.commit()
    data = serialize_conversation(conv)
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_created", "data": data})
    return data

@router.post("/conversations/{conversation_id}/pin")
async def pin_conversation(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.pinned = True
    conv.pinned_at = datetime.utcnow()
    db.commit()
    data = serialize_conversation(conv)
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_updated", "action": "pinned", "data": data})
    return data

@router.post("/conversations/{conversation_id}/unpin")
async def unpin_conversation(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.pinned = False
    conv.pinned_at = None
    db.commit()
    data = serialize_conversation(conv)
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_updated", "action": "unpinned", "data": data})
    return data

@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.archived_at = datetime.utcnow()
    db.commit()
    data = serialize_conversation(conv)
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_updated", "action": "archived", "data": data})
    return data

@router.get("/conversations/search")
def search_conversations(
    q: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    query_str = q.strip()
    if not query_str:
        return []
    
    title_matches = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.title.ilike(f"%{query_str}%")
    ).limit(10).all()
    
    message_matches = db.query(Message, Conversation).join(
        Conversation, Message.conversation_id == Conversation.id
    ).filter(
        Conversation.user_id == current_user.id,
        Message.content.ilike(f"%{query_str}%")
    ).order_by(Message.created_at.desc()).limit(20).all()
    
    seen_convs = set()
    results = []
    
    for c in title_matches:
        if c.id not in seen_convs:
            seen_convs.add(c.id)
            results.append({
                "conversation_id": str(c.id),
                "title": c.title,
                "match_type": "title",
                "snippet": c.title,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None
            })
            
    for m, c in message_matches:
        if c.id not in seen_convs:
            seen_convs.add(c.id)
            content = m.content or ""
            idx = content.lower().find(query_str.lower())
            start = max(0, idx - 40)
            end = min(len(content), idx + len(query_str) + 40)
            snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
            
            results.append({
                "conversation_id": str(c.id),
                "title": c.title,
                "match_type": "message",
                "snippet": snippet,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None
            })
            
    return results

@router.post("/conversations/{conversation_id}/share")
async def share_conversation(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    existing_share = db.query(ConversationShare).filter(
        ConversationShare.conversation_id == conv.id,
        ConversationShare.is_active == True
    ).first()
    
    if existing_share:
        share_token = existing_share.share_token
    else:
        share_token = secrets.token_urlsafe(16)
        share = ConversationShare(
            conversation_id=conv.id,
            user_id=current_user.id,
            share_token=share_token,
            is_active=True
        )
        db.add(share)
        db.commit()

    share_url = f"/share/{share_token}"
    return {
        "status": "shared",
        "conversation_id": str(conv.id),
        "share_token": share_token,
        "title": conv.title,
        "share_url": share_url
    }

@router.get("/share/{token}")
def get_shared_conversation(token: str, db: Session = Depends(get_db)):
    share = db.query(ConversationShare).filter(
        ConversationShare.share_token == token,
        ConversationShare.is_active == True
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Shared conversation not found or expired")
    
    conv = db.query(Conversation).filter(Conversation.id == share.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.asc()).all()
    return {
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "character_id": conv.character_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None
            } for m in messages
        ]
    }

@router.delete("/share/{token}")
def revoke_shared_conversation(token: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    share = db.query(ConversationShare).filter(
        ConversationShare.share_token == token,
        ConversationShare.user_id == current_user.id
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    
    share.is_active = False
    db.commit()
    return {"status": "revoked"}

@router.get("/conversations/{conversation_id}/files")
async def get_conversation_files(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    files = []
    seen_ids = set()

    # 1. Generated images in this conversation
    images = db.query(GeneratedImage).filter(GeneratedImage.conversation_id == conv_uuid).order_by(GeneratedImage.created_at.desc()).all()
    for img in images:
        img_id = str(img.id)
        if img_id not in seen_ids:
            seen_ids.add(img_id)
            files.append({
                "id": img_id,
                "conversation_id": conversation_id,
                "name": f"image-{img_id[:8]}.png",
                "filename": f"image-{img_id[:8]}.png",
                "mime_type": "image/png",
                "size_bytes": 1024 * 1024,
                "thumbnail": img.image_url,
                "url": img.image_url,
                "source": "generated",
                "created_at": img.created_at.isoformat() if img.created_at else None
            })

    # 2. Attachments and files from messages in this conversation
    msgs = db.query(Message).filter(Message.conversation_id == conv_uuid).order_by(Message.created_at.desc()).all()
    for m in msgs:
        meta = m.metadata_json or {}
        attachments = meta.get("attachments", [])
        for att in attachments:
            att_id = str(att.get("id") or att.get("filename") or uuid.uuid4())
            if att_id not in seen_ids:
                seen_ids.add(att_id)
                files.append({
                    "id": att_id,
                    "conversation_id": conversation_id,
                    "name": att.get("filename") or att.get("name", "attachment"),
                    "filename": att.get("filename") or att.get("name", "attachment"),
                    "mime_type": att.get("mime_type", "application/octet-stream"),
                    "size_bytes": att.get("size", 0),
                    "thumbnail": att.get("url") if att.get("mime_type", "").startswith("image/") else None,
                    "url": att.get("url") or f"/api/v1/documents/{att_id}/download",
                    "source": "uploaded",
                    "created_at": m.created_at.isoformat() if m.created_at else None
                })
        
        # Tool results (generated outputs/charts/reports)
        tool_results = meta.get("tool_results", [])
        for tr in tool_results:
            if isinstance(tr, dict) and tr.get("output_file"):
                f = tr["output_file"]
                f_id = str(f.get("id") or f.get("filename") or uuid.uuid4())
                if f_id not in seen_ids:
                    seen_ids.add(f_id)
                    files.append({
                        "id": f_id,
                        "conversation_id": conversation_id,
                        "name": f.get("filename", "generated_artifact"),
                        "filename": f.get("filename", "generated_artifact"),
                        "mime_type": f.get("mime_type", "application/octet-stream"),
                        "size_bytes": f.get("size", 0),
                        "thumbnail": f.get("url"),
                        "url": f.get("url"),
                        "source": "generated",
                        "created_at": m.created_at.isoformat() if m.created_at else None
                    })

    return files

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_deleted", "id": conversation_id})
    return {"status": "deleted", "id": conversation_id}

class ConversationUpdate(BaseModel):
    title: str

@router.put("/conversations/{conversation_id}")
@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, update_data: ConversationUpdate, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    clean_title = update_data.title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Conversation title cannot be empty")
    conv.title = clean_title[:200]
    conv.updated_at = datetime.utcnow()
    db.commit()
    data = serialize_conversation(conv)
    await ws_manager.send_to_user(str(current_user.id), {"type": "conversation_updated", "action": "renamed", "data": data})
    return {"status": "updated", "conversation": data}

@router.get("/conversations/{conversation_id}/messages", response_model=List[Dict[str, Any]])
def list_messages(conversation_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == uuid.UUID(conversation_id), Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.asc()).all()
    
    result = []
    for m in messages:
        content = m.content or ""
        meta = m.metadata_json or {}
        # Auto-enrich assistant message if an image tool was run but content lacks markdown image tag
        if m.role == "assistant" and "![" not in content and meta.get("tool_results"):
            for tr in meta["tool_results"]:
                if tr.get("tool") in ["create_image", "edit_image"]:
                    tr_res = tr.get("result", "")
                    img_match = re.search(r"(!\[.*?\]\([^\)]+\))", tr_res)
                    data_match = re.search(r"(<!--\s*SAKURA_IMAGE_DATA:.*?-->)", tr_res, re.DOTALL)
                    if img_match:
                        content += f"\n\n{img_match.group(1)}"
                        if data_match:
                            content += f"\n\n{data_match.group(1)}"
        result.append({
            "id": str(m.id),
            "role": m.role,
            "content": content,
            "metadata": meta,
            "created_at": m.created_at.isoformat()
        })
    return result

class FeedbackRequest(BaseModel):
    rating: str  # "positive" | "negative"
    comment: Optional[str] = None
    category: Optional[str] = None

@router.post("/messages/{message_id}/feedback")
def submit_message_feedback(
    message_id: str,
    body: FeedbackRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    try:
        msg_uuid = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message ID")
    
    msg = db.query(Message).filter(Message.id == msg_uuid).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
        
    feedback = MessageFeedback(
        message_id=msg_uuid,
        user_id=current_user.id,
        rating=body.rating,
        comment=body.comment,
        category=body.category
    )
    db.add(feedback)
    db.commit()
    return {"status": "success", "id": str(feedback.id), "rating": body.rating}


# ─── Memory Endpoints ────────────────────────────────────────────────────────

@router.get("/memory", response_model=List[Dict[str, Any]])
def list_memory(current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    memories = db.query(UserMemory).filter(UserMemory.user_id == current_user.id).all()
    return [
        {
            "id": str(m.id),
            "memory_type": m.memory_type,
            "content": m.content,
            "confidence": m.confidence
        } for m in memories
    ]

@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    memory = db.query(UserMemory).filter(UserMemory.id == uuid.UUID(memory_id), UserMemory.user_id == current_user.id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    db.delete(memory)
    db.commit()
    return {"status": "deleted"}


# ─── Documents / RAG Endpoints ───────────────────────────────────────────────

UPLOAD_DIR = "./uploaded_documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Async document ingestion worker
async def async_ingest_document(doc_id: uuid.UUID, user_id: uuid.UUID):
    from database.db import get_db_context
    with get_db_context() as db:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return
            
        try:
            # 1. Parsing
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Parsing"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Parsing"})
            await asyncio.sleep(0.5)

            # Parse file
            parser = DocumentParser()
            raw_text = parser.parse_file(doc.storage_path, doc.mime_type)
            
            # 2. Chunking
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Chunking"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Chunking"})
            await asyncio.sleep(0.5)

            chunks = parser.get_chunks(raw_text)

            # 3. Embedding
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Embedding"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Embedding"})
            await asyncio.sleep(0.5)

            embed_mgr = EmbeddingManager()
            contents = [c["content"] for c in chunks]
            embeddings = embed_mgr.get_embeddings(contents)

            # 4. Indexing
            doc.metadata_json = {**doc.metadata_json, "indexing_status": "Indexing"}
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Indexing"})
            await asyncio.sleep(0.5)

            for i, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    embedding=embeddings[i],
                    metadata_json=chunk["metadata"]
                )
                db.add(db_chunk)

            # 5. Ready
            doc.metadata_json = {
                **doc.metadata_json,
                "indexing_status": "Ready",
                "chunks": len(chunks)
            }
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Ready", "chunks": len(chunks)})

        except Exception as e:
            # 6. Failed
            doc.metadata_json = {
                **doc.metadata_json,
                "indexing_status": "Failed",
                "error": str(e)
            }
            db.commit()
            await ws_manager.send_to_user(str(user_id), {"type": "document_status", "document_id": str(doc.id), "status": "Failed", "error": str(e)})

@router.post("/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    # Save file locally
    file_id = uuid.uuid4()
    extension = os.path.splitext(file.filename)[1]
    storage_path = os.path.join(UPLOAD_DIR, f"{file_id}{extension}")
    
    with open(storage_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    file_size = os.path.getsize(storage_path)

    try:
        # Create Document record with indexing_status="Uploaded"
        doc = Document(
            id=file_id,
            user_id=current_user.id,
            filename=file.filename,
            mime_type=file.content_type or "text/plain",
            storage_path=storage_path,
            metadata_json={
                "indexing_status": "Uploaded",
                "size": file_size,
                "chunks": 0,
                "error": None
            }
        )
        db.add(doc)
        db.commit()

        # Enqueue background ingestion
        background_tasks.add_task(async_ingest_document, doc.id, current_user.id)

        return {"status": "success", "document_id": str(doc.id)}
    except Exception as e:
        if os.path.exists(storage_path):
            os.remove(storage_path)
        raise HTTPException(status_code=500, detail=f"Failed to initiate file upload: {str(e)}")

@router.get("/documents", response_model=List[Dict[str, Any]])
def list_documents(current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.user_id == current_user.id).all()
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "mime_type": d.mime_type,
            "created_at": d.created_at.isoformat(),
            "metadata": d.metadata_json or {}
        } for d in docs
    ]

@router.delete("/documents/{document_id}")
def delete_document(document_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == uuid.UUID(document_id), Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # delete file from disk
    if os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass
            
    db.delete(doc)
    db.commit()
    return {"status": "deleted"}

class RenameRequest(BaseModel):
    filename: str

@router.post("/documents/{document_id}/rename")
def rename_document(document_id: str, req: RenameRequest, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == uuid.UUID(document_id), Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc.filename = req.filename
    db.commit()
    return {"status": "success", "filename": doc.filename}

@router.post("/documents/{document_id}/retry")
def retry_document_indexing(document_id: str, background_tasks: BackgroundTasks, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == uuid.UUID(document_id), Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # Reset status
    doc.metadata_json = {**doc.metadata_json, "indexing_status": "Uploaded", "error": None}
    db.commit()
    
    # Enqueue background ingestion
    background_tasks.add_task(async_ingest_document, doc.id, current_user.id)
    return {"status": "retry_queued"}


# ─── Async Background Memory Extraction ─────────────────────────────────────

def background_memory_extraction(user_id: Any, conversation_id: Any):
    """Worker task runs after stream completes to extract long-term preferences."""
    from database.db import get_db_context
    with get_db_context() as db:
        # Fetch last 6 messages of conversation
        messages = db.query(Message).filter(Message.conversation_id == uuid.UUID(str(conversation_id))).order_by(Message.created_at.desc()).limit(6).all()
        if not messages:
            return
            
        formatted = [{"role": m.role, "content": m.content} for m in reversed(messages)]
        mgr = MemoryManager(db)
        # Run extractor
        import asyncio
        asyncio.run(mgr.extract_and_save_memories(user_id, formatted))


# ─── Chat Streaming Endpoint ────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Fetch Conversation
    conv = db.query(Conversation).filter(Conversation.id == uuid.UUID(req.conversation_id), Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. Load conversation history with intelligent token budget (max ~7,500 chars, ~1,800 tokens)
    past_messages = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(12).all()
    history = []
    current_history_chars = 0
    max_history_chars = 7500

    for m in past_messages:
        # Ignore failed error message dumps from history
        if "I apologize, but I encountered an error generating a response" in m.content:
            continue
        content = m.content
        # If an individual historical message is excessively long, truncate for context economy
        if m.role == "assistant" and len(content) > 2000:
            content = content[:1200] + "\n\n... [content summarized for context] ...\n\n" + content[-400:]
        
        if current_history_chars + len(content) > max_history_chars:
            break
        
        history.insert(0, {"role": m.role, "content": content})
        current_history_chars += len(content)

    # 3. Save user message immediately
    user_attachments = [a.dict() if hasattr(a, 'dict') else a for a in (req.attachments or [])]
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=req.message,
        metadata_json={"attachments": user_attachments} if user_attachments else {}
    )
    db.add(user_msg)
    db.commit()

    # 4. Build system prompt
    engine = CharacterEngine(db, conv.character_id)
    emotional_state = engine.determine_emotional_state("general_inquiry", "neutral")
    system_prompt = engine.build_system_prompt(emotional_state)

    # 5. Enrich system prompt with user memories
    mem_mgr = MemoryManager(db)
    memories = mem_mgr.get_relevant_memories(current_user.id, req.message, limit=3)
    if memories:
        memory_ctx = "\n\nUser context from previous conversations:\n" + "\n".join(
            f"- {m['content']}" for m in memories
        )
        system_prompt += memory_ctx

    # Calculate exact context tokens using tiktoken
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        context_str = system_prompt + " " + req.message + " " + "".join(m["content"] for m in history)
        num_tokens = len(encoding.encode(context_str))
        current_context_used_by_user[str(current_user.id)] = num_tokens
    except Exception:
        current_context_used_by_user[str(current_user.id)] = len(req.message) // 4 + 500

    # 6. Create and run the Agent
    from llm.agent import Agent
    agent = Agent(
        db=db,
        user_id=current_user.id,
        conversation_id=conv.id,
        llm_router=llm_router,
        system_prompt=system_prompt,
        history=history,
        intensity=req.intensity or "medium",
        enabled_tools=req.tools or [],
        attachments=req.attachments or []
    )

    async def token_generator():
        full_response = ""
        provider_used = "unknown"

        async for chunk in agent.run_stream(req.message):
            token = chunk.get("token", "")
            provider_used = chunk.get("provider", provider_used)
            
            # Skip empty tool-call status tokens
            if chunk.get("tool_call"):
                yield f"data: {json.dumps({'tool_call': chunk['tool_call'], 'status': chunk['status']})}\n\n"
                continue

            if token:
                user_tokens_count[str(current_user.id)] += 1
                full_response += token
                yield f"data: {json.dumps({'token': token, 'provider': provider_used})}\n\n"

        # Save assistant message after stream completes
        from database.db import get_db_context
        with get_db_context() as db_ctx:
            meta = {
                "provider": provider_used,
                "tool_results": agent.get_tool_results(),
            }
            assistant_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content=full_response,
                metadata_json=meta
            )
            db_ctx.add(assistant_msg)

            c = db_ctx.query(Conversation).filter_by(id=conv.id).first()
            if c:
                # Auto-title: use first 50 chars of first user message
                if c.title.startswith("Chat with"):
                    c.title = req.message[:50] + ("..." if len(req.message) > 50 else "")
                c.updated_at = __import__("datetime").datetime.utcnow()

            db_ctx.commit()

        # Queue background memory extraction
        background_tasks.add_task(background_memory_extraction, current_user.id, conv.id)

    return StreamingResponse(token_generator(), media_type="text/event-stream")

# Helper to execute task flows asynchronously
async def run_task_flow(task_id: str, user_id: str):
    from database.db import get_db_context
    task_info = ACTIVE_TASKS.get(task_id)
    if not task_info:
        return
        
    task_info["status"] = "Starting"
    task_info["startedAt"] = datetime.utcnow().isoformat()
    await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_info})
    await asyncio.sleep(0.5)
    
    task_type = task_info["type"]
    payload = task_info["payload"]
    
    with get_db_context() as db:
        try:
            if task_type == "code_analysis":
                await execute_code_analysis(task_id, user_id, payload["code"], payload.get("task", "explain"), db)
            elif task_type == "doc_summary":
                await execute_doc_summary(task_id, user_id, payload["document_id"], db)
            elif task_type == "dataset_analysis":
                await execute_dataset_analysis(task_id, user_id, payload["dataset_text"], db)
            elif task_type == "web_research":
                await execute_web_research(task_id, user_id, payload["query"], db)
            else:
                await update_task_status(task_id, user_id, "Failed", 100, error="Unknown task type")
        except asyncio.CancelledError:
            task_info["status"] = "Cancelled"
            task_info["completedAt"] = datetime.utcnow().isoformat()
            await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_info})
        except Exception as e:
            await update_task_status(task_id, user_id, "Failed", 100, error=str(e))
        finally:
            if task_id in RUNNING_TASKS:
                del RUNNING_TASKS[task_id]

async def update_task_status(task_id: str, user_id: str, status: str, progress: int, error: Optional[str] = None, result: Optional[str] = None):
    task_info = ACTIVE_TASKS.get(task_id)
    if task_info:
        task_info["status"] = status
        task_info["progress"] = progress
        if error:
            task_info["error"] = error
        if result:
            task_info["result"] = result
        if status in ["Completed", "Failed", "Cancelled"]:
            task_info["completedAt"] = datetime.utcnow().isoformat()
        await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_info})

async def execute_code_analysis(task_id: str, user_id: str, code: str, instruction: str, db: Session):
    await update_task_status(task_id, user_id, "Running", 10)
    await asyncio.sleep(1.0)
    await update_task_status(task_id, user_id, "Running", 40)
    
    prompt = f"Please analyze this code and provide a review:\nTask: {instruction}\nCode:\n{code}"
    try:
        await update_task_status(task_id, user_id, "Running", 60)
        _, response = await llm_router.generate(prompt=prompt, system_prompt="You are a senior code reviewer.")
        await update_task_status(task_id, user_id, "Completed", 100, result=response)
    except Exception as e:
        await update_task_status(task_id, user_id, "Failed", 100, error=str(e))

async def execute_doc_summary(task_id: str, user_id: str, doc_id: str, db: Session):
    await update_task_status(task_id, user_id, "Running", 10)
    doc = db.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
    if not doc:
        await update_task_status(task_id, user_id, "Failed", 100, error="Document not found")
        return
        
    await update_task_status(task_id, user_id, "Running", 30)
    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc()).all()
    if not chunks:
        await update_task_status(task_id, user_id, "Failed", 100, error="No text indexed in this document")
        return
        
    await update_task_status(task_id, user_id, "Running", 50)
    combined_text = "\n".join(c.content for c in chunks[:5])
    prompt = f"Please summarize the following document content:\n\n{combined_text}"
    try:
        await update_task_status(task_id, user_id, "Running", 70)
        _, response = await llm_router.generate(prompt=prompt, system_prompt="You are a precise document summarizer.")
        await update_task_status(task_id, user_id, "Completed", 100, result=response)
    except Exception as e:
        await update_task_status(task_id, user_id, "Failed", 100, error=str(e))

async def execute_dataset_analysis(task_id: str, user_id: str, dataset_text: str, db: Session):
    await update_task_status(task_id, user_id, "Running", 20)
    await asyncio.sleep(0.5)
    await update_task_status(task_id, user_id, "Running", 50)
    try:
        lines = dataset_text.strip().split("\n")
        num_rows = len(lines)
        num_cols = len(lines[0].split(",")) if num_rows > 0 else 0
        analysis_result = f"Dataset Analysis Report:\n- Total Rows: {num_rows}\n- Estimated Columns: {num_cols}\n"
        if num_rows > 1:
            analysis_result += f"- Headers: {lines[0]}"
        await update_task_status(task_id, user_id, "Running", 80)
        await asyncio.sleep(0.5)
        await update_task_status(task_id, user_id, "Completed", 100, result=analysis_result)
    except Exception as e:
        await update_task_status(task_id, user_id, "Failed", 100, error=str(e))

async def execute_web_research(task_id: str, user_id: str, query: str, db: Session):
    await update_task_status(task_id, user_id, "Running", 10)
    try:
        await update_task_status(task_id, user_id, "Running", 30)
        await asyncio.sleep(1.0)
        await update_task_status(task_id, user_id, "Running", 60)
        prompt = f"Write a research summary on the following topic: {query}"
        _, response = await llm_router.generate(prompt=prompt, system_prompt="You are a research analyst.")
        await update_task_status(task_id, user_id, "Completed", 100, result=response)
    except Exception as e:
        await update_task_status(task_id, user_id, "Failed", 100, error=str(e))

# System Status Broadcast Loop
async def system_status_broadcast_loop():
    while True:
        try:
            await asyncio.sleep(1.0)
            for user_id in list(user_tokens_count.keys()):
                tokens_per_second_by_user[user_id] = user_tokens_count[user_id]
                user_tokens_count[user_id] = 0
                
            for user_id in list(ws_manager.user_connections.keys()):
                user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
                active_tasks_count = len([t for t in user_tasks if t["status"] in ["Queued", "Starting", "Running", "Waiting"]])
                
                avg_latency = sum(LATENCY_SAMPLES) / len(LATENCY_SAMPLES) if LATENCY_SAMPLES else 120.0
                
                uptime_seconds = int(time.time() - START_TIME)
                m, s = divmod(uptime_seconds, 60)
                h, m = divmod(m, 60)
                uptime_str = f"{h:02d}:{m:02d}:{s:02d}"
                
                status_payload = {
                    "type": "system_status",
                    "data": {
                        "connection": "LIVE",
                        "latency": round(avg_latency),
                        "contextUsed": current_context_used_by_user.get(user_id, 0),
                        "contextLimit": 128000,
                        "tokensPerSecond": tokens_per_second_by_user.get(user_id, 0),
                        "activeTasks": active_tasks_count,
                        "region": "IN / AP-SOUTH",
                        "uptime": uptime_str,
                        "lastUpdatedAt": datetime.utcnow().isoformat()
                    }
                }
                await ws_manager.send_to_user(user_id, status_payload)
        except Exception:
            pass

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(system_status_broadcast_loop())

@router.get("/system/status")
def system_status(current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
    active_tasks_count = len([t for t in user_tasks if t["status"] in ["Queued", "Starting", "Running", "Waiting"]])
    avg_latency = sum(LATENCY_SAMPLES) / len(LATENCY_SAMPLES) if LATENCY_SAMPLES else 120.0
    
    uptime_seconds = int(time.time() - START_TIME)
    m, s = divmod(uptime_seconds, 60)
    h, m = divmod(m, 60)
    uptime_str = f"{h:02d}:{m:02d}:{s:02d}"
    
    return {
        "connection": "LIVE",
        "latency": round(avg_latency),
        "contextUsed": current_context_used_by_user.get(user_id, 0),
        "contextLimit": 128000,
        "tokensPerSecond": tokens_per_second_by_user.get(user_id, 0),
        "activeTasks": active_tasks_count,
        "region": "IN / AP-SOUTH",
        "uptime": uptime_str,
        "lastUpdatedAt": datetime.utcnow().isoformat(),
        "cpu": psutil.cpu_percent(interval=None),
        "memory": psutil.virtual_memory().percent
    }

# WebSocket route
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    if not token:
        token = websocket.query_params.get("token")
        
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    try:
        from jose import jwt
        from auth.manager import SECRET_KEY, ALGORITHM
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    from database.db import get_db_context
    with get_db_context() as db:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_id = str(user.id)

    await ws_manager.connect(user_id, websocket)
    try:
        user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
        await websocket.send_json({"type": "tasks_list", "data": user_tasks})
        
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user_id, websocket)

# Tasks Queue HTTP Endpoints
class TaskCreateRequest(BaseModel):
    type: str
    title: str
    payload: Dict[str, Any]

@router.post("/tasks")
async def create_task(req: TaskCreateRequest, current_user: User = Depends(AuthManager.get_current_user)):
    task_id = str(uuid.uuid4())
    user_id = str(current_user.id)
    
    if req.type == "doc_summary" and "document_id" not in req.payload:
        raise HTTPException(status_code=400, detail="document_id is required for document summary")
    elif req.type == "code_analysis" and "code" not in req.payload:
        raise HTTPException(status_code=400, detail="code is required for code analysis")
    elif req.type == "dataset_analysis" and "dataset_text" not in req.payload:
        raise HTTPException(status_code=400, detail="dataset_text is required for dataset analysis")
    elif req.type == "web_research" and "query" not in req.payload:
        raise HTTPException(status_code=400, detail="query is required for web research")
        
    task_info = {
        "id": task_id,
        "type": req.type,
        "title": req.title,
        "status": "Queued",
        "progress": 0,
        "createdAt": datetime.utcnow().isoformat(),
        "startedAt": None,
        "completedAt": None,
        "error": None,
        "result": None,
        "payload": req.payload,
        "userId": user_id
    }
    
    ACTIVE_TASKS[task_id] = task_info
    
    t = asyncio.create_task(run_task_flow(task_id, user_id))
    RUNNING_TASKS[task_id] = t
    
    user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
    await ws_manager.send_to_user(user_id, {"type": "tasks_list", "data": user_tasks})
    return task_info

@router.get("/tasks")
def list_tasks(current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
    return user_tasks

@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    task_info = ACTIVE_TASKS.get(task_id)
    if not task_info or task_info["userId"] != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task_info["status"] in ["Queued", "Starting", "Running", "Waiting"]:
        if task_id in RUNNING_TASKS:
            RUNNING_TASKS[task_id].cancel()
            del RUNNING_TASKS[task_id]
        
        task_info["status"] = "Cancelled"
        task_info["completedAt"] = datetime.utcnow().isoformat()
        await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_info})
        
    return task_info

@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    task_info = ACTIVE_TASKS.get(task_id)
    if not task_info or task_info["userId"] != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task_info["status"] in ["Failed", "Cancelled"]:
        task_info["status"] = "Queued"
        task_info["progress"] = 0
        task_info["error"] = None
        task_info["result"] = None
        task_info["createdAt"] = datetime.utcnow().isoformat()
        task_info["startedAt"] = None
        task_info["completedAt"] = None
        
        t = asyncio.create_task(run_task_flow(task_id, user_id))
        RUNNING_TASKS[task_id] = t
        
        await ws_manager.send_to_user(user_id, {"type": "task_update", "data": task_info})
        
    return task_info

@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    task_info = ACTIVE_TASKS.get(task_id)
    if not task_info or task_info["userId"] != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task_info["status"] in ["Queued", "Starting", "Running", "Waiting"]:
        if task_id in RUNNING_TASKS:
            RUNNING_TASKS[task_id].cancel()
            del RUNNING_TASKS[task_id]
            
    del ACTIVE_TASKS[task_id]
    
    user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
    await ws_manager.send_to_user(user_id, {"type": "tasks_list", "data": user_tasks})
    return {"status": "deleted"}

@router.delete("/tasks/clear_completed")
async def clear_completed_tasks(current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    to_delete = [tid for tid, t in ACTIVE_TASKS.items() if t["userId"] == user_id and t["status"] in ["Completed", "Failed", "Cancelled"]]
    for tid in to_delete:
        del ACTIVE_TASKS[tid]
        
    user_tasks = [t for t in ACTIVE_TASKS.values() if t["userId"] == user_id]
    await ws_manager.send_to_user(user_id, {"type": "tasks_list", "data": user_tasks})
    return {"status": "cleared"}


# ─── Image Generation & Editing Endpoints ─────────────────────────────────────

class ImageGenerateAPIRequest(BaseModel):
    prompt: str
    conversation_id: Optional[str] = None
    aspect_ratio: Optional[str] = "1:1"
    intensity: Optional[str] = "medium"

class ImageEditAPIRequest(BaseModel):
    parent_image_id: str
    edit_instruction: str
    conversation_id: Optional[str] = None
    intensity: Optional[str] = "medium"

class ImageVariationAPIRequest(BaseModel):
    parent_image_id: str
    count: Optional[int] = 2
    conversation_id: Optional[str] = None

class ImageUpscaleAPIRequest(BaseModel):
    parent_image_id: str
    scale: Optional[int] = 2
    conversation_id: Optional[str] = None

@router.post("/images/generate")
async def api_generate_image(
    req: ImageGenerateAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from media.image_engine import ImageGenerationEngine
    conv_id = uuid.UUID(req.conversation_id) if req.conversation_id else None
    engine = ImageGenerationEngine(db, current_user.id)
    try:
        res = await engine.generate_image(
            prompt=req.prompt,
            conversation_id=conv_id,
            aspect_ratio=req.aspect_ratio,
            intensity=req.intensity or "medium"
        )
        return {"status": "success", "image": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/images/edit")
async def api_edit_image(
    req: ImageEditAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from media.image_engine import ImageGenerationEngine
    conv_id = uuid.UUID(req.conversation_id) if req.conversation_id else None
    parent_id = uuid.UUID(req.parent_image_id)
    engine = ImageGenerationEngine(db, current_user.id)
    try:
        res = await engine.edit_image(
            parent_image_id=parent_id,
            edit_instruction=req.edit_instruction,
            conversation_id=conv_id,
            intensity=req.intensity or "medium"
        )
        return {"status": "success", "image": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/images/variation")
async def api_variation_image(
    req: ImageVariationAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from media.image_engine import ImageGenerationEngine
    conv_id = uuid.UUID(req.conversation_id) if req.conversation_id else None
    parent_id = uuid.UUID(req.parent_image_id)
    engine = ImageGenerationEngine(db, current_user.id)
    try:
        res = await engine.create_variations(
            parent_image_id=parent_id,
            count=req.count or 2,
            conversation_id=conv_id
        )
        return {"status": "success", "variations": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/images/upscale")
async def api_upscale_image(
    req: ImageUpscaleAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from media.image_engine import ImageGenerationEngine
    conv_id = uuid.UUID(req.conversation_id) if req.conversation_id else None
    parent_id = uuid.UUID(req.parent_image_id)
    engine = ImageGenerationEngine(db, current_user.id)
    try:
        res = await engine.upscale_image(
            parent_image_id=parent_id,
            scale=req.scale or 2,
            conversation_id=conv_id
        )
        return {"status": "success", "image": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/images/{image_id}/metadata")
def api_get_image_metadata(
    image_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    from database.models import GeneratedImage
    img = db.query(GeneratedImage).filter(
        GeneratedImage.id == uuid.UUID(image_id),
        GeneratedImage.user_id == current_user.id
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    return {
        "id": str(img.id),
        "prompt": img.prompt,
        "enhanced_prompt": img.enhanced_prompt,
        "aspect_ratio": img.aspect_ratio,
        "width": img.width,
        "height": img.height,
        "model": img.model,
        "seed": img.seed,
        "workflow": img.workflow,
        "parent_image_id": str(img.parent_image_id) if img.parent_image_id else None,
        "lineage_depth": img.lineage_depth,
        "url": img.image_url,
        "created_at": img.created_at.isoformat()
    }

