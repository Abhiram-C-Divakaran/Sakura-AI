"""
Sakura AI — Reusable Authorization & IDOR Protection Helpers

Enforces strict resource-ownership boundaries across workspaces, documents,
conversations, messages, projects, and generated media.
"""

import uuid
from typing import Union, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from database.models import (
    User,
    Document,
    Conversation,
    Message,
    Project,
    GeneratedImage,
    RepositoryWorkspace,
    CodingTask
)

def _to_uuid(val: Any) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid identifier format."
        )

def assert_workspace_owner(db: Session, workspace_id: Any, user_id: Any) -> RepositoryWorkspace:
    """Verifies that the workspace exists and belongs to the authenticated user."""
    ws_uuid = _to_uuid(workspace_id)
    u_uuid = _to_uuid(user_id)
    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == u_uuid
    ).first()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or access denied."
        )
    return ws

def assert_document_owner(db: Session, document_id: Any, user_id: Any) -> Document:
    """Verifies that the document exists and belongs to the authenticated user."""
    doc_uuid = _to_uuid(document_id)
    u_uuid = _to_uuid(user_id)
    doc = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.user_id == u_uuid
    ).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )
    return doc

def assert_conversation_owner(db: Session, conversation_id: Any, user_id: Any) -> Conversation:
    """Verifies that the conversation exists and belongs to the authenticated user."""
    conv_uuid = _to_uuid(conversation_id)
    u_uuid = _to_uuid(user_id)
    conv = db.query(Conversation).filter(
        Conversation.id == conv_uuid,
        Conversation.user_id == u_uuid
    ).first()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
    return conv

def assert_message_owner(db: Session, message_id: Any, user_id: Any) -> Message:
    """
    Verifies that the message exists and belongs to a conversation owned by
    the authenticated user.
    """
    msg_uuid = _to_uuid(message_id)
    u_uuid = _to_uuid(user_id)
    msg = db.query(Message).join(Conversation).filter(
        Message.id == msg_uuid,
        Conversation.user_id == u_uuid
    ).first()
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found or access denied."
        )
    return msg

def assert_project_owner(db: Session, project_id: Any, user_id: Any) -> Project:
    """Verifies that the project exists and belongs to the authenticated user."""
    proj_uuid = _to_uuid(project_id)
    u_uuid = _to_uuid(user_id)
    project = db.query(Project).filter(
        Project.id == proj_uuid,
        Project.user_id == u_uuid
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or access denied."
        )
    return project

def assert_image_owner(db: Session, image_id: Any, user_id: Any) -> GeneratedImage:
    """Verifies that the generated image exists and belongs to the authenticated user."""
    img_uuid = _to_uuid(image_id)
    u_uuid = _to_uuid(user_id)
    image = db.query(GeneratedImage).filter(
        GeneratedImage.id == img_uuid,
        GeneratedImage.user_id == u_uuid
    ).first()
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found or access denied."
        )
    return image

def assert_task_owner(db: Session, task_id: Any, user_id: Any) -> CodingTask:
    """Verifies that the coding task exists and belongs to the authenticated user."""
    task_uuid = _to_uuid(task_id)
    u_uuid = _to_uuid(user_id)
    task = db.query(CodingTask).filter(
        CodingTask.id == task_uuid,
        CodingTask.user_id == u_uuid
    ).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coding task not found or access denied."
        )
    return task
