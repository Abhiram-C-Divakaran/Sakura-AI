import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.db import get_db, get_db_context
from database.models import User, RepositoryWorkspace, CodingTask, ToolExecution
from auth.manager import AuthManager
from coding.repository import WorkspaceManager
from coding.agent import CodingAgent
from coding.schemas import (
    WorkspaceCreateRequest,
    WorkspaceResponse,
    CodingTaskCreateRequest,
    ToolExecutionRequest,
    ToolExecutionResponse
)
from llm.router import LLMRouter

router = APIRouter(prefix="/coding", tags=["coding"])
llm_router = LLMRouter()

@router.post("/workspaces", response_model=Dict[str, Any])
async def create_workspace(
    req: WorkspaceCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Creates an isolated repository workspace for software engineering tasks."""
    mgr = WorkspaceManager(db, current_user)
    ws = await mgr.create_workspace(
        name=req.name,
        repository_url=req.repository_url,
        branch=req.branch or "main",
        clone_existing=req.clone_existing or False
    )
    return {
        "status": "success",
        "workspace": {
            "id": str(ws.id),
            "name": ws.name,
            "repository_url": ws.repository_url,
            "active_branch": ws.active_branch,
            "status": ws.status,
            "created_at": ws.created_at.isoformat() if ws.created_at else None
        }
    }

@router.get("/workspaces", response_model=List[Dict[str, Any]])
def list_workspaces(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all active coding workspaces owned by the user."""
    workspaces = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.user_id == current_user.id
    ).order_by(RepositoryWorkspace.created_at.desc()).all()

    return [
        {
            "id": str(w.id),
            "name": w.name,
            "repository_url": w.repository_url,
            "active_branch": w.active_branch,
            "status": w.status,
            "created_at": w.created_at.isoformat() if w.created_at else None
        }
        for w in workspaces
    ]

@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches details and current git status of a workspace."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == current_user.id
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    mgr = WorkspaceManager(db, current_user)
    toolchain = mgr.get_toolchain_for_workspace(ws)
    status_res = await toolchain.git_status()
    diff_res = await toolchain.git_diff()

    return {
        "id": str(ws.id),
        "name": ws.name,
        "repository_url": ws.repository_url,
        "active_branch": ws.active_branch,
        "status": ws.status,
        "git_status": status_res.get("stdout", ""),
        "uncommitted_changes": bool(diff_res.get("stdout", "").strip()),
        "created_at": ws.created_at.isoformat() if ws.created_at else None
    }

@router.get("/workspaces/{workspace_id}/diff")
async def get_workspace_diff(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Returns the live unified git diff of all modifications in the workspace."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == current_user.id
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    mgr = WorkspaceManager(db, current_user)
    toolchain = mgr.get_toolchain_for_workspace(ws)
    diff_res = await toolchain.git_diff()
    return {"workspace_id": workspace_id, "diff": diff_res.get("stdout", "")}

@router.post("/workspaces/{workspace_id}/tools", response_model=Dict[str, Any])
async def execute_workspace_tool(
    workspace_id: str,
    req: ToolExecutionRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Directly executes a single coding tool in the workspace."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == current_user.id
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    agent = CodingAgent(db, ws, current_user, llm_router)
    result = await agent.execute_tool(None, req.tool_name, req.arguments)
    return result

@router.post("/workspaces/{workspace_id}/tasks")
async def create_and_run_task(
    workspace_id: str,
    req: CodingTaskCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Launches an agentic coding task and streams execution updates."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == current_user.id
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    task = CodingTask(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=current_user.id,
        title=req.title,
        objective=req.objective,
        status="QUEUED"
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    agent = CodingAgent(db, ws, current_user, llm_router, intensity=req.intensity or "high")

    async def event_generator():
        import json
        async for update in agent.run_task_stream(task):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes workspace and all attached task logs."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    mgr = WorkspaceManager(db, current_user)
    deleted = mgr.delete_workspace(ws_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {"status": "deleted", "id": workspace_id}


class NetworkAuthorizationCreateRequest(BaseModel):
    command: str
    reason: Optional[str] = None


@router.post("/workspaces/{workspace_id}/network-authorizations", response_model=Dict[str, Any])
def create_workspace_network_authorization(
    workspace_id: str,
    req: NetworkAuthorizationCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a server-authoritative short-lived network authorization for a specific workspace and command."""
    try:
        ws_uuid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workspace ID")

    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == current_user.id
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    from coding.security import compute_command_hash
    from database.models import SandboxNetworkAuthorization, utc_now
    from datetime import timedelta

    cmd_hash = compute_command_hash(cmd)
    auth = SandboxNetworkAuthorization(
        id=uuid.uuid4(),
        user_id=current_user.id,
        workspace_id=ws.id,
        command_hash=cmd_hash,
        created_at=utc_now(),
        expires_at=utc_now() + timedelta(seconds=300),
        consumed_at=None
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)

    return {
        "status": "authorized",
        "authorization_id": str(auth.id),
        "command_hash": auth.command_hash,
        "expires_at": auth.expires_at.isoformat()
    }
