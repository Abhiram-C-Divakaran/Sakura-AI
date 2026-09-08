import uuid
import json
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.db import get_db, get_db_context
from database.models import User, RepositoryWorkspace, CodingTask, CodingJob, CodingTaskEvent, ToolExecution, utc_now
from auth.manager import AuthManager
from coding.repository import WorkspaceManager
from coding.agent import CodingAgent
from coding.job_worker import CodingJobWorker, enqueue_coding_job
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

async def stream_coding_task_events(task_id: str, after_seq: int = 0):
    """Streams CodingTaskEvent records as Server-Sent Events with replay and terminal closure."""
    current_seq = after_seq
    terminal_phases = ["COMPLETED_VERIFIED", "COMPLETED_UNVERIFIED", "FAILED", "CANCELLED", "MAX_ITERATIONS"]
    is_terminal = False
    max_idle_polls = 120  # 60s idle timeout
    idle_count = 0

    while not is_terminal and idle_count < max_idle_polls:
        with get_db_context() as db:
            evts = db.query(CodingTaskEvent).filter(
                CodingTaskEvent.task_id == str(task_id),
                CodingTaskEvent.sequence_number > current_seq
            ).order_by(CodingTaskEvent.sequence_number.asc()).all()

            if evts:
                idle_count = 0
                for evt in evts:
                    current_seq = evt.sequence_number
                    yield f"data: {json.dumps(evt.to_dict())}\n\n"
                    if evt.phase in terminal_phases:
                        is_terminal = True
                        break
            else:
                idle_count += 1
                job = db.query(CodingJob).filter(CodingJob.task_id == str(task_id)).first()
                if job and job.status in terminal_phases:
                    is_terminal = True

        if not is_terminal:
            await asyncio.sleep(0.5)


@router.post("/workspaces/{workspace_id}/tasks")
async def create_and_run_task(
    workspace_id: str,
    req: CodingTaskCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Launches an agentic coding task backed by a durable CodingJob queue."""
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

    task_id = uuid.uuid4()
    task = CodingTask(
        id=task_id,
        workspace_id=ws.id,
        user_id=current_user.id,
        title=req.title,
        objective=req.objective,
        status="QUEUED"
    )

    job = CodingJob(
        id=uuid.uuid4(),
        task_id=str(task_id),
        workspace_id=ws.id,
        user_id=current_user.id,
        instructions=req.objective,
        status="QUEUED"
    )

    db.add(task)
    db.add(job)
    db.commit()
    db.refresh(task)
    db.refresh(job)

    # 1. Enqueue to durable Redis queue
    enqueued = enqueue_coding_job(str(task.id), job.id)

    # 2. In embedded mode or local dev, ensure execution starts immediately
    worker = CodingJobWorker(worker_id=f"api_worker_{uuid.uuid4().hex[:6]}")
    asyncio.create_task(worker.execute_job(job))

    if req.stream:
        return StreamingResponse(
            stream_coding_task_events(str(task.id), after_seq=0),
            media_type="text/event-stream"
        )

    return {
        "status": "QUEUED",
        "taskId": str(task.id),
        "jobId": str(job.id),
        "workspaceId": str(ws.id)
    }


@router.get("/workspaces/{workspace_id}/tasks/{task_id}")
@router.get("/tasks/{task_id}")
def get_coding_task_status(
    task_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches task status and verification summary."""
    job = db.query(CodingJob).filter(
        CodingJob.task_id == str(task_id),
        CodingJob.user_id == current_user.id
    ).first()

    task = db.query(CodingTask).filter(
        CodingTask.id == uuid.UUID(task_id),
        CodingTask.user_id == current_user.id
    ).first() if not job else None

    if not job and not task:
        raise HTTPException(status_code=404, detail="Coding task not found")

    if job:
        return job.to_dict()

    return {
        "id": str(task.id),
        "taskId": str(task.id),
        "workspaceId": str(task.workspace_id),
        "userId": str(task.user_id),
        "status": task.status,
        "title": task.title,
        "instructions": task.objective,
        "verificationState": task.verification_summary or {},
        "createdAt": task.created_at.isoformat() if task.created_at else None
    }


@router.get("/workspaces/{workspace_id}/tasks/{task_id}/events")
@router.get("/tasks/{task_id}/events")
def get_coding_task_events(
    task_id: str,
    after_sequence: int = Query(0, ge=0),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Returns persistent execution events for reconnect and audit."""
    events = db.query(CodingTaskEvent).filter(
        CodingTaskEvent.task_id == str(task_id),
        CodingTaskEvent.sequence_number > after_sequence
    ).order_by(CodingTaskEvent.sequence_number.asc()).all()

    return [evt.to_dict() for evt in events]


@router.get("/workspaces/{workspace_id}/tasks/{task_id}/events/stream")
@router.get("/tasks/{task_id}/events/stream")
async def stream_coding_task_events_endpoint(
    task_id: str,
    after_sequence: int = Query(0, ge=0),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Server-Sent Events endpoint for real-time task log streaming with reconnect replay."""
    return StreamingResponse(
        stream_coding_task_events(str(task_id), after_seq=after_sequence),
        media_type="text/event-stream"
    )


@router.post("/workspaces/{workspace_id}/tasks/{task_id}/cancel")
@router.post("/tasks/{task_id}/cancel")
def cancel_coding_task(
    task_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Signals cancellation to running or queued coding task."""
    job = db.query(CodingJob).filter(
        CodingJob.task_id == str(task_id),
        CodingJob.user_id == current_user.id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Coding task not found")

    job.cancel_requested = True
    if job.status in ["QUEUED", "RUNNING"]:
        job.status = "CANCELLED"
        job.completed_at = utc_now()

    task = db.query(CodingTask).filter(CodingTask.id == uuid.UUID(task_id)).first()
    if task:
        task.status = "CANCELLED"

    db.commit()
    return {"status": "cancelled", "taskId": str(task_id)}

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
