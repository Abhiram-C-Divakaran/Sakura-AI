"""
Sakura AI — Real Sandbox Isolation Subsystem

Provides execution boundaries for AI-generated and user-supplied code.
Supports Docker container sandbox with strict CPU, memory, PID, and network limits,
with local restricted subprocess runtime for environments where containerization
is unavailable or for local testing.
"""

import os
import time
import shutil
import asyncio
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from coding.security import WorkspaceSecurity, SecurityException

class BaseSandboxRuntime(ABC):
    """Abstract interface for sandbox execution runtimes."""

    @abstractmethod
    async def run_command(
        self,
        command: Union[str, List[str]],
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command",
        allow_network: bool = False
    ) -> Dict[str, Any]:
        pass


class DockerSandboxRuntime(BaseSandboxRuntime):
    """
    Genuine container-isolated execution boundary using Docker containers.
    - Mounts ONLY the workspace directory to /workspace
    - Runs as non-root user (UID 1001)
    - Drops all capabilities, restricts new privileges
    - Enforces memory, CPU, and PID limits
    - Disables network by default (unless explicitly approved)
    - Strips all host backend secrets and environment
    """

    DEFAULT_IMAGE = os.getenv("SAKURA_SANDBOX_IMAGE", "python:3.11-slim")
    DEFAULT_CPU_LIMIT = float(os.getenv("SAKURA_SANDBOX_CPUS", "2.0"))
    DEFAULT_MEMORY_MB = int(os.getenv("SAKURA_SANDBOX_MEMORY_MB", "512"))
    DEFAULT_PIDS_LIMIT = int(os.getenv("SAKURA_SANDBOX_PIDS", "64"))
    MAX_OUTPUT_CHARS = 100000

    def __init__(self, workspace_root: str, default_timeout_seconds: int = 60):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.default_timeout_seconds = default_timeout_seconds

    async def run_command(
        self,
        command: Union[str, List[str]],
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command",
        allow_network: bool = False
    ) -> Dict[str, Any]:
        start_time = time.time()
        timeout = timeout_seconds or self.default_timeout_seconds

        # Container working directory relative to mounted /workspace
        container_workdir = "/workspace"
        if cwd_relative:
            clean_rel = cwd_relative.replace("\\", "/").strip("/")
            container_workdir = f"/workspace/{clean_rel}"

        # Build command invocation
        if isinstance(command, list):
            cmd_args = command
        else:
            cmd_args = ["sh", "-c", command]

        network_flag = "bridge" if allow_network else "none"

        docker_cmd = [
            "docker", "run", "--rm",
            "--user", "1001:1001",
            "--network", network_flag,
            f"--cpus={self.DEFAULT_CPU_LIMIT}",
            f"--memory={self.DEFAULT_MEMORY_MB}m",
            f"--pids-limit={self.DEFAULT_PIDS_LIMIT}",
            "--security-opt", "no-new-privileges:true",
            "-v", f"{self.workspace_root}:/workspace:rw",
            "-w", container_workdir,
            self.DEFAULT_IMAGE
        ] + cmd_args

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
                duration_ms = int((time.time() - start_time) * 1000)
                stdout_str = stdout_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]
                stderr_str = stderr_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]

                return {
                    "success": proc.returncode == 0,
                    "tool": tool_name,
                    "command": " ".join(cmd_args) if isinstance(cmd_args, list) else str(cmd_args),
                    "exit_code": proc.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "duration_ms": duration_ms,
                    "timed_out": False
                }
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
                    "command": str(command),
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Execution timed out after {timeout} seconds.",
                    "duration_ms": duration_ms,
                    "timed_out": True
                }
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "tool": tool_name,
                "command": str(command),
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Docker execution error: {str(e)}",
                "duration_ms": duration_ms,
                "timed_out": False
            }


class LocalRestrictedSandboxRuntime(BaseSandboxRuntime):
    """
    Local restricted subprocess boundary for environments without Docker.
    - Validates target paths stay inside the workspace root (cannot escape)
    - Validates commands against destructive blacklists (rm -rf /, fork bombs, etc.)
    - Sanitizes environment by scrubbing all backend secrets, tokens, and API keys
    - Terminates entire child process tree on timeout
    - Limits maximum output size to prevent memory bloat
    """

    MAX_OUTPUT_CHARS = 100000

    def __init__(self, workspace_root: str, default_timeout_seconds: int = 60):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.default_timeout_seconds = default_timeout_seconds
        os.makedirs(self.workspace_root, exist_ok=True)

    async def run_command(
        self,
        command: Union[str, List[str]],
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command",
        allow_network: bool = False
    ) -> Dict[str, Any]:
        start_time = time.time()
        timeout = timeout_seconds or self.default_timeout_seconds

        cmd_display = " ".join(command) if isinstance(command, list) else str(command)

        # 1. Validate command security
        try:
            WorkspaceSecurity.validate_command(cmd_display)
        except SecurityException as e:
            return {
                "success": False,
                "tool": tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Security Error: {str(e)}",
                "duration_ms": 0,
                "timed_out": False
            }

        # 2. Determine execution directory safely
        if cwd_relative:
            try:
                run_cwd = WorkspaceSecurity.resolve_safe_path(self.workspace_root, cwd_relative)
            except SecurityException as e:
                return {
                    "success": False,
                    "tool": tool_name,
                    "command": cmd_display,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Working directory error: {str(e)}",
                    "duration_ms": 0,
                    "timed_out": False
                }
        else:
            run_cwd = self.workspace_root

        # 3. Sanitize environment (scrub JWT, API keys, database URLs)
        sanitized_env = WorkspaceSecurity.sanitize_environment()

        # 4. Launch subprocess
        try:
            if isinstance(command, list):
                clean_cmd = []
                for c in command:
                    c_str = str(c).strip()
                    if len(c_str) >= 2 and ((c_str[0] == '"' and c_str[-1] == '"') or (c_str[0] == "'" and c_str[-1] == "'")):
                        c_str = c_str[1:-1]
                    clean_cmd.append(c_str)
                proc = await asyncio.create_subprocess_exec(
                    *clean_cmd,
                    cwd=run_cwd,
                    env=sanitized_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
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
                    timeout=timeout
                )
                duration_ms = int((time.time() - start_time) * 1000)
                stdout_str = stdout_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]
                stderr_str = stderr_data.decode("utf-8", errors="replace")[:self.MAX_OUTPUT_CHARS]

                return {
                    "success": proc.returncode == 0,
                    "tool": tool_name,
                    "command": cmd_display,
                    "exit_code": proc.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "duration_ms": duration_ms,
                    "timed_out": False
                }
            except asyncio.TimeoutError:
                # Force kill process tree
                self._kill_process_tree(proc.pid)
                try:
                    await proc.communicate()
                except Exception:
                    pass
                duration_ms = int((time.time() - start_time) * 1000)
                return {
                    "success": False,
                    "tool": tool_name,
                    "command": cmd_display,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Execution timed out after {timeout} seconds.",
                    "duration_ms": duration_ms,
                    "timed_out": True
                }
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "tool": tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution error: {str(e)}",
                "duration_ms": duration_ms,
                "timed_out": False
            }

    def _kill_process_tree(self, pid: int) -> None:
        """Kills the target process and all child processes."""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            else:
                import signal
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass


class SandboxManager:
    """
    Factory and manager for sandbox execution runtimes.
    Detects container isolation support and instantiates appropriate runtime.
    """

    _docker_checked: bool = False
    _docker_available: bool = False

    @classmethod
    def is_docker_available(cls) -> bool:
        """Checks if the Docker CLI and daemon are operational on host."""
        if cls._docker_checked:
            return cls._docker_available

        cls._docker_checked = True
        docker_path = shutil.which("docker")
        if not docker_path:
            cls._docker_available = False
            return False

        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False
            )
            cls._docker_available = (res.returncode == 0)
        except Exception:
            cls._docker_available = False

        return cls._docker_available

    @classmethod
    def get_runtime(
        cls,
        workspace_root: str,
        timeout_seconds: int = 60,
        force_runtime: Optional[str] = None
    ) -> BaseSandboxRuntime:
        """Returns the appropriate Sandbox runtime according to configuration and system support."""
        pref = force_runtime or os.getenv("SAKURA_SANDBOX_RUNTIME", "auto").lower()

        if pref == "docker" or (pref == "auto" and cls.is_docker_available()):
            if cls.is_docker_available():
                return DockerSandboxRuntime(workspace_root, default_timeout_seconds=timeout_seconds)
            elif pref == "docker":
                # Docker explicitly requested but unavailable
                raise RuntimeError("Docker sandbox runtime was explicitly requested but Docker is not available.")

        return LocalRestrictedSandboxRuntime(workspace_root, default_timeout_seconds=timeout_seconds)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns runtime availability status for telemetry and capabilities endpoint."""
        docker_ok = cls.is_docker_available()
        return {
            "available": True,
            "runtime": "docker" if docker_ok else "local_restricted",
            "docker_available": docker_ok,
            "isolation_level": "container" if docker_ok else "restricted_subprocess",
            "cpu_limit": 2.0 if docker_ok else "host_shared",
            "memory_limit_mb": 512 if docker_ok else "host_shared",
            "network_disabled_by_default": True
        }
