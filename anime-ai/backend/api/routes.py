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
from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
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
    email: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class PasswordResetRequestBody(BaseModel):
    identifier: str

class PasswordResetConfirmBody(BaseModel):
    token: str
    new_password: str

class AccountDeleteBody(BaseModel):
    password: str
    confirm: str

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    intensity: Optional[str] = "medium"
    tools: Optional[List[str]] = []
    attachments: Optional[List[Dict[str, Any]]] = []
    active_workspace_id: Optional[str] = None
    repository_workspace_id: Optional[str] = None
    idempotency_key: Optional[str] = None


# ─── Auth Endpoints ─────────────────────────────────────────────────────────

@router.get("/auth/config")
def get_auth_config():
    """Returns truthful authentication capabilities for the login/registration UI."""
    from services.email import is_password_reset_enabled
    return {
        "password_reset_enabled": is_password_reset_enabled(),
        # OAuth login authorize/callback routes are not implemented; never advertise broken links.
        "google_oauth_enabled": False,
        "github_oauth_enabled": False,
    }


@router.post("/auth/register", response_model=Dict[str, str])
def register(user_data: UserRegister, request: Request, db: Session = Depends(get_db)):
    from services.rate_limit import enforce_rate_limit, get_client_ip
    client_ip = get_client_ip(request)
    enforce_rate_limit("auth_register", client_ip, limit=15, window_seconds=900, fail_closed_in_prod=True)

    clean_username = (user_data.username or "").strip()
    if not clean_username or len(clean_username) > 100:
        raise HTTPException(status_code=400, detail="Valid username is required.")

    existing = db.query(User).filter(User.username == clean_username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")

    clean_email = (user_data.email or "").strip().lower() or (clean_username.lower() if "@" in clean_username else None)
    new_user = User(
        username=clean_username,
        email=clean_email,
        hashed_password=AuthManager.hash_password(user_data.password),
    )
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}


@router.post("/auth/token", response_model=Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    from services.rate_limit import enforce_rate_limit, get_client_ip
    client_ip = get_client_ip(request)
    enforce_rate_limit("auth_login_ip", client_ip, limit=30, window_seconds=900, fail_closed_in_prod=True)
    enforce_rate_limit(
        "auth_login_user",
        f"{client_ip}:{(form_data.username or '').strip().lower()}",
        limit=15,
        window_seconds=900,
        fail_closed_in_prod=True,
    )

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not AuthManager.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = AuthManager.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/password-reset/request")
def request_password_reset(
    req_body: PasswordResetRequestBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Real password reset initiation:
    - Fails honestly with HTTP 503 if SMTP or canonical production PUBLIC_APP_URL is unconfigured.
    - Rate limited per IP and identifier (fail-closed in production if Redis is down).
    - Enumeration-safe identical response whether or not the account exists.
    - Stores only SHA-256 hashed single-use token with 30-minute expiry.
    - Deletes the token if SMTP delivery fails so no orphaned valid tokens remain.
    """
    import hashlib
    import secrets
    from datetime import timedelta
    from urllib.parse import quote
    from services.email import (
        is_password_reset_enabled,
        get_canonical_public_app_url,
        send_password_reset_email,
    )
    from services.rate_limit import enforce_rate_limit, get_client_ip
    from database.models import PasswordResetToken

    base_url = get_canonical_public_app_url()
    if not is_password_reset_enabled() or not base_url:
        raise HTTPException(
            status_code=503,
            detail="Password reset is disabled on this deployment because SMTP delivery or canonical HTTPS PUBLIC_APP_URL is not configured.",
        )

    client_ip = get_client_ip(request)
    clean_id = (req_body.identifier or "").strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Email or username is required.")

    enforce_rate_limit("auth_pw_reset_ip", client_ip, limit=10, window_seconds=900, fail_closed_in_prod=True)
    enforce_rate_limit("auth_pw_reset_id", clean_id.lower(), limit=5, window_seconds=900, fail_closed_in_prod=True)

    generic_response = {
        "message": "If an account exists for this email or username, a password reset link has been sent."
    }

    user = db.query(User).filter(
        (User.username == clean_id) | (User.email == clean_id.lower())
    ).first()
    if not user:
        return generic_response

    target_email = user.email or (user.username if "@" in user.username else None)
    if not target_email:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()
    reset_record = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        consumed_at=None,
    )
    db.add(reset_record)
    db.commit()

    reset_url = f"{base_url.rstrip('/')}/login?reset_token={quote(raw_token)}"
    try:
        send_password_reset_email(target_email, reset_url)
    except Exception:
        # Never leave a live reset token persisted when email delivery fails
        db.query(PasswordResetToken).filter(PasswordResetToken.id == reset_record.id).delete(synchronize_session=False)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Unable to deliver password reset email at this time. Please retry later.",
        )
    return generic_response


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(
    req_body: PasswordResetConfirmBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Atomically consumes a single-use hashed password reset token and updates the user's password.
    """
    import hashlib
    from services.rate_limit import enforce_rate_limit, get_client_ip
    from database.models import PasswordResetToken

    client_ip = get_client_ip(request)
    enforce_rate_limit("auth_pw_confirm_ip", client_ip, limit=15, window_seconds=900, fail_closed_in_prod=True)

    raw_token = (req_body.token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=400, detail="Reset token is required.")

    AuthManager.validate_password_strength(req_body.new_password)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()

    rec = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.consumed_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).first()
    if not rec:
        raise HTTPException(status_code=400, detail="Password reset token is invalid or expired.")

    rows = db.query(PasswordResetToken).filter(
        PasswordResetToken.id == rec.id,
        PasswordResetToken.consumed_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).update({PasswordResetToken.consumed_at: now}, synchronize_session=False)
    if rows != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="Password reset token has already been used or expired.")

    user = db.query(User).filter(User.id == rec.user_id).first()
    if not user:
        db.rollback()
        raise HTTPException(status_code=400, detail="Account not found.")

    user.hashed_password = AuthManager.hash_password(req_body.new_password)
    db.commit()
    return {"message": "Password updated successfully."}


@router.get("/auth/me/quotas")
def get_my_quotas(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns current UTC-day per-user usage quota counts and configured limits."""
    from services.quotas import get_user_quota_summary
    return get_user_quota_summary(db, current_user.id)


@router.delete("/auth/me")
def delete_my_account(
    body: AccountDeleteBody,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Self-service authenticated account deletion.
    Requires explicit confirmation ('DELETE') and current password verification.
    Cancels active jobs, purges workspaces & storage objects, removes DB data, and writes an audit record.
    """
    from services.account import delete_user_account

    if (body.confirm or "").strip() != "DELETE":
        raise HTTPException(status_code=400, detail="Explicit confirmation 'DELETE' is required.")
    if not AuthManager.verify_password(body.password or "", current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Current password verification failed.")

    return delete_user_account(db, current_user)


@router.post("/auth/me/export", status_code=202)
def request_my_data_export(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atomically persists UserDataExport, AccountAuditEvent, and BackgroundTask in a single
    database transaction, then enqueues the Redis notification strictly after commit.
    """
    from database.models import UserDataExport, AccountAuditEvent
    from tasks.worker import enqueue_task

    now = utc_now()
    exp = UserDataExport(
        id=uuid.uuid4(),
        user_id=current_user.id,
        status="QUEUED",
        created_at=now,
    )
    db.add(exp)
    db.add(
        AccountAuditEvent(
            id=uuid.uuid4(),
            subject_user_id=current_user.id,
            event_type="DATA_EXPORT_REQUESTED",
            details_json={"export_id": str(exp.id)},
            created_at=now,
        )
    )
    bg_task = TaskManager.create_task_in_session(
        db=db,
        user_id=current_user.id,
        task_type="user_data_export",
        title="Account Data Export",
        payload={"export_id": str(exp.id)},
    )
    db.commit()
    db.refresh(exp)
    db.refresh(bg_task)

    # Best-effort Redis push strictly after atomic DB commit (DB polling remains authoritative fallback)
    try:
        enqueue_task(bg_task.id)
    except Exception:
        pass

    data = exp.to_dict()
    data["task_id"] = str(bg_task.id)
    return data


@router.get("/auth/me/exports")
def list_my_data_exports(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Lists data export jobs owned by the authenticated user."""
    from database.models import UserDataExport
    from services.account import is_export_expired
    rows = db.query(UserDataExport).filter(
        UserDataExport.user_id == current_user.id
    ).order_by(UserDataExport.created_at.desc()).limit(20).all()
    changed = False
    for r in rows:
        if r.status == "COMPLETED" and is_export_expired(r):
            r.status = "EXPIRED"
            changed = True
    if changed:
        db.commit()
    return [r.to_dict() for r in rows]


@router.get("/auth/me/export/{export_id}")
def get_my_data_export(
    export_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns owner-verified status of a user data export, enforcing expiry truthfully."""
    from database.models import UserDataExport
    from services.account import is_export_expired
    try:
        exp_uuid = uuid.UUID(str(export_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid export ID.")
    exp = db.query(UserDataExport).filter(
        UserDataExport.id == exp_uuid,
        UserDataExport.user_id == current_user.id,
    ).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Data export not found.")
    if exp.status == "COMPLETED" and is_export_expired(exp):
        exp.status = "EXPIRED"
        db.commit()
    return exp.to_dict()


@router.get("/auth/me/export/{export_id}/download")
def download_my_data_export(
    export_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Downloads a completed, non-expired user-isolated data export archive."""
    from database.models import UserDataExport
    from services.account import is_export_expired, _enqueue_outbox_entry
    from services.storage import get_storage_backend, assert_user_storage_key

    try:
        exp_uuid = uuid.UUID(str(export_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid export ID.")
    exp = db.query(UserDataExport).filter(
        UserDataExport.id == exp_uuid,
        UserDataExport.user_id == current_user.id,
    ).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Data export not found.")

    if is_export_expired(exp):
        if exp.status != "EXPIRED":
            exp.status = "EXPIRED"
        if exp.storage_key:
            _enqueue_outbox_entry(
                db,
                storage_backend=exp.storage_backend or "local",
                storage_key=exp.storage_key,
                legacy_path=None,
                last_error="Export expired; scheduled for deletion",
            )
        db.commit()
        raise HTTPException(
            status_code=410,
            detail="Data export has expired and is no longer available for download.",
        )

    if exp.status != "COMPLETED" or not exp.storage_key:
        raise HTTPException(status_code=409, detail=f"Data export is not ready (status: {exp.status}).")

    assert_user_storage_key(current_user.id, exp.storage_key)
    storage = get_storage_backend(exp.storage_backend or "local")
    if not storage.exists(exp.storage_key):
        raise HTTPException(status_code=404, detail="Export archive not found in storage.")
    return storage.generate_download_response(
        exp.storage_key,
        filename=f"sakura_export_{str(exp.id)[:8]}.zip",
        mime_type="application/zip",
    )


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
    from services.quotas import enforce_user_quota
    enforce_user_quota(db, current_user.id, "file_upload")
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

@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(document_id: str, current_user: User = Depends(AuthManager.get_current_user), db: Session = Depends(get_db)):
    import services.documents as docs_svc
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document ID format")
    del_res = docs_svc.request_document_deletion(doc_uuid, current_user.id, db)
    if del_res.get("file"):
        await ws_manager.send_to_user(str(current_user.id), {
            "type": "library_update",
            "action": "updated",
            "data": del_res["file"],
        })
    return del_res

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
    try:
        conv_uuid = uuid.UUID(str(req.conversation_id).strip())
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid conversation ID format")

    conv = db.query(Conversation).filter(Conversation.id == conv_uuid, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    from services.quotas import enforce_user_quota
    enforce_user_quota(db, current_user.id, "chat")

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
            from coding.job_worker import (
                create_and_enqueue_coding_job,
                is_terminal_coding_status,
            )
            from database.models import CodingJob, CodingTaskEvent
            from services.quotas import enforce_user_quota

            is_replay = False
            if req.idempotency_key and req.idempotency_key.strip():
                is_replay = (
                    db.query(CodingJob)
                    .filter(
                        CodingJob.user_id == current_user.id,
                        CodingJob.idempotency_key == req.idempotency_key.strip()[:128],
                    )
                    .first()
                    is not None
                )
            if not is_replay:
                enforce_user_quota(db, current_user.id, "coding_task")

            coding_task, coding_job, _created = create_and_enqueue_coding_job(
                db=db,
                user=current_user,
                workspace=ws,
                title=f"Chat Coding: {code_objective[:40]}",
                objective=code_objective,
                intensity=req.intensity or "high",
                idempotency_key=req.idempotency_key,
                metadata={"source": "chat_stream", "conversation_id": str(conv.id)},
            )
            queued_task_id = str(coding_task.id)
            queued_job_id = str(coding_job.id)
            ws_uuid = ws.id
            ws_id_str = str(ws.id)
            ws_name = ws.name
            owner_id = current_user.id
            conv_id_val = conv.id
            req_msg_preview = req.message[:50] + ("..." if len(req.message) > 50 else "")
            events_stream_url = f"/api/v1/coding/tasks/{queued_task_id}/events/stream"
            queued_banner = f"*Queued durable coding task `{queued_task_id}` for workspace `{ws_name}`.*\n"

            # Persist the assistant message referencing the durable coding task immediately
            # so a page refresh or disconnect mid-task can recover and reconnect seamlessly.
            assistant_msg_rec = Message(
                conversation_id=conv_id_val,
                role="assistant",
                content=queued_banner,
                metadata_json={
                    "provider": "sakura_code",
                    "coding_task_id": queued_task_id,
                    "coding_job_id": queued_job_id,
                    "workspace_id": ws_id_str,
                    "workspace_name": ws_name,
                    "events_stream_url": events_stream_url,
                },
            )
            db.add(assistant_msg_rec)
            if conv.title.startswith("Chat with"):
                conv.title = req_msg_preview
            conv.updated_at = utc_now()
            db.commit()
            assistant_msg_id = assistant_msg_rec.id

            async def coding_stream_generator():
                full_response = queued_banner
                current_seq = 0
                is_terminal = False
                idle_count = 0
                queued_idle_count = 0
                is_test_env = os.getenv("ENVIRONMENT", "").lower() in ("test", "testing")
                max_idle_polls = 240  # 120s max idle wait while RUNNING
                max_queued_polls = 1 if is_test_env else 20  # bounded wait if still unclaimed in QUEUED

                yield f"data: {json.dumps({'token': queued_banner, 'provider': 'sakura_code', 'coding_task_id': queued_task_id, 'coding_job_id': queued_job_id, 'workspace_id': ws_id_str, 'workspace_name': ws_name, 'phase': 'QUEUED', 'events_stream_url': events_stream_url})}\n\n"

                from database.db import get_db_context
                try:
                    while not is_terminal and idle_count < max_idle_polls:
                        with get_db_context() as db_ctx:
                            evts = (
                                db_ctx.query(CodingTaskEvent)
                                .join(CodingJob, CodingTaskEvent.job_id == CodingJob.id)
                                .filter(
                                    CodingTaskEvent.task_id == queued_task_id,
                                    CodingTaskEvent.sequence_number > current_seq,
                                    CodingJob.user_id == owner_id,
                                    CodingJob.workspace_id == ws_uuid,
                                )
                                .order_by(CodingTaskEvent.sequence_number.asc())
                                .all()
                            )
                            if evts:
                                idle_count = 0
                                queued_idle_count = 0
                                for evt in evts:
                                    current_seq = evt.sequence_number
                                    chunk_msg = ""
                                    if evt.tool_name and evt.event_type == "tool_start":
                                        chunk_msg = f"\n`[{evt.phase}: {evt.tool_name}]`\n"
                                    elif is_terminal_coding_status(evt.phase):
                                        chunk_msg = f"\n\n### Coding Task Result: {evt.phase}\n\n{evt.message or evt.stdout_preview or ''}"
                                    elif evt.message:
                                        chunk_msg = f"*{evt.message}*\n"
                                    if chunk_msg:
                                        full_response += chunk_msg
                                        yield f"data: {json.dumps({'token': chunk_msg, 'provider': 'sakura_code', 'coding_task_id': queued_task_id, 'coding_job_id': queued_job_id, 'workspace_id': ws_id_str, 'workspace_name': ws_name, 'sequence_number': evt.sequence_number, 'phase': evt.phase, 'tool': evt.tool_name})}\n\n"
                                    if is_terminal_coding_status(evt.phase):
                                        is_terminal = True
                                        break
                            else:
                                idle_count += 1
                                job_rec = db_ctx.query(CodingJob).filter(
                                    CodingJob.task_id == queued_task_id,
                                    CodingJob.user_id == owner_id,
                                ).first()
                                if not job_rec or is_terminal_coding_status(job_rec.status):
                                    is_terminal = True
                                elif job_rec.status == "QUEUED":
                                    queued_idle_count += 1
                                    if queued_idle_count >= max_queued_polls:
                                        break

                        if not is_terminal:
                            await asyncio.sleep(0.05 if is_test_env else 0.5)
                finally:
                    # Update the persisted assistant message with streamed output & latest sequence
                    with get_db_context() as db_ctx:
                        msg_row = db_ctx.query(Message).filter_by(id=assistant_msg_id).first()
                        if msg_row:
                            msg_row.content = full_response
                            meta = dict(msg_row.metadata_json or {})
                            meta["last_sequence"] = current_seq
                            msg_row.metadata_json = meta
                        c = db_ctx.query(Conversation).filter_by(id=conv_id_val).first()
                        if c:
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

# WebSocket route (short-lived single-use tickets ONLY; query-string JWT tokens are forbidden)
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    ticket: Optional[str] = None,
):
    if not ticket:
        ticket = websocket.query_params.get("ticket")

    # Explicitly reject query-string JWT token fallback
    if not ticket or websocket.query_params.get("token"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_uuid = await asyncio.to_thread(AuthManager.consume_ws_ticket, ticket)
    if not user_uuid:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = str(user_uuid)

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

@router.delete("/tasks/clear_completed")
async def clear_completed_tasks(current_user: User = Depends(AuthManager.get_current_user)):
    TaskManager.clear_completed_tasks(current_user.id)
    user_tasks = [t.to_dict() for t in TaskManager.list_tasks(current_user.id)]
    await ws_manager.send_to_user(str(current_user.id), {"type": "tasks_list", "data": user_tasks})
    return {"status": "cleared"}

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


# ─── Image Generation & Editing Endpoints ─────────────────────────────────────

class ImageGenerateAPIRequest(BaseModel):
    prompt: str
    conversation_id: Optional[str] = None
    aspect_ratio: Optional[str] = "1:1"
    intensity: Optional[str] = "medium"
    requested_pipeline: Optional[str] = "auto"
    idempotency_key: Optional[str] = None

class ImageEditAPIRequest(BaseModel):
    parent_image_id: str
    edit_instruction: str
    conversation_id: Optional[str] = None
    intensity: Optional[str] = "medium"
    idempotency_key: Optional[str] = None

class ImageVariationAPIRequest(BaseModel):
    parent_image_id: str
    count: Optional[int] = 2
    conversation_id: Optional[str] = None
    intensity: Optional[str] = "medium"
    idempotency_key: Optional[str] = None

class ImageUpscaleAPIRequest(BaseModel):
    parent_image_id: str
    scale: Optional[int] = 2
    conversation_id: Optional[str] = None
    idempotency_key: Optional[str] = None

@router.post("/images/generate", status_code=202)
async def api_generate_image(
    req: ImageGenerateAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Enqueues a durable worker-backed text-to-image ImageGenerationJob with centralized quota enforcement."""
    from media.image_worker import create_image_generation_job
    if req.conversation_id:
        try:
            uuid.UUID(str(req.conversation_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation ID format.")
    try:
        job, created = create_image_generation_job(
            db=db,
            user_id=current_user.id,
            prompt=req.prompt,
            requested_pipeline=req.requested_pipeline or "auto",
            parameters={
                "aspect_ratio": req.aspect_ratio or "1:1",
                "intensity": req.intensity or "medium",
                "conversation_id": req.conversation_id,
                "workflow": "TEXT_TO_IMAGE",
            },
            idempotency_key=req.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    job_dict = job.to_dict()
    job_dict["idempotent_replay"] = not created
    return {
        "status": "queued",
        "job_id": str(job.id),
        "status_url": f"/api/v1/images/jobs/{job.id}",
        "job": job_dict,
    }

@router.post("/images/edit", status_code=202)
async def api_edit_image(
    req: ImageEditAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enqueues a durable worker-backed prompt-based variation ImageGenerationJob (reinterpretation,
    not pixel-level image-conditioned editing). Verifies parent image ownership and enforces image quota.
    """
    from media.image_worker import create_image_generation_job
    try:
        parent_id = uuid.UUID(req.parent_image_id)
        if req.conversation_id:
            uuid.UUID(req.conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    parent = db.query(GeneratedImage).filter(
        GeneratedImage.id == parent_id,
        GeneratedImage.user_id == current_user.id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent image not found.")

    try:
        job, created = create_image_generation_job(
            db=db,
            user_id=current_user.id,
            prompt=req.edit_instruction,
            requested_pipeline="edit",
            parameters={
                "parent_image_id": str(parent_id),
                "edit_instruction": req.edit_instruction,
                "conversation_id": req.conversation_id,
                "intensity": req.intensity or "medium",
                "workflow": "PROMPT_VARIATION",
            },
            idempotency_key=req.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    job_dict = job.to_dict()
    job_dict["idempotent_replay"] = not created
    return {
        "status": "queued",
        "job_id": str(job.id),
        "status_url": f"/api/v1/images/jobs/{job.id}",
        "workflow": "PROMPT_VARIATION",
        "image_conditioned_edit": False,
        "job": job_dict,
    }

@router.post("/images/variation", status_code=202)
async def api_variation_image(
    req: ImageVariationAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enqueues durable worker-backed prompt-variation ImageGenerationJobs with strict
    batch idempotency, request fingerprint validation (HTTP 409 on payload mismatch),
    and atomic batch quota reservation.
    """
    from media.image_worker import (
        create_batch_image_generation_jobs,
        compute_variation_request_fingerprint,
        IdempotencyConflictError,
    )
    clean_idem = (req.idempotency_key or "").strip()
    if not clean_idem:
        raise HTTPException(
            status_code=400,
            detail="idempotency_key is required for image variation requests.",
        )

    try:
        parent_id = uuid.UUID(req.parent_image_id)
        if req.conversation_id:
            uuid.UUID(req.conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    parent = db.query(GeneratedImage).filter(
        GeneratedImage.id == parent_id,
        GeneratedImage.user_id == current_user.id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent image not found.")

    count = max(1, min(int(req.count or 2), 4))
    intensity = (req.intensity or "medium").strip().lower()
    aspect_ratio = parent.aspect_ratio or "1:1"
    request_fp = compute_variation_request_fingerprint(
        parent_image_id=parent_id,
        count=count,
        conversation_id=req.conversation_id,
        aspect_ratio=aspect_ratio,
        intensity=intensity,
        requested_pipeline="auto",
    )
    specs = [
        {
            "prompt": f"{parent.prompt} (variation {i + 1})",
            "requested_pipeline": "auto",
            "parameters": {
                "parent_image_id": str(parent_id),
                "aspect_ratio": aspect_ratio,
                "intensity": intensity,
                "conversation_id": req.conversation_id,
                "workflow": "VARIATION",
            },
        }
        for i in range(count)
    ]
    try:
        jobs, created = create_batch_image_generation_jobs(
            db=db,
            user_id=current_user.id,
            job_specs=specs,
            idempotency_key=clean_idem,
            parent_image_id=parent_id,
            request_fingerprint=request_fp,
            require_idempotency_key=True,
        )
    except IdempotencyConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "queued",
        "workflow": "PROMPT_VARIATION",
        "idempotent_replay": not created,
        "jobs": [j.to_dict() for j in jobs],
    }

@router.post("/images/upscale", status_code=202)
async def api_upscale_image(
    req: ImageUpscaleAPIRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enqueues a durable worker-backed high-resolution prompt-based regeneration ImageGenerationJob
    (not pixel-level super-resolution upscaling). Verifies parent ownership and enforces image quota.
    """
    from media.image_worker import create_image_generation_job
    try:
        parent_id = uuid.UUID(req.parent_image_id)
        if req.conversation_id:
            uuid.UUID(req.conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format.")

    parent = db.query(GeneratedImage).filter(
        GeneratedImage.id == parent_id,
        GeneratedImage.user_id == current_user.id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Target image for regeneration not found.")

    job, created = create_image_generation_job(
        db=db,
        user_id=current_user.id,
        prompt=parent.prompt,
        requested_pipeline="upscale",
        parameters={
            "parent_image_id": str(parent_id),
            "scale": req.scale or 2,
            "aspect_ratio": parent.aspect_ratio or "1:1",
            "conversation_id": req.conversation_id,
            "intensity": "high",
            "workflow": "HIGH_RES_REGENERATION",
        },
        idempotency_key=req.idempotency_key,
    )
    job_dict = job.to_dict()
    job_dict["idempotent_replay"] = not created
    return {
        "status": "queued",
        "job_id": str(job.id),
        "status_url": f"/api/v1/images/jobs/{job.id}",
        "workflow": "HIGH_RES_REGENERATION",
        "true_upscale": False,
        "job": job_dict,
    }

class ImageJobCreateRequest(BaseModel):
    prompt: str
    requested_pipeline: Optional[str] = "auto"
    aspect_ratio: Optional[str] = "1:1"
    intensity: Optional[str] = "medium"
    conversation_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@router.post("/images/jobs", status_code=202)
def api_create_image_job(
    req: ImageJobCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a durable worker-backed ImageGenerationJob in QUEUED state with centralized quota enforcement."""
    from media.image_worker import create_image_generation_job
    if not (req.prompt or "").strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    if req.conversation_id:
        try:
            uuid.UUID(str(req.conversation_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation ID format.")

    try:
        job, created = create_image_generation_job(
            db=db,
            user_id=current_user.id,
            prompt=req.prompt,
            requested_pipeline=req.requested_pipeline or "auto",
            parameters={
                "aspect_ratio": req.aspect_ratio or "1:1",
                "intensity": req.intensity or "medium",
                "conversation_id": req.conversation_id,
            },
            idempotency_key=req.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    payload = job.to_dict()
    payload["idempotent_replay"] = not created
    return payload


@router.get("/images/jobs")
def api_list_image_jobs(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Lists durable image generation jobs owned by the authenticated user."""
    from database.models import ImageGenerationJob
    jobs = db.query(ImageGenerationJob).filter(
        ImageGenerationJob.user_id == current_user.id
    ).order_by(ImageGenerationJob.created_at.desc()).limit(50).all()
    return [j.to_dict() for j in jobs]


@router.get("/images/jobs/{job_id}")
def api_get_image_job(
    job_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns owner-verified status of a durable ImageGenerationJob."""
    from database.models import ImageGenerationJob, GeneratedImage
    try:
        j_uuid = uuid.UUID(str(job_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format.")

    job = db.query(ImageGenerationJob).filter(
        ImageGenerationJob.id == j_uuid,
        ImageGenerationJob.user_id == current_user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Image generation job not found.")

    data = job.to_dict()
    if job.output_image_id:
        img = db.query(GeneratedImage).filter(
            GeneratedImage.id == job.output_image_id,
            GeneratedImage.user_id == current_user.id,
        ).first()
        if img:
            data["output_image_url"] = img.image_url
    return data


@router.post("/images/jobs/{job_id}/cancel")
def api_cancel_image_job(
    job_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Cancels a queued or running ImageGenerationJob without overwriting terminal states."""
    from database.models import ImageGenerationJob, ImageGenerationJobStatus
    try:
        j_uuid = uuid.UUID(str(job_id).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format.")

    job = db.query(ImageGenerationJob).filter(
        ImageGenerationJob.id == j_uuid,
        ImageGenerationJob.user_id == current_user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Image generation job not found.")

    if job.status in (
        ImageGenerationJobStatus.COMPLETED,
        ImageGenerationJobStatus.FAILED,
        ImageGenerationJobStatus.CANCELLED,
    ):
        return job.to_dict()

    now = utc_now()
    job.cancel_requested = True
    if job.status == ImageGenerationJobStatus.QUEUED:
        job.status = ImageGenerationJobStatus.CANCELLED
        job.completed_at = now
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return job.to_dict()


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

