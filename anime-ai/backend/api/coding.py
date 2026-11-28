import uuid
import json
import asyncio
from datetime import timedelta
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database.db import get_db, get_db_context
from database.models import (
    User,
    RepositoryWorkspace,
    CodingTask,
    CodingJob,
    CodingTaskEvent,
    SandboxNetworkAuthorization,
    utc_now,
)
from auth.manager import AuthManager
from coding.repository import WorkspaceManager
from coding.agent import CodingAgent
from coding.job_worker import (
    create_and_enqueue_coding_job,
    append_coding_task_event,
    is_terminal_coding_status,
)
from coding.security import NetworkAccessPolicy, SecurityException, compute_command_hash
from coding.schemas import (
    WorkspaceCreateRequest,
    CodingTaskCreateRequest,
    ToolExecutionRequest,
)
from llm.router import LLMRouter

router = APIRouter(prefix="/coding", tags=["coding"])
llm_router = LLMRouter()


def _parse_uuid(raw_value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw_value).strip())
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")


def _resolve_owned_workspace(db: Session, workspace_id: str, user_id: uuid.UUID) -> RepositoryWorkspace:
    ws_uuid = _parse_uuid(workspace_id, "workspace ID")
    ws = db.query(RepositoryWorkspace).filter(
        RepositoryWorkspace.id == ws_uuid,
        RepositoryWorkspace.user_id == user_id,
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _resolve_owned_coding_task(
    db: Session,
    current_user: User,
    task_id: str,
    workspace_id: Optional[str] = None,
) -> Tuple[uuid.UUID, Optional[uuid.UUID], Optional[CodingJob], Optional[CodingTask]]:
    """
    Strictly validates UUID inputs and enforces multi-tenant ownership:
    - task_id must be a valid UUID (400 if malformed)
    - if workspace_id is supplied, it must be a valid UUID (400) and owned by current_user (404)
    - CodingJob / CodingTask must belong to current_user AND to workspace_id when supplied
    - Returns 404 without leaking resource existence on any ownership mismatch
    """
    task_uuid = _parse_uuid(task_id, "task ID")
    ws_uuid: Optional[uuid.UUID] = None

    if workspace_id is not None:
        ws_uuid = _parse_uuid(workspace_id, "workspace ID")
        ws = db.query(RepositoryWorkspace).filter(
            RepositoryWorkspace.id == ws_uuid,
            RepositoryWorkspace.user_id == current_user.id,
        ).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Coding task not found")

    job_query = db.query(CodingJob).filter(
        CodingJob.task_id == str(task_uuid),
        CodingJob.user_id == current_user.id,
    )
    task_query = db.query(CodingTask).filter(
        CodingTask.id == task_uuid,
        CodingTask.user_id == current_user.id,
    )
    if ws_uuid is not None:
        job_query = job_query.filter(CodingJob.workspace_id == ws_uuid)
        task_query = task_query.filter(CodingTask.workspace_id == ws_uuid)

    job = job_query.first()
    task = task_query.first()

    if not job and not task:
        raise HTTPException(status_code=404, detail="Coding task not found")

    return task_uuid, ws_uuid, job, task


@router.post("/workspaces", response_model=Dict[str, Any])
async def create_workspace(
    req: WorkspaceCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Creates an isolated repository workspace for software engineering tasks."""
    mgr = WorkspaceManager(db, current_user)
    ws = await mgr.create_workspace(
        name=req.name,
        repository_url=req.repository_url,
        branch=req.branch or "main",
        clone_existing=req.clone_existing or False,
    )
    return {
        "status": "success",
        "workspace": {
            "id": str(ws.id),
            "name": ws.name,
            "repository_url": ws.repository_url,
            "active_branch": ws.active_branch,
            "status": ws.status,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        },
    }


@router.get("/workspaces", response_model=List[Dict[str, Any]])
def list_workspaces(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
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
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in workspaces
    ]


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches details and current git status of a workspace."""
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)

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
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }


@router.get("/workspaces/{workspace_id}/diff")
async def get_workspace_diff(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the live unified git diff of all modifications in the workspace."""
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)

    mgr = WorkspaceManager(db, current_user)
    toolchain = mgr.get_toolchain_for_workspace(ws)
    diff_res = await toolchain.git_diff()
    return {"workspace_id": str(ws.id), "diff": diff_res.get("stdout", "")}


@router.post("/workspaces/{workspace_id}/tools", response_model=Dict[str, Any])
async def execute_workspace_tool(
    workspace_id: str,
    req: ToolExecutionRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Directly executes a single coding tool in the user's owned workspace."""
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)

    agent = CodingAgent(db, ws, current_user, llm_router)
    result = await agent.execute_tool(None, req.tool_name, req.arguments)
    return result


async def stream_coding_task_events(
    task_id: str,
    user_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = None,
    after_seq: int = 0,
    max_idle_polls: int = 240,
    poll_interval: float = 0.5,
):
    """
    Streams owner-scoped CodingTaskEvent records as Server-Sent Events with
    monotonic replay and case-insensitive terminal closure.
    Joins CodingTaskEvent against CodingJob to enforce ownership on every read.
    """
    current_seq = after_seq
    is_terminal = False
    idle_count = 0

    while not is_terminal and idle_count < max_idle_polls:
        with get_db_context() as db:
            evt_query = (
                db.query(CodingTaskEvent)
                .join(CodingJob, CodingTaskEvent.job_id == CodingJob.id)
                .filter(
                    CodingTaskEvent.task_id == str(task_id),
                    CodingTaskEvent.sequence_number > current_seq,
                    CodingJob.user_id == user_id,
                )
            )
            if workspace_id is not None:
                evt_query = evt_query.filter(CodingJob.workspace_id == workspace_id)

            evts = evt_query.order_by(CodingTaskEvent.sequence_number.asc()).all()

            if evts:
                idle_count = 0
                for evt in evts:
                    current_seq = evt.sequence_number
                    yield f"data: {json.dumps(evt.to_dict())}\n\n"
                    if is_terminal_coding_status(evt.phase):
                        is_terminal = True
                        break
            else:
                idle_count += 1
                job_query = db.query(CodingJob).filter(
                    CodingJob.task_id == str(task_id),
                    CodingJob.user_id == user_id,
                )
                if workspace_id is not None:
                    job_query = job_query.filter(CodingJob.workspace_id == workspace_id)
                job = job_query.first()
                if not job or is_terminal_coding_status(job.status):
                    is_terminal = True

        if not is_terminal:
            await asyncio.sleep(poll_interval)


@router.post("/workspaces/{workspace_id}/tasks")
async def create_and_run_task(
    workspace_id: str,
    req: CodingTaskCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates a CodingTask + durable CodingJob transactionally and enqueues it for
    the dedicated CodingJobWorker. Never spawns inline unclaimed execution.
    """
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)
    effective_idem = req.idempotency_key or idempotency_key

    task, job, created = create_and_enqueue_coding_job(
        db=db,
        user=current_user,
        workspace=ws,
        title=req.title,
        objective=req.objective,
        intensity=req.intensity or "high",
        idempotency_key=effective_idem,
        enforce_quota=True,
    )

    if req.stream:
        return StreamingResponse(
            stream_coding_task_events(
                task_id=str(task.id),
                user_id=current_user.id,
                workspace_id=ws.id,
                after_seq=0,
            ),
            media_type="text/event-stream",
        )

    return {
        "status": job.status,
        "taskId": str(task.id),
        "jobId": str(job.id),
        "workspaceId": str(ws.id),
        "idempotentReplay": not created,
    }


@router.get("/workspaces/{workspace_id}/tasks/{task_id}")
@router.get("/tasks/{task_id}")
def get_coding_task_status(
    task_id: str,
    workspace_id: Optional[str] = None,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Fetches owner-verified task status, modified files, and verification summary."""
    _task_uuid, _ws_uuid, job, task = _resolve_owned_coding_task(
        db=db,
        current_user=current_user,
        task_id=task_id,
        workspace_id=workspace_id,
    )

    if job:
        payload = job.to_dict()
        if task:
            payload["taskStatus"] = task.status
            payload["title"] = task.title
            payload["filesModified"] = task.files_modified or []
            payload["taskCompletedAt"] = task.completed_at.isoformat() if task.completed_at else None
        return payload

    return {
        "id": str(task.id),
        "taskId": str(task.id),
        "workspaceId": str(task.workspace_id),
        "userId": str(task.user_id),
        "status": task.status,
        "title": task.title,
        "instructions": task.objective,
        "filesModified": task.files_modified or [],
        "verificationState": task.verification_summary or {},
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/workspaces/{workspace_id}/tasks/{task_id}/events")
@router.get("/tasks/{task_id}/events")
def get_coding_task_events(
    task_id: str,
    workspace_id: Optional[str] = None,
    after_sequence: int = Query(0, ge=0),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns owner-verified persistent execution events joined against CodingJob."""
    task_uuid, ws_uuid, job, _task = _resolve_owned_coding_task(
        db=db,
        current_user=current_user,
        task_id=task_id,
        workspace_id=workspace_id,
    )

    evt_query = (
        db.query(CodingTaskEvent)
        .join(CodingJob, CodingTaskEvent.job_id == CodingJob.id)
        .filter(
            CodingTaskEvent.task_id == str(task_uuid),
            CodingTaskEvent.sequence_number > after_sequence,
            CodingJob.user_id == current_user.id,
        )
    )
    if ws_uuid is not None:
        evt_query = evt_query.filter(CodingJob.workspace_id == ws_uuid)

    events = evt_query.order_by(CodingTaskEvent.sequence_number.asc()).all()
    return [evt.to_dict() for evt in events]


@router.get("/workspaces/{workspace_id}/tasks/{task_id}/events/stream")
@router.get("/tasks/{task_id}/events/stream")
async def stream_coding_task_events_endpoint(
    task_id: str,
    workspace_id: Optional[str] = None,
    after_sequence: int = Query(0, ge=0),
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Owner-verified Server-Sent Events endpoint for real-time task log streaming."""
    task_uuid, ws_uuid, _job, _task = _resolve_owned_coding_task(
        db=db,
        current_user=current_user,
        task_id=task_id,
        workspace_id=workspace_id,
    )

    return StreamingResponse(
        stream_coding_task_events(
            task_id=str(task_uuid),
            user_id=current_user.id,
            workspace_id=ws_uuid,
            after_seq=after_sequence,
        ),
        media_type="text/event-stream",
    )


@router.post("/workspaces/{workspace_id}/tasks/{task_id}/cancel")
@router.post("/tasks/{task_id}/cancel")
def cancel_coding_task(
    task_id: str,
    workspace_id: Optional[str] = None,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Signals durable cancellation to a queued or running coding task.
    - Terminal jobs preserve their terminal state and are never overwritten.
    - QUEUED jobs transition atomically to CANCELLED and emit a CANCELLED event.
    - RUNNING jobs persist cancel_requested=True so the owning worker terminates active execution
      and finalizes cleanly under its lease fence (or transitions immediately if lease already expired).
    """
    task_uuid, ws_uuid, job, task = _resolve_owned_coding_task(
        db=db,
        current_user=current_user,
        task_id=task_id,
        workspace_id=workspace_id,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Coding task not found")

    if is_terminal_coding_status(job.status):
        return {
            "status": job.status,
            "taskId": str(task_uuid),
            "alreadyTerminal": True,
        }

    now = utc_now()
    if job.status == "QUEUED":
        rows = db.query(CodingJob).filter(
            CodingJob.id == job.id,
            CodingJob.status == "QUEUED",
        ).update(
            {
                CodingJob.cancel_requested: True,
                CodingJob.status: "CANCELLED",
                CodingJob.completed_at: now,
            },
            synchronize_session=False,
        )
        if rows == 1:
            if task:
                task.status = "CANCELLED"
                task.completed_at = now
                task.updated_at = now
            db.commit()
            append_coding_task_event(
                task_id=str(task_uuid),
                job_id=job.id,
                phase="CANCELLED",
                event_type="status",
                message="Queued task cancelled by user.",
            )
            return {"status": "CANCELLED", "taskId": str(task_uuid)}
        db.rollback()
        db.refresh(job)

    # Job is RUNNING: persist cancel_requested=True so the active worker terminates cooperatively.
    # If its lease is already expired (dead worker), atomically transition to CANCELLED.
    job.cancel_requested = True
    db.commit()

    expired_rows = db.query(CodingJob).filter(
        CodingJob.id == job.id,
        CodingJob.status == "RUNNING",
        or_(
            CodingJob.lease_expires_at.is_(None),
            CodingJob.lease_expires_at < now,
        ),
    ).update(
        {
            CodingJob.status: "CANCELLED",
            CodingJob.completed_at: now,
            CodingJob.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    if expired_rows == 1:
        if task:
            task.status = "CANCELLED"
            task.completed_at = now
            task.updated_at = now
        db.commit()
        append_coding_task_event(
            task_id=str(task_uuid),
            job_id=job.id,
            phase="CANCELLED",
            event_type="status",
            message="Task cancelled by user (expired lease).",
        )
        return {"status": "CANCELLED", "taskId": str(task_uuid)}

    db.commit()
    return {"status": "CANCELLING", "cancelRequested": True, "taskId": str(task_uuid)}


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes an owner-verified workspace and all attached task logs."""
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)

    mgr = WorkspaceManager(db, current_user)
    deleted = mgr.delete_workspace(ws.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {"status": "deleted", "id": str(ws.id)}


class NetworkAuthorizationCreateRequest(BaseModel):
    command: str
    reason: Optional[str] = None
    ttl_seconds: Optional[int] = 300


class NetworkCapabilityMintRequest(BaseModel):
    command: str
    ttl_seconds: Optional[int] = 60


@router.post("/workspaces/{workspace_id}/network-authorizations", response_model=Dict[str, Any])
def create_workspace_network_authorization(
    workspace_id: str,
    req: NetworkAuthorizationCreateRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a server-authoritative short-lived network authorization for a specific workspace and command."""
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)

    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    ttl = max(10, min(int(req.ttl_seconds or 300), 600))
    cmd_hash = compute_command_hash(cmd)
    now = utc_now()
    auth = SandboxNetworkAuthorization(
        id=uuid.uuid4(),
        user_id=current_user.id,
        workspace_id=ws.id,
        command_hash=cmd_hash,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
        consumed_at=None,
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)

    return {
        "status": "authorized",
        "authorization_id": str(auth.id),
        "workspace_id": str(ws.id),
        "command_hash": auth.command_hash,
        "scope": "network_exec",
        "expires_at": auth.expires_at.isoformat(),
    }


@router.post(
    "/workspaces/{workspace_id}/network-authorizations/{authorization_id}/mint",
    response_model=Dict[str, Any],
)
def mint_workspace_network_capability(
    workspace_id: str,
    authorization_id: str,
    req: NetworkCapabilityMintRequest,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifies and atomically consumes a SandboxNetworkAuthorization (checking user ownership,
    workspace ID, exact command hash, expiry, and non-consumption) and mints a short-lived
    HMAC-signed 'network_exec' capability token for the remote sandbox executor.
    """
    ws = _resolve_owned_workspace(db, workspace_id, current_user.id)
    auth_uuid = _parse_uuid(authorization_id, "authorization ID")

    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    ttl = max(10, min(int(req.ttl_seconds or 60), 180))
    try:
        capability_token = NetworkAccessPolicy.authorize_and_mint_capability(
            db=db,
            auth_id=auth_uuid,
            user_id=current_user.id,
            workspace_id=ws.id,
            command=cmd,
            ttl_seconds=ttl,
        )
    except SecurityException as e:
        raise HTTPException(status_code=403, detail=str(e))

    return {
        "status": "minted",
        "authorization_id": str(auth_uuid),
        "workspace_id": str(ws.id),
        "scope": "network_exec",
        "capability_token": capability_token,
        "ttl_seconds": ttl,
    }
