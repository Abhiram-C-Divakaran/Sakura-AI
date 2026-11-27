import os
import stat
import uuid
import shutil
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from database.models import RepositoryWorkspace, User
from coding.tools import CodingToolchain
from coding.executor import SandboxExecutor
from coding.security import WorkspaceSecurity

logger = logging.getLogger("sakura.coding.repository")

SANDBOX_CHILD_UID = int(os.getenv("SAKURA_SANDBOX_UID", "1001"))
SANDBOX_CHILD_GID = int(os.getenv("SAKURA_SANDBOX_GID", "1001"))

# Never create directories on module import; resolve canonical path string lazily at runtime.
WORKSPACES_ROOT = os.path.realpath(os.path.abspath(os.getenv("SAKURA_WORKSPACE_ROOT", "./workspaces")))


def get_workspaces_root(override: Optional[str] = None) -> str:
    """Resolves canonical workspaces root path dynamically without import-time side effects."""
    raw = override or os.getenv("SAKURA_WORKSPACE_ROOT") or "./workspaces"
    return os.path.realpath(os.path.abspath(raw))


def apply_workspace_permissions(path: str, *, recursive: bool = False) -> None:
    """
    Applies the explicit workspace ownership/permission contract for POSIX hosts:
    - Owner/group set to UID/GID 1001 (the non-root sandbox child identity) when permitted.
    - Restrictive owner+group permissions (0770 for directories, 0660 for files) — NEVER world-writable (0777).
    """
    if os.name == "nt" or not os.path.exists(path):
        return

    def _apply_one(target: str, is_dir: bool) -> None:
        try:
            os.chown(target, SANDBOX_CHILD_UID, SANDBOX_CHILD_GID)
        except (PermissionError, OSError):
            pass
        try:
            os.chmod(target, 0o770 if is_dir else 0o660)
        except (PermissionError, OSError):
            pass

    _apply_one(path, os.path.isdir(path))
    if recursive and os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for d in dirs:
                _apply_one(os.path.join(root, d), True)
            for f in files:
                _apply_one(os.path.join(root, f), False)


class WorkspaceManager:
    """Manages creation, allocation, and tracking of repository workspaces."""

    def __init__(self, db: Optional[Session] = None, user: Optional[User] = None, workspaces_root: Optional[str] = None):
        self.db = db
        self.user = user
        self.workspaces_root = get_workspaces_root(workspaces_root)
        os.makedirs(self.workspaces_root, exist_ok=True)
        if os.name != "nt":
            try:
                # Ensure root allows group traversal (0750 or 0770), never world-writable
                mode = stat.S_IMODE(os.stat(self.workspaces_root).st_mode)
                if mode & stat.S_IWOTH:
                    os.chmod(self.workspaces_root, 0o770)
            except OSError:
                pass

    def get_workspace(self, workspace_id: uuid.UUID) -> Optional[RepositoryWorkspace]:
        if not self.db or not self.user:
            return None
        return self.db.query(RepositoryWorkspace).filter(
            RepositoryWorkspace.id == workspace_id,
            RepositoryWorkspace.user_id == self.user.id
        ).first()

    async def _provision_remote_workspace_if_configured(self, workspace_id: uuid.UUID) -> None:
        """
        When a remote sandbox executor is configured, provisions the workspace directory
        via POST /workspaces/{workspace_id} first so the shared volume receives proper
        1001:1001 (0770) ownership even on freshly mounted Docker named volumes.
        """
        remote_url = (
            os.getenv("SAKURA_SANDBOX_EXECUTOR_URL") or os.getenv("SAKURA_SANDBOX_URL") or ""
        ).strip().rstrip("/")
        if not remote_url:
            return
        token = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "").strip()
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{remote_url}/workspaces/{workspace_id}",
                    headers={"X-Sandbox-Token": token},
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Remote sandbox workspace provisioning returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
        except Exception as e:
            logger.warning(f"Remote sandbox workspace provisioning call failed for {workspace_id}: {e}")

    async def create_workspace(
        self,
        name: str,
        repository_url: Optional[str] = None,
        branch: str = "main",
        clone_existing: bool = False
    ) -> Any:
        """Allocates an isolated workspace directory and persists record."""
        workspace_id = uuid.uuid4()
        await self._provision_remote_workspace_if_configured(workspace_id)
        os.makedirs(self.workspaces_root, exist_ok=True)
        workspace_dir = os.path.realpath(os.path.join(self.workspaces_root, str(workspace_id)))
        if os.path.commonpath([workspace_dir, self.workspaces_root]) != self.workspaces_root or workspace_dir == self.workspaces_root:
            raise ValueError("Workspace directory escapes workspaces root.")
        os.makedirs(workspace_dir, exist_ok=True)
        apply_workspace_permissions(workspace_dir)

        status = "READY"
        base_commit = None

        # Validate branch name syntax
        WorkspaceSecurity.validate_branch_name(branch)

        if repository_url and clone_existing:
            # Validate URL to prevent shell/flag injection and SSRF
            WorkspaceSecurity.validate_repository_url(repository_url)

            executor = SandboxExecutor(workspace_dir, workspace_id=str(workspace_id))
            clone_cmd = ["git", "clone", "--depth", "1", "--branch", branch, repository_url, "."]
            from coding.capabilities import mint_sandbox_capability
            clone_capability = mint_sandbox_capability(
                workspace_id=str(workspace_id),
                command=clone_cmd,
                scope="repository_clone",
                repository_url=repository_url,
                branch=branch,
                ttl_seconds=180
            )
            clone_res = await executor.clone_repository(
                repository_url=repository_url,
                branch=branch,
                capability_token=clone_capability,
                timeout_seconds=180
            )
            if not clone_res["success"]:
                status = "ERROR"
            else:
                rev_res = await executor.run_command(["git", "rev-parse", "HEAD"])
                if rev_res["success"]:
                    base_commit = rev_res["stdout"].strip()
        else:
            # Initialize git repository locally
            executor = SandboxExecutor(workspace_dir, workspace_id=str(workspace_id))
            await executor.run_command(["git", "init"])
            await executor.run_command(["git", "config", "user.name", "Sakura AI"])
            await executor.run_command(["git", "config", "user.email", "sakura@sakura.ai"])

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
        """
        Deletes workspace directory and database record.
        Strictly enforces multi-user authorization: rejects deletion if the
        workspace belongs to a different user.
        """
        ws_id_str = str(workspace_id)
        try:
            ws_uuid = uuid.UUID(ws_id_str) if not isinstance(workspace_id, uuid.UUID) else workspace_id
        except ValueError:
            return False

        # If DB session and user are present, verify ownership before touching disk
        if self.db:
            query = self.db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == ws_uuid)
            if self.user:
                query = query.filter(RepositoryWorkspace.user_id == self.user.id)
            ws = query.first()
            if not ws:
                # Workspace does not exist or belongs to another user
                return False

            self.db.delete(ws)
            self.db.commit()

        # Only delete filesystem directory once authorization check passes
        ws_dir = os.path.join(self.workspaces_root, ws_id_str)
        if os.path.exists(ws_dir):
            try:
                shutil.rmtree(ws_dir)
            except Exception:
                pass

        return not os.path.exists(ws_dir)
