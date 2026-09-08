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
    MessageFeedback, ConversationShare, utc_now
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
from api.capabilities import router as capabilities_router

# Import NLP classifiers
from ml_pipeline import SentimentAnalyzer, IntentClassifier

# Global telemetry & connection variables
START_TIME = time.time()
LATENCY_SAMPLES = []
current_context_used_by_user = {}
tokens_per_second_by_user = {}
user_tokens_count = __import__("collections").defaultdict(int)

from realtime.manager import ws_manager
from tasks.task_manager import TaskManager

router = APIRouter(prefix="/api/v1")
router.include_router(audio_router)
router.include_router(library_router)
router.include_router(coding_router)
router.include_router(projects_router)
router.include_router(scheduled_router)
router.include_router(integrations_router)
router.include_router(capabilities_router)

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
    active_workspace_id: Optional[str] = None
    repository_workspace_id: Optional[str] = None


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


@router.post("/auth/ws-ticket")
def issue_websocket_ticket(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Issues a short-lived, single-use WebSocket ticket for authenticating realtime connections."""
    return AuthManager.issue_ws_ticket(user_id=current_user.id, ttl_seconds=60, db=db)


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
async def share_conversation(
    conversation_id: str,
    expires_in: Optional[str] = "never",
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    expires_at = None
    if expires_in:
        exp_clean = expires_in.strip().lower()
        if exp_clean == "1d":
            expires_at = utc_now() + timedelta(days=1)
        elif exp_clean == "7d":
            expires_at = utc_now() + timedelta(days=7)
        elif exp_clean == "30d":
            expires_at = utc_now() + timedelta(days=30)
    
    existing_share = db.query(ConversationShare).filter(
        ConversationShare.conversation_id == conv.id,
        ConversationShare.is_active == True,
        ConversationShare.revoked_at.is_(None)
    ).first()
    
    if existing_share:
        share_token = existing_share.share_token
        existing_share.expires_at = expires_at
        db.commit()
    else:
        share_token = secrets.token_urlsafe(16)
        share = ConversationShare(
            conversation_id=conv.id,
            user_id=current_user.id,
            share_token=share_token,
            is_active=True,
            expires_at=expires_at
        )
        db.add(share)
        db.commit()

    share_url = f"/share/{share_token}"
    return {
        "status": "shared",
        "conversation_id": str(conv.id),
        "share_token": share_token,
        "title": conv.title,
        "share_url": share_url,
        "expires_at": expires_at.isoformat() if expires_at else None
    }

@router.get("/share/{token}")
def get_shared_conversation(token: str, db: Session = Depends(get_db)):
    now = utc_now()
    share = db.query(ConversationShare).filter(
        ConversationShare.share_token == token,
        ConversationShare.is_active == True,
        ConversationShare.revoked_at.is_(None)
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Shared conversation not found or expired")
    
    if share.expires_at is not None:
        share_exp = share.expires_at.replace(tzinfo=None) if share.expires_at.tzinfo else share.expires_at
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        if share_exp <= now_naive:
            raise HTTPException(status_code=404, detail="Shared conversation not found or expired")
    
    conv = db.query(Conversation).filter(Conversation.id == share.conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.asc()).all()
    return {
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "character_id": conv.character_id,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
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
    share.revoked_at = utc_now()
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
            img_size = img.storage_size or (img.metadata_json or {}).get("file_size") or 0
            if not img_size and img.storage_path and os.path.exists(img.storage_path):
                try:
                    img_size = os.path.getsize(img.storage_path)
                except Exception:
                    img_size = 0
            files.append({
                "id": img_id,
                "conversation_id": conversation_id,
                "name": f"image-{img_id[:8]}.png",
                "filename": f"image-{img_id[:8]}.png",
                "mime_type": "image/png",
                "size_bytes": img_size,
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
    from auth.authorization import assert_message_owner
    msg = assert_message_owner(db, message_id, current_user.id)
        
    feedback = MessageFeedback(
        message_id=msg.id,
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

@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Uploads document to durable StorageBackend and enqueues durable document_index worker task."""
    import services.documents as docs_svc
    doc = await docs_svc.upload_document(
        file=file,
        user_id=current_user.id,
        db=db,
        auto_index=True
    )
    return {"status": "success", "document_id": str(doc.id)}

@router.get("/documents", response_model=List[Dict[str, Any]])
def list_documents(current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    import services.documents as docs_svc
    docs = db.query(Document).filter(Document.user_id == current_user.id).all()
    return [docs_svc.serialize_document(d) for d in docs]

@router.delete("/documents/{document_id}")
def delete_document(document_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    import services.documents as docs_svc
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document ID format")
    docs_svc.delete_document(doc_uuid, current_user.id, db)
    return {"status": "deleted"}

class RenameRequest(BaseModel):
    filename: str

@router.post("/documents/{document_id}/rename")
def rename_document(document_id: str, req: RenameRequest, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == uuid.UUID(document_id), Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    clean_name = req.filename.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")
    doc.filename = clean_name
    db.commit()
    return {"status": "success", "filename": doc.filename}

@router.post("/documents/{document_id}/retry")
def retry_document_indexing(document_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    import services.documents as docs_svc
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document ID format")
    task = docs_svc.retry_indexing(doc_uuid, current_user.id, db)
    return {"status": "retry_queued", "task_id": str(task.id)}


# ─── Async Background Memory Extraction ─────────────────────────────────────

def background_memory_extraction(user_id: Any, conversation_id: Any):
    """Worker task runs after stream completes to extract long-term preferences."""
    import os
    env = os.getenv("ENVIRONMENT", "").lower()
    from config.settings import get_settings
    if env in ["test", "testing"] or get_settings().environment in ["test", "testing"]:
        return
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


def is_repository_coding_intent(message: str) -> bool:
    """Detects repository engineering intent requiring a repository workspace."""
    msg_lower = (message or "").strip().lower()
    if msg_lower.startswith("/code"):
        return True
    repo_patterns = [
        r"\b(fix|patch|resolve)\s+(the\s+)?.*?(bug|issue|failure|error|crash|endpoint)\b",
        r"\bupdate\s+(the\s+)?(api|validation|schema|route|handler|model|component|service)\b",
        r"\b(run|execute)\s+(the\s+)?(tests?|linter|typecheck|build)\s+and\s+(fix|patch)\b",
        r"\brefactor\s+(this\s+|the\s+)?(component|module|file|class|function|service|subsystem)\b",
        r"\bimplement\s+.*?\s+(in\s+(the\s+)?(backend|frontend|repo|codebase|api|system))\b",
        r"\breview\s+(this\s+|the\s+)?(repo|repository|codebase|diff)\s+and\s+(patch|fix)\b",
        r"\bin\s+this\s+(repo|repository|codebase)\b",
    ]
    return any(re.search(pat, msg_lower) for pat in repo_patterns)


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

    # 5b. Enrich with Project context if conversation is associated with a project
    from database.models import ProjectConversation, RepositoryWorkspace, CodingTask, TaskOutcome
    from coding.agent import CodingAgent

    project_link = db.query(ProjectConversation).filter(ProjectConversation.conversation_id == conv.id).first()
    active_project = project_link.project if project_link else None

    if active_project:
        if active_project.instructions:
            system_prompt += f"\n\nProject Instructions ({active_project.name}):\n{active_project.instructions}"
        if active_project.repositories:
            repos_info = "\n".join(f"- {r.name} ({r.branch}): {r.repository_url}" for r in active_project.repositories)
            system_prompt += f"\n\nAttached Project Repositories:\n{repos_info}"

    # Calculate exact context tokens using tiktoken
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        context_str = system_prompt + " " + req.message + " " + "".join(m["content"] for m in history)
        num_tokens = len(encoding.encode(context_str))
        current_context_used_by_user[str(current_user.id)] = num_tokens
    except Exception:
        current_context_used_by_user[str(current_user.id)] = len(req.message) // 4 + 500

    # 5c. Check if request targets repository coding agent
    is_code_command = req.message.strip().startswith("/code")
    has_coding_tool = any(t in (req.tools or []) for t in ["sakura_code", "code_workspace"])
    inferred_intent = is_repository_coding_intent(req.message)

    if is_code_command or (active_project and has_coding_tool) or inferred_intent:
        code_objective = req.message.replace("/code", "", 1).strip() if is_code_command else req.message

        user_workspaces = db.query(RepositoryWorkspace).filter(
            RepositoryWorkspace.user_id == current_user.id
        ).all()

        ws = None
        # 1. Explicit workspace ID in request
        explicit_ws_id = req.active_workspace_id or req.repository_workspace_id
        if explicit_ws_id:
            try:
                target_uuid = uuid.UUID(str(explicit_ws_id))
                ws = next((w for w in user_workspaces if w.id == target_uuid), None)
            except ValueError:
                ws = None
            if not ws:
                async def not_found_generator():
                    yield f"data: {json.dumps({'token': f'Specified workspace `{explicit_ws_id}` was not found or access is denied.', 'provider': 'sakura_code'})}\n\n"
                return StreamingResponse(not_found_generator(), media_type="text/event-stream")
        else:
            # 2. Active project workspace match
            if not ws and active_project:
                matched_workspaces = [w for w in user_workspaces if active_project.name.lower() in w.name.lower()]
                if len(matched_workspaces) == 1:
                    ws = matched_workspaces[0]

            # 3. Exactly one unambiguous workspace for user
            if not ws and len(user_workspaces) == 1:
                ws = user_workspaces[0]

            # 4. Multiple candidate workspaces with no selection -> ask which repository
            if not ws and len(user_workspaces) > 1 and (is_code_command or has_coding_tool or "repo" in req.message.lower() or "repository" in req.message.lower()):
                ws_options = "\n".join(f"- **{w.name}** (`{w.id}`)" for w in user_workspaces)
                clarification_msg = (
                    f"You have {len(user_workspaces)} repository workspaces available:\n\n"
                    f"{ws_options}\n\n"
                    f"Please specify which workspace you would like Sakura Code to target."
                )
                async def disambiguation_generator():
                    yield f"data: {json.dumps({'token': clarification_msg, 'provider': 'sakura_code'})}\n\n"
                return StreamingResponse(disambiguation_generator(), media_type="text/event-stream")

        if ws:
            coding_agent = CodingAgent(
                db=db,
                workspace=ws,
                user=current_user,
                llm_router=llm_router,
                intensity=req.intensity or "high"
            )
            coding_task = CodingTask(
                workspace_id=ws.id,
                user_id=current_user.id,
                title=f"Chat Coding: {code_objective[:40]}",
                objective=code_objective,
                status=TaskOutcome.QUEUED
            )
            db.add(coding_task)
            db.commit()

            async def coding_stream_generator():
                full_response = ""
                async for event in coding_agent.run_task_stream(coding_task):
                    if "tool" in event:
                        tool_name = event.get("tool")
                        tool_phase = event.get("phase", "TOOL")
                        chunk_msg = f"\n`[{tool_phase}: {tool_name}]`\n"
                        full_response += chunk_msg
                        yield f"data: {json.dumps({'token': chunk_msg, 'provider': 'sakura_code'})}\n\n"
                    elif "message" in event:
                        msg_token = f"*{event['message']}*\n"
                        full_response += msg_token
                        yield f"data: {json.dumps({'token': msg_token, 'provider': 'sakura_code'})}\n\n"
                    elif "final_output" in event:
                        final_out = f"\n\n### Coding Task Result: {event.get('phase')}\n\n{event['final_output']}"
                        full_response += final_out
                        yield f"data: {json.dumps({'token': final_out, 'provider': 'sakura_code'})}\n\n"
                    elif "error" in event:
                        err_out = f"\n\n**Error:** {event['error']}\n"
                        full_response += err_out
                        yield f"data: {json.dumps({'token': err_out, 'provider': 'sakura_code'})}\n\n"

                # Save assistant message after stream completes
                from database.db import get_db_context
                with get_db_context() as db_ctx:
                    assistant_msg = Message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=full_response,
                        metadata_json={"provider": "sakura_code", "coding_task_id": str(coding_task.id)}
                    )
                    db_ctx.add(assistant_msg)
                    c = db_ctx.query(Conversation).filter_by(id=conv.id).first()
                    if c:
                        if c.title.startswith("Chat with"):
                            c.title = req.message[:50] + ("..." if len(req.message) > 50 else "")
                        c.updated_at = utc_now()
                    db_ctx.commit()

            return StreamingResponse(coding_stream_generator(), media_type="text/event-stream")

    # 6. Create and run standard Agent
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

def get_system_telemetry(user_id: str, user_uuid: uuid.UUID) -> dict:
    active_tasks_count = TaskManager.count_active_tasks(user_uuid)
    avg_latency = round(sum(LATENCY_SAMPLES) / len(LATENCY_SAMPLES)) if LATENCY_SAMPLES else None

    uptime_seconds = int(time.time() - START_TIME)
    m, s = divmod(uptime_seconds, 60)
    h, m = divmod(m, 60)
    uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

    context_limit = None
    try:
        active_provider = llm_router.get_active_provider()
        if hasattr(active_provider, "context_limit"):
            context_limit = active_provider.context_limit
        elif hasattr(active_provider, "model"):
            model_name = getattr(active_provider, "model", "")
            if "claude" in model_name.lower():
                context_limit = 200000
            elif "gpt-4" in model_name.lower():
                context_limit = 128000
    except Exception:
        context_limit = None

    region = os.getenv("DEPLOYMENT_REGION", None)
    is_live = user_id in ws_manager.user_connections and len(ws_manager.user_connections[user_id]) > 0

    return {
        "connection": "LIVE" if is_live else "ONLINE",
        "latency": avg_latency,
        "contextUsed": current_context_used_by_user.get(user_id, 0),
        "contextLimit": context_limit,
        "tokensPerSecond": tokens_per_second_by_user.get(user_id, 0),
        "activeTasks": active_tasks_count,
        "region": region,
        "uptime": uptime_str,
        "lastUpdatedAt": datetime.utcnow().isoformat()
    }

# System Status Broadcast Loop
async def system_status_broadcast_loop():
    while True:
        if os.getenv("ENVIRONMENT", "").lower() in ["test", "testing"]:
            break
        try:
            await asyncio.sleep(1.0)
            for user_id in list(user_tokens_count.keys()):
                tokens_per_second_by_user[user_id] = user_tokens_count[user_id]
                user_tokens_count[user_id] = 0

            for user_id in list(ws_manager.user_connections.keys()):
                try:
                    u_uuid = uuid.UUID(user_id)
                except ValueError:
                    continue
                telemetry = get_system_telemetry(user_id, u_uuid)
                status_payload = {
                    "type": "system_status",
                    "data": telemetry
                }
                await ws_manager.send_to_user(user_id, status_payload)
        except asyncio.CancelledError:
            break
        except Exception:
            pass

_status_broadcast_task = None
 
@router.on_event("startup")
async def startup_event():
    global _status_broadcast_task
    env_str = os.getenv("ENVIRONMENT", "").lower()
    if env_str in ["test", "testing"]:
        return
    from config.settings import get_settings
    if get_settings().environment in ["test", "testing"]:
        return
    await ws_manager.initialize()
    _status_broadcast_task = asyncio.create_task(system_status_broadcast_loop())

@router.on_event("shutdown")
async def shutdown_event():
    global _status_broadcast_task
    if _status_broadcast_task:
        _status_broadcast_task.cancel()
        try:
            await _status_broadcast_task
        except asyncio.CancelledError:
            pass
        _status_broadcast_task = None
    await ws_manager.shutdown()

@router.get("/system/status")
def system_status(current_user: User = Depends(AuthManager.get_current_user)):
    user_id = str(current_user.id)
    return get_system_telemetry(user_id, current_user.id)

# WebSocket route
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    ticket: Optional[str] = None,
    token: Optional[str] = None
):
    user_id = None
    if not ticket:
        ticket = websocket.query_params.get("ticket")
    if not token:
        token = websocket.query_params.get("token")

    if ticket:
        user_uuid = AuthManager.consume_ws_ticket(ticket)
        if user_uuid:
            user_id = str(user_uuid)
        else:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    elif token:
        try:
            from jose import jwt
            from auth.manager import SECRET_KEY, ALGORITHM
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            from database.db import get_db_context
            with get_db_context() as db:
                user = db.query(User).filter(User.username == username).first()
                if not user:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                user_id = str(user.id)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    else:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(user_id, websocket)
    try:
        try:
            import uuid as _uuid
            user_tasks = [t.to_dict() for t in TaskManager.list_tasks(_uuid.UUID(user_id))]
            await websocket.send_json({"type": "tasks_list", "data": user_tasks})
        except Exception:
            pass

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
    user_id = str(current_user.id)

    if req.type == "doc_summary" and "document_id" not in req.payload:
        raise HTTPException(status_code=400, detail="document_id is required for document summary")
    elif req.type == "code_analysis" and "code" not in req.payload:
        raise HTTPException(status_code=400, detail="code is required for code analysis")
    elif req.type == "dataset_analysis" and "dataset_text" not in req.payload:
        raise HTTPException(status_code=400, detail="dataset_text is required for dataset analysis")
    elif req.type == "web_research" and "query" not in req.payload:
        raise HTTPException(status_code=400, detail="query is required for web research")

    task = TaskManager.create_task(
        user_id=current_user.id,
        task_type=req.type,
        title=req.title,
        payload=req.payload
    )
    user_tasks = [t.to_dict() for t in TaskManager.list_tasks(current_user.id)]
    await ws_manager.send_to_user(user_id, {"type": "tasks_list", "data": user_tasks})
    return task.to_dict()

@router.get("/tasks")
def list_tasks(current_user: User = Depends(AuthManager.get_current_user)):
    return [t.to_dict() for t in TaskManager.list_tasks(current_user.id)]

@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    task = await TaskManager.cancel_task(t_uuid, current_user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()

@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    task = await TaskManager.retry_task(t_uuid, current_user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()

@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = Depends(AuthManager.get_current_user)):
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    success = TaskManager.delete_task(t_uuid, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    user_tasks = [t.to_dict() for t in TaskManager.list_tasks(current_user.id)]
    await ws_manager.send_to_user(str(current_user.id), {"type": "tasks_list", "data": user_tasks})
    return {"status": "deleted"}

@router.delete("/tasks/clear_completed")
async def clear_completed_tasks(current_user: User = Depends(AuthManager.get_current_user)):
    TaskManager.clear_completed_tasks(current_user.id)
    user_tasks = [t.to_dict() for t in TaskManager.list_tasks(current_user.id)]
    await ws_manager.send_to_user(str(current_user.id), {"type": "tasks_list", "data": user_tasks})
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

