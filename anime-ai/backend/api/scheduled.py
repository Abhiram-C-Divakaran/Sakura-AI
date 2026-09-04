import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.db import get_db
from database.models import User, ScheduledTask, ScheduledTaskRun
from auth.manager import AuthManager
from tasks.scheduler import execute_scheduled_task_run, compute_next_run
from database.models import utc_now

router = APIRouter(prefix="/scheduled", tags=["scheduled"])

class ScheduledTaskCreate(BaseModel):
    title: str
    prompt: str
    schedule: str
    timezone: Optional[str] = "UTC"
    enabled: Optional[bool] = True

class ScheduledTaskUpdate(BaseModel):
    title: Optional[str] = None
    prompt: Optional[str] = None
    schedule: Optional[str] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None

@router.get("", response_model=List[Dict[str, Any]])
def list_scheduled_tasks(
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all persistent scheduled tasks for authenticated user."""
    tasks = db.query(ScheduledTask).filter(
        ScheduledTask.user_id == current_user.id
    ).order_by(ScheduledTask.created_at.desc()).all()

    return [
        {
            "id": str(t.id),
            "title": t.title,
            "prompt": t.prompt,
            "schedule": t.schedule,
            "timezone": t.timezone,
            "enabled": t.enabled,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in tasks
    ]

@router.post("", response_model=Dict[str, Any])
def create_scheduled_task(
    req: ScheduledTaskCreate,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a new durable scheduled task with immediate next_run_at calculation."""
    title = req.title.strip()
    prompt = req.prompt.strip()
    if not title or not prompt:
        raise HTTPException(status_code=400, detail="Title and prompt are required.")

    is_enabled = req.enabled if req.enabled is not None else True
    tz = req.timezone or "UTC"
    next_run = compute_next_run(req.schedule, tz, utc_now()) if is_enabled else None

    task = ScheduledTask(
        id=uuid.uuid4(),
        user_id=current_user.id,
        title=title,
        prompt=prompt,
        schedule=req.schedule,
        timezone=tz,
        enabled=is_enabled,
        next_run_at=next_run
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return {
        "status": "success",
        "id": str(task.id),
        "title": task.title,
        "prompt": task.prompt,
        "schedule": task.schedule,
        "timezone": task.timezone,
        "enabled": task.enabled,
        "last_run_at": None,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "task": {
            "id": str(task.id),
            "title": task.title,
            "prompt": task.prompt,
            "schedule": task.schedule,
            "timezone": task.timezone,
            "enabled": task.enabled,
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None
        }
    }

@router.put("/{task_id}")
@router.patch("/{task_id}")
def update_scheduled_task(
    task_id: str,
    req: ScheduledTaskUpdate,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Updates a scheduled task and recalculates next_run_at."""
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = db.query(ScheduledTask).filter(
        ScheduledTask.id == t_uuid,
        ScheduledTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    if req.title is not None:
        task.title = req.title.strip()
    if req.prompt is not None:
        task.prompt = req.prompt.strip()
    if req.schedule is not None:
        task.schedule = req.schedule
    if req.timezone is not None:
        task.timezone = req.timezone
    if req.enabled is not None:
        task.enabled = req.enabled

    if task.enabled:
        task.next_run_at = compute_next_run(task.schedule, task.timezone, utc_now())
    else:
        task.next_run_at = None

    db.commit()
    db.refresh(task)
    return {
        "status": "success",
        "id": str(task.id),
        "enabled": task.enabled,
        "title": task.title,
        "schedule": task.schedule,
        "timezone": task.timezone,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None
    }

@router.delete("/{task_id}")
def delete_scheduled_task(
    task_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes a scheduled task."""
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = db.query(ScheduledTask).filter(
        ScheduledTask.id == t_uuid,
        ScheduledTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    db.delete(task)
    db.commit()
    return {"status": "deleted", "id": task_id}

@router.get("/{task_id}/runs", response_model=List[Dict[str, Any]])
def get_task_runs(
    task_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches execution history for a scheduled task."""
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = db.query(ScheduledTask).filter(
        ScheduledTask.id == t_uuid,
        ScheduledTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    runs = db.query(ScheduledTaskRun).filter(
        ScheduledTaskRun.task_id == task.id
    ).order_by(ScheduledTaskRun.started_at.desc()).limit(20).all()

    return [
        {
            "id": str(r.id),
            "task_id": str(r.task_id),
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error": r.error,
            "output": r.output,
            "duration_ms": r.duration_ms
        }
        for r in runs
    ]

@router.post("/{task_id}/run")
async def trigger_scheduled_task(
    task_id: str,
    current_user: User = Depends(AuthManager.get_current_user),
    db: Session = Depends(get_db)
):
    """Manually triggers real execution of a scheduled task."""
    try:
        t_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task = db.query(ScheduledTask).filter(
        ScheduledTask.id == t_uuid,
        ScheduledTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    # Run the scheduled task and record run outcome
    result = await execute_scheduled_task_run(task.id)

    return {
        "status": "triggered",
        "id": str(task.id),
        "title": task.title,
        "run_result": result
    }
