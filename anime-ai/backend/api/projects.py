import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.db import get_db
from database.models import User, Project, ProjectRepository, ProjectFile, ProjectConversation, Conversation, Document
from auth.manager import AuthManager

router = APIRouter(prefix="/projects", tags=["projects"])

class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    instructions: Optional[str] = ""

class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None

class AttachRepoRequest(BaseModel):
    repository_url: str
    name: str
    branch: Optional[str] = "main"

class AttachFileRequest(BaseModel):
    document_id: str

@router.get("", response_model=List[Dict[str, Any]])
def list_projects(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all projects owned by authenticated user."""
    projects = db.query(Project).filter(Project.user_id == current_user.id).order_by(Project.created_at.desc()).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "instructions": p.instructions,
            "repositories_count": len(p.repositories),
            "files_count": len(p.files),
            "conversations_count": len(p.conversations),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None
        }
        for p in projects
    ]

@router.post("", response_model=Dict[str, Any])
def create_project(
    req: ProjectCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a new project workspace container."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")

    project = Project(
        id=uuid.uuid4(),
        user_id=current_user.id,
        name=name,
        description=req.description or "",
        instructions=req.instructions or ""
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "status": "success",
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "instructions": project.instructions,
        "repositories_count": 0,
        "files_count": 0,
        "conversations_count": 0,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "instructions": project.instructions,
            "created_at": project.created_at.isoformat() if project.created_at else None
        }
    }

@router.get("/{project_id}")
def get_project(
    project_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches project details along with attached resources."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "instructions": project.instructions,
        "repositories": [
            {"id": str(r.id), "name": r.name, "url": r.repository_url, "branch": r.branch}
            for r in project.repositories
        ],
        "files": [
            {"id": str(f.id), "document_id": str(f.document_id), "filename": f.document.filename if f.document else "Unknown"}
            for f in project.files
        ],
        "conversations": [
            {"id": str(c.id), "conversation_id": str(c.conversation_id), "title": c.conversation.title if c.conversation else "Conversation"}
            for c in project.conversations
        ],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None
    }

@router.put("/{project_id}")
def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Updates project metadata or system instructions."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if req.name is not None:
        project.name = req.name.strip()
    if req.description is not None:
        project.description = req.description
    if req.instructions is not None:
        project.instructions = req.instructions

    db.commit()
    db.refresh(project)
    return {"status": "success", "id": str(project.id)}

@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes project and its attachments."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(project)
    db.commit()
    return {"status": "deleted", "id": project_id}

@router.post("/{project_id}/repositories")
def attach_repository(
    project_id: str,
    req: AttachRepoRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Attaches a GitHub or Git repository link to project."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_record = ProjectRepository(
        id=uuid.uuid4(),
        project_id=project.id,
        repository_url=req.repository_url,
        name=req.name,
        branch=req.branch or "main"
    )
    db.add(repo_record)
    db.commit()
    return {"status": "success", "id": str(repo_record.id)}

@router.post("/{project_id}/files")
def attach_file(
    project_id: str,
    req: AttachFileRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Attaches a library document to project context."""
    try:
        p_uuid = uuid.UUID(project_id)
        doc_uuid = uuid.UUID(req.document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = db.query(Document).filter(Document.id == doc_uuid, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or access denied")

    pf = ProjectFile(id=uuid.uuid4(), project_id=project.id, document_id=doc.id)
    db.add(pf)
    db.commit()
    return {"status": "success", "id": str(pf.id)}

@router.post("/{project_id}/conversations")
def start_project_conversation(
    project_id: str,
    req: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Starts or links a conversation within this project workspace."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = req or {}
    title = payload.get("title") or f"Chat on {project.name}"
    
    conv = Conversation(
        id=uuid.uuid4(),
        user_id=current_user.id,
        title=title,
        character_id="sakura"
    )
    db.add(conv)
    db.flush()

    p_conv = ProjectConversation(
        id=uuid.uuid4(),
        project_id=project.id,
        conversation_id=conv.id
    )
    db.add(p_conv)
    db.commit()

    return {
        "status": "success",
        "id": str(conv.id),
        "conversation_id": str(conv.id),
        "title": conv.title,
        "project_id": str(project.id)
    }

@router.get("/{project_id}/conversations")
def list_project_conversations(
    project_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Lists conversations attached to this project."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return [
        {
            "id": str(c.conversation.id),
            "title": c.conversation.title,
            "created_at": c.created_at.isoformat() if c.created_at else None
        }
        for c in project.conversations if c.conversation
    ]
