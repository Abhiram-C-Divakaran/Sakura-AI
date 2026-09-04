import os
import re
from typing import Dict, Any, Optional
from coding.executor import SandboxExecutor

class GitManager:
    """Provides high-level, safe Git operations for repository workspaces."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.executor = SandboxExecutor(workspace_root)

    async def status(self) -> Dict[str, Any]:
        """Returns structured git status."""
        res = await self.executor.run_command("git status --short", tool_name="git_status")
        return res

    async def diff(self, file_path: Optional[str] = None, cached: bool = False) -> Dict[str, Any]:
        """Returns unified diff of uncommitted or staged changes."""
        cmd = "git diff"
        if cached:
            cmd += " --cached"
        if file_path:
            # Validate path safety
            clean_path = file_path.replace('"', '').replace("'", "")
            cmd += f" -- {clean_path}"
        return await self.executor.run_command(cmd, tool_name="git_diff")

    async def log(self, max_count: int = 10) -> Dict[str, Any]:
        """Returns commit history."""
        cmd = f"git log -n {max(1, min(max_count, 50))} --oneline --decorate"
        return await self.executor.run_command(cmd, tool_name="git_log")

    async def show(self, commit_or_tag: str = "HEAD") -> Dict[str, Any]:
        """Shows commit details."""
        clean_target = re.sub(r"[^\w\-\./]", "", commit_or_tag)
        cmd = f"git show --stat {clean_target}"
        return await self.executor.run_command(cmd, tool_name="git_show")

    async def current_branch(self) -> str:
        """Returns the current active git branch."""
        res = await self.executor.run_command("git rev-parse --abbrev-ref HEAD", tool_name="git_branch")
        if res["success"] and res["stdout"].strip():
            return res["stdout"].strip()
        return "main"

    async def create_and_checkout_branch(self, branch_name: str) -> Dict[str, Any]:
        """Creates a temporary working branch for coding tasks."""
        safe_branch = re.sub(r"[^\w\-_/]", "", branch_name)
        cmd = f"git checkout -b {safe_branch}"
        return await self.executor.run_command(cmd, tool_name="git_checkout_branch")

    async def commit(self, message: str) -> Dict[str, Any]:
        """Stages all workspace changes and commits with descriptive message."""
        add_res = await self.executor.run_command("git add -A", tool_name="git_add")
        if not add_res["success"]:
            return add_res
        escaped_msg = message.replace('"', '\\"')
        cmd = f'git commit -m "{escaped_msg}"'
        return await self.executor.run_command(cmd, tool_name="git_commit")
