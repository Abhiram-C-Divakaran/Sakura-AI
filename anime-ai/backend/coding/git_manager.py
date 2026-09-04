"""
Sakura AI — Safe Git Manager

Executes Git operations using subprocess argument arrays without shell interpolation,
eliminating command injection vulnerabilities.
"""

import os
import re
from typing import Dict, Any, Optional
from coding.executor import SandboxExecutor
from coding.security import WorkspaceSecurity

class GitManager:
    """Provides high-level, safe Git operations for repository workspaces."""

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.executor = SandboxExecutor(self.workspace_root)

    async def status(self) -> Dict[str, Any]:
        """Returns structured git status."""
        return await self.executor.run_command(["git", "status", "--short"], tool_name="git_status")

    async def diff(self, file_path: Optional[str] = None, cached: bool = False) -> Dict[str, Any]:
        """Returns unified diff of uncommitted or staged changes."""
        cmd = ["git", "diff"]
        if cached:
            cmd.append("--cached")
        if file_path:
            # Ensure path does not escape workspace
            safe_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, file_path)
            rel_path = os.path.relpath(safe_path, self.workspace_root).replace("\\", "/")
            cmd.extend(["--", rel_path])
        return await self.executor.run_command(cmd, tool_name="git_diff")

    async def log(self, max_count: int = 10) -> Dict[str, Any]:
        """Returns commit history."""
        safe_count = max(1, min(int(max_count), 50))
        cmd = ["git", "log", "-n", str(safe_count), "--oneline", "--decorate"]
        return await self.executor.run_command(cmd, tool_name="git_log")

    async def show(self, commit_or_tag: str = "HEAD") -> Dict[str, Any]:
        """Shows commit details."""
        clean_target = re.sub(r"[^\w\-\./]", "", commit_or_tag) or "HEAD"
        cmd = ["git", "show", "--stat", clean_target]
        return await self.executor.run_command(cmd, tool_name="git_show")

    async def current_branch(self) -> str:
        """Returns the current active git branch."""
        res = await self.executor.run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], tool_name="git_branch")
        if res["success"] and res["stdout"].strip():
            return res["stdout"].strip()
        return "main"

    async def create_and_checkout_branch(self, branch_name: str) -> Dict[str, Any]:
        """Creates a temporary working branch for coding tasks."""
        WorkspaceSecurity.validate_branch_name(branch_name)
        cmd = ["git", "checkout", "-b", branch_name]
        return await self.executor.run_command(cmd, tool_name="git_checkout_branch")

    async def commit(self, message: str) -> Dict[str, Any]:
        """Stages all workspace changes and commits with descriptive message."""
        add_res = await self.executor.run_command(["git", "add", "-A"], tool_name="git_add")
        if not add_res["success"]:
            return add_res
        cmd = ["git", "commit", "-m", str(message)]
        return await self.executor.run_command(cmd, tool_name="git_commit")
