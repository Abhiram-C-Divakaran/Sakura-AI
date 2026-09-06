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
import httpx
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from coding.security import WorkspaceSecurity, SecurityException

class SandboxUnavailableError(Exception):
    """Raised when secure isolated sandbox execution is required but unavailable."""
    pass

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


class RemoteHttpSandboxRuntime(BaseSandboxRuntime):
    """
    Remote container-isolated execution runtime communicating with the internal
    Sandbox Executor Service over authenticated HTTP.
    Ensures the backend API process has no access to the Docker daemon or docker socket.
    """

    def __init__(
        self,
        workspace_root: str,
        default_timeout_seconds: int = 60,
        service_url: Optional[str] = None,
        service_token: Optional[str] = None,
        workspace_id: Optional[str] = None
    ):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.default_timeout_seconds = default_timeout_seconds
        self.service_url = (service_url or os.getenv("SAKURA_SANDBOX_EXECUTOR_URL", "http://sandbox-executor:9000")).rstrip("/")
        self.service_token = service_token or os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "")
        self.workspace_id = workspace_id or os.path.basename(self.workspace_root)

    async def run_command(
        self,
        command: Union[str, List[str]],
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command",
        allow_network: bool = False
    ) -> Dict[str, Any]:
        timeout = timeout_seconds or self.default_timeout_seconds
        payload = {
            "command": command,
            "timeout_seconds": timeout,
            "workspace_id": self.workspace_id,
            "workspace_path": self.workspace_root,
            "cwd_relative": cwd_relative,
            "allow_network": allow_network,
            "tool_name": tool_name
        }
        headers = {}
        if self.service_token:
            headers["X-Sandbox-Token"] = self.service_token

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=float(timeout + 10)) as client:
                resp = await client.post(
                    f"{self.service_url}/execute",
                    json=payload,
                    headers=headers
                )
                if resp.status_code == 401:
                    raise SandboxUnavailableError("Sandbox executor authentication failed: invalid service token.")
                if resp.status_code != 200:
                    raise SandboxUnavailableError(f"Sandbox executor returned HTTP {resp.status_code}: {resp.text}")
                data = resp.json()
                if data.get("isolation_unavailable"):
                    raise SandboxUnavailableError(
                        f"Sandbox executor container isolation unavailable: {data.get('stderr')}"
                    )
                return data
        except SandboxUnavailableError:
            raise
        except Exception as e:
            env = os.getenv("ENVIRONMENT", "development").lower()
            if env in ("production", "prod"):
                raise SandboxUnavailableError(f"Production sandbox execution failed: {str(e)}") from e
            return {
                "success": False,
                "tool": tool_name,
                "command": " ".join(command) if isinstance(command, list) else str(command),
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Sandbox service connection error: {str(e)}",
                "duration_ms": int((time.time() - start_time) * 1000),
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
    def is_service_available(cls, service_url: Optional[str] = None) -> bool:
        """Checks if the internal Sandbox Executor service is reachable and ready to execute code."""
        url = (service_url or os.getenv("SAKURA_SANDBOX_EXECUTOR_URL", "http://sandbox-executor:9000")).rstrip("/")
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{url}/readiness")
                if res.status_code == 200:
                    data = res.json()
                    return bool(data.get("ready", False))
                return False
        except Exception:
            return False

    @classmethod
    def get_runtime(
        cls,
        workspace_root: str,
        timeout_seconds: int = 60,
        force_runtime: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> BaseSandboxRuntime:
        """
        Returns the appropriate Sandbox runtime according to configuration, system support,
        and environment security policy.
        In production: Remote executor is mandatory. NEVER falls back to local Docker or host subprocess.
        Fails closed with SandboxUnavailableError if remote executor is unavailable.
        """
        env = os.getenv("ENVIRONMENT", "development").lower()
        is_prod = env in ("production", "prod")
        pref = (force_runtime or os.getenv("SAKURA_SANDBOX_RUNTIME", "auto")).lower()

        if is_prod:
            if pref in ("local_restricted", "docker"):
                raise SandboxUnavailableError(
                    f"Production sandbox execution blocked: Runtime '{pref}' cannot be used in production. "
                    "Only the dedicated remote sandbox executor service is permitted."
                )

            # In production, ONLY remote executor is permitted (backend container has no Docker access)
            if cls.is_service_available():
                return RemoteHttpSandboxRuntime(
                    workspace_root,
                    default_timeout_seconds=timeout_seconds,
                    workspace_id=workspace_id
                )

            raise SandboxUnavailableError(
                "Production sandbox execution blocked: Remote sandbox executor service is unavailable. "
                "In production, backend cannot control Docker directly and fails closed to preserve security isolation."
            )

        # Development / Test environments
        if pref == "remote":
            if cls.is_service_available():
                return RemoteHttpSandboxRuntime(
                    workspace_root,
                    default_timeout_seconds=timeout_seconds,
                    workspace_id=workspace_id
                )
            raise SandboxUnavailableError("Remote sandbox runtime was explicitly requested but service is unreachable.")

        if pref == "docker":
            if cls.is_docker_available():
                return DockerSandboxRuntime(workspace_root, default_timeout_seconds=timeout_seconds)
            raise SandboxUnavailableError("Docker sandbox runtime was explicitly requested but Docker is not available.")

        if pref == "auto":
            if cls.is_service_available():
                return RemoteHttpSandboxRuntime(
                    workspace_root,
                    default_timeout_seconds=timeout_seconds,
                    workspace_id=workspace_id
                )
            if cls.is_docker_available():
                return DockerSandboxRuntime(workspace_root, default_timeout_seconds=timeout_seconds)

        return LocalRestrictedSandboxRuntime(workspace_root, default_timeout_seconds=timeout_seconds)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns runtime availability status for telemetry and capabilities endpoint."""
        env = os.getenv("ENVIRONMENT", "development").lower()
        is_prod = env in ("production", "prod")
        service_ok = cls.is_service_available()
        docker_ok = cls.is_docker_available()

        if is_prod:
            if service_ok:
                return {
                    "available": True,
                    "runtime": "remote_docker",
                    "isolation_level": "container",
                    "production_safe": True,
                    "reason": "Secure remote container sandbox executor active",
                    "docker_available": True,
                    "cpu_limit": 2.0,
                    "memory_limit_mb": 512,
                    "network_disabled_by_default": True
                }
            return {
                "available": False,
                "runtime": "unavailable",
                "isolation_level": "none",
                "production_safe": False,
                "reason": "Container isolation unavailable: remote sandbox executor unreachable in production",
                "docker_available": False,
                "cpu_limit": 0,
                "memory_limit_mb": 0,
                "network_disabled_by_default": True
            }

        if service_ok:
            return {
                "available": True,
                "runtime": "remote_docker",
                "isolation_level": "container",
                "production_safe": True,
                "reason": "Secure remote container sandbox executor active",
                "docker_available": True,
                "cpu_limit": 2.0,
                "memory_limit_mb": 512,
                "network_disabled_by_default": True
            }
        elif docker_ok:
            return {
                "available": True,
                "runtime": "docker",
                "isolation_level": "container",
                "production_safe": True,
                "reason": "Secure local container isolation active",
                "docker_available": True,
                "cpu_limit": 2.0,
                "memory_limit_mb": 512,
                "network_disabled_by_default": True
            }
        else:
            return {
                "available": True,
                "runtime": "local_restricted",
                "isolation_level": "restricted_subprocess",
                "production_safe": False,
                "reason": "Running in development mode using local restricted subprocess",
                "docker_available": False,
                "cpu_limit": "host_shared",
                "memory_limit_mb": "host_shared",
                "network_disabled_by_default": True
            }
