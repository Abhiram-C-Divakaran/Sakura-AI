import os
import uuid
import shutil
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database.models import RepositoryWorkspace, User
from coding.tools import CodingToolchain
from coding.executor import SandboxExecutor

WORKSPACES_ROOT = os.path.realpath(os.path.abspath("./workspaces"))
os.makedirs(WORKSPACES_ROOT, exist_ok=True)

class WorkspaceManager:
    """Manages creation, allocation, and tracking of repository workspaces."""

    def __init__(self, db: Optional[Session] = None, user: Optional[User] = None, workspaces_root: Optional[str] = None):
        self.db = db
        self.user = user
        self.workspaces_root = os.path.realpath(os.path.abspath(workspaces_root)) if workspaces_root else WORKSPACES_ROOT
        os.makedirs(self.workspaces_root, exist_ok=True)

    def get_workspace(self, workspace_id: uuid.UUID) -> Optional[RepositoryWorkspace]:
        if not self.db or not self.user:
            return None
        return self.db.query(RepositoryWorkspace).filter(
            RepositoryWorkspace.id == workspace_id,
            RepositoryWorkspace.user_id == self.user.id
        ).first()

    async def create_workspace(
        self,
        name: str,
        repository_url: Optional[str] = None,
        branch: str = "main",
        clone_existing: bool = False
    ) -> Any:
        """Allocates an isolated workspace directory and persists record."""
        workspace_id = uuid.uuid4()
        workspace_dir = os.path.join(self.workspaces_root, str(workspace_id))
        os.makedirs(workspace_dir, exist_ok=True)

        status = "READY"
        base_commit = None

        if repository_url and clone_existing:
            executor = SandboxExecutor(workspace_dir)
            clone_res = await executor.run_command(f"git clone --depth 1 -b {branch} {repository_url} .")
            if not clone_res["success"]:
                status = "ERROR"
            else:
                rev_res = await executor.run_command("git rev-parse HEAD")
                if rev_res["success"]:
                    base_commit = rev_res["stdout"].strip()
        else:
            # Initialize git repository locally
            executor = SandboxExecutor(workspace_dir)
            await executor.run_command("git init")
            await executor.run_command("git config user.name 'Sakura AI'")
            await executor.run_command("git config user.email 'sakura@sakura.ai'")

        if not self.db or not self.user:
            return str(workspace_id), workspace_dir

        ws = RepositoryWorkspace(
            id=workspace_id,
            user_id=self.user.id,
            name=name,
            repository_url=repository_url,
            workspace_path=workspace_dir,
            active_branch=branch,
            base_commit=base_commit,
            status=status
        )
        self.db.add(ws)
        self.db.commit()
        self.db.refresh(ws)
        return ws

    def get_toolchain_for_workspace(self, workspace: RepositoryWorkspace) -> CodingToolchain:
        """Returns initialized CodingToolchain pointing to the workspace root."""
        return CodingToolchain(workspace.workspace_path)

    def delete_workspace(self, workspace_id: Any) -> bool:
        """Deletes workspace files and database record."""
        ws_id_str = str(workspace_id)
        ws_dir = os.path.join(self.workspaces_root, ws_id_str)
        if os.path.exists(ws_dir):
            try:
                shutil.rmtree(ws_dir)
            except Exception:
                pass

        if self.db:
            try:
                ws_uuid = uuid.UUID(ws_id_str) if not isinstance(workspace_id, uuid.UUID) else workspace_id
                ws = self.db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == ws_uuid).first()
                if ws:
                    self.db.delete(ws)
                    self.db.commit()
            except Exception:
                pass

        return not os.path.exists(ws_dir)
