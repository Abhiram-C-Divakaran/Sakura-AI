from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class WorkspaceCreateRequest(BaseModel):
    name: str
    repository_url: Optional[str] = None
    branch: Optional[str] = "main"
    clone_existing: Optional[bool] = False

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    repository_url: Optional[str] = None
    active_branch: str
    status: str
    created_at: str

class CodingTaskCreateRequest(BaseModel):
    title: str
    objective: str
    intensity: Optional[str] = "high"
    stream: Optional[bool] = False

class ToolExecutionRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]

class ToolExecutionResponse(BaseModel):
    success: bool
    tool: str
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: int = 0
    data: Optional[Dict[str, Any]] = None
