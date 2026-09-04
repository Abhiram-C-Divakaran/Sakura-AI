import asyncio
import os
import time
from typing import Dict, Any, Optional
from coding.security import WorkspaceSecurity, SecurityException

class SandboxExecutor:
    """
    Executes commands and tests in an isolated workspace subprocess with
    strict resource timeouts, environment sanitization, and output limits.
    """

    DEFAULT_TIMEOUT_SECONDS = 60
    MAX_OUTPUT_CHARS = 100000  # 100 KB output cap

    def __init__(self, workspace_root: str = ".", timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.default_timeout_seconds = timeout_seconds
        if not os.path.exists(self.workspace_root):
            os.makedirs(self.workspace_root, exist_ok=True)

    def execute(self, command, cwd: Optional[str] = None, timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Synchronous wrapper for run_command."""
        cmd_str = " ".join(command) if isinstance(command, list) else str(command)
        timeout = timeout_seconds or self.default_timeout_seconds
        return asyncio.run(self.run_command(cmd_str, cwd_relative=cwd, timeout_seconds=timeout))

    async def run_command(
        self,
        command: str,
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command"
    ) -> Dict[str, Any]:
        """
        Executes a shell command inside the workspace.
        """
        start_time = time.time()
        
        # 1. Validate command security
        try:
            WorkspaceSecurity.validate_command(command)
        except SecurityException as e:
            return {
                "success": False,
                "tool": tool_name,
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Security Error: {str(e)}",
                "duration_ms": 0
            }

        # 2. Determine execution directory
        if cwd_relative:
            try:
                run_cwd = WorkspaceSecurity.resolve_safe_path(self.workspace_root, cwd_relative)
            except SecurityException as e:
                return {
                    "success": False,
                    "tool": tool_name,
                    "command": command,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Working directory error: {str(e)}",
                    "duration_ms": 0
                }
        else:
            run_cwd = self.workspace_root

        # 3. Sanitize environment
        sanitized_env = WorkspaceSecurity.sanitize_environment()

        effective_timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds

        # 4. Launch subprocess
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=run_cwd,
                env=sanitized_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=effective_timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                duration_ms = int((time.time() - start_time) * 1000)
                return {
                    "success": False,
                    "tool": tool_name,
                    "command": command,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Command timed out after {effective_timeout} seconds.",
                    "duration_ms": duration_ms
                }

            duration_ms = int((time.time() - start_time) * 1000)
            stdout_str = stdout_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]
            stderr_str = stderr_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]
            exit_code = proc.returncode or 0

            return {
                "success": (exit_code == 0),
                "tool": tool_name,
                "command": command,
                "exit_code": exit_code,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "duration_ms": duration_ms
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "tool": tool_name,
                "command": command,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Subprocess execution error: {str(e)}",
                "duration_ms": duration_ms
            }
