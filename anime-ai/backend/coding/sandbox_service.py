"""
Sakura AI — Dedicated Sandbox Executor Service
Internal service exposing authenticated HTTP endpoints for isolated code execution.
Runs as a standalone service with access to Docker daemon (the main backend API container
does NOT have Docker daemon access).
"""

import os
import re
import uuid
import time
import shutil
import hmac
import asyncio
import subprocess
from typing import Dict, Any, Optional, List, Union, Tuple
from fastapi import FastAPI, Header, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from coding.security import WorkspaceSecurity, SecurityException

app = FastAPI(
    title="Sakura Sandbox Executor Service",
    description="Internal isolated execution boundary service",
    version="1.0.0"
)

# Configuration from environment
SERVICE_TOKEN = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "")
SANDBOX_IMAGE = os.getenv("SAKURA_SANDBOX_IMAGE", "python:3.11-slim")
CPU_LIMIT = float(os.getenv("SAKURA_SANDBOX_CPUS", "2.0"))
MEMORY_MB = int(os.getenv("SAKURA_SANDBOX_MEMORY_MB", "512"))
PIDS_LIMIT = int(os.getenv("SAKURA_SANDBOX_PIDS", "64"))
CAPTURE_LIMIT_BYTES = int(os.getenv("SAKURA_CAPTURE_LIMIT_BYTES", str(512 * 1024)))      # 512 KiB
HARD_OUTPUT_LIMIT_BYTES = int(os.getenv("SAKURA_HARD_OUTPUT_LIMIT_BYTES", str(5 * 1024 * 1024))) # 5 MiB
MAX_OUTPUT_BYTES = CAPTURE_LIMIT_BYTES
import tempfile

default_ws_root = os.getenv("SAKURA_WORKSPACE_ROOT")
if not default_ws_root:
    if os.path.exists("/workspaces") and os.access("/workspaces", os.W_OK):
        default_ws_root = "/workspaces"
    elif os.name != "nt" and not os.access("/", os.W_OK):
        default_ws_root = os.path.join(tempfile.gettempdir(), "sakura_workspaces")
    else:
        default_ws_root = "/workspaces"
WORKSPACE_ROOT = os.path.realpath(os.path.abspath(default_ws_root))
WORKSPACES_VOLUME = os.getenv("SAKURA_WORKSPACES_VOLUME", "")

try:
    os.makedirs(WORKSPACE_ROOT, exist_ok=True)
except (PermissionError, OSError):
    pass

_readiness_cache: Dict[str, Any] = {"last_check": 0.0, "result": None}


def check_docker_operational() -> bool:
    """Checks if the Docker CLI and daemon are operational on host."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False
        )
        return res.returncode == 0
    except Exception:
        return False


def get_volume_host_mountpoint(volume_name: str) -> Optional[str]:
    """Inspects Docker volume mountpoint on host if running in Docker."""
    if not volume_name or not check_docker_operational():
        return None
    try:
        res = subprocess.run(
            ["docker", "volume", "inspect", volume_name, "--format", "{{ .Mountpoint }}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def verify_service_token(
    x_sandbox_token: Optional[str] = Header(None, alias="X-Sandbox-Token"),
    authorization: Optional[str] = Header(None)
) -> bool:
    """
    Validates internal service authentication token via constant-time comparison.
    Accepts token from X-Sandbox-Token or Authorization: Bearer <token>.
    """
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ("production", "prod")

    provided_token = x_sandbox_token
    if not provided_token and authorization:
        if authorization.startswith("Bearer "):
            provided_token = authorization[7:].strip()
        else:
            provided_token = authorization.strip()

    expected_token = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", SERVICE_TOKEN).strip()

    if not expected_token:
        if is_prod:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Sandbox service token not configured in production environment."
            )
        return True

    if not provided_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required sandbox authentication token."
        )

    if not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid sandbox authentication token."
        )

    return True


class ExecuteRequest(BaseModel):
    command: Union[str, List[str]]
    timeout_seconds: Optional[int] = 60
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    cwd_relative: Optional[str] = None
    environment: Optional[Dict[str, str]] = None
    allow_network: bool = False
    read_only: bool = False
    tool_name: str = "run_command"


class TestExecutionRequest(BaseModel):
    test_command: Union[str, List[str]] = "pytest"
    test_targets: Optional[List[str]] = None
    timeout_seconds: Optional[int] = 120
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    cwd_relative: Optional[str] = None
    environment: Optional[Dict[str, str]] = None


class StreamDrainer:
    """
    Asynchronously drains an output stream into a bounded memory buffer while
    continuing to read until EOF. Prevents OS pipe deadlock when output exceeds capture limit,
    and signals hard limit violations.
    """
    def __init__(self, capture_limit: int, hard_limit: int, on_hard_limit_exceeded=None):
        self.capture_limit = capture_limit
        self.hard_limit = hard_limit
        self.on_hard_limit_exceeded = on_hard_limit_exceeded
        self.captured = bytearray()
        self.total_bytes = 0
        self.truncated = False
        self.hard_limit_exceeded = False

    async def read(self, stream: Optional[asyncio.StreamReader]) -> bytes:
        if not stream:
            return b""
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            chunk_len = len(chunk)
            self.total_bytes += chunk_len

            if len(self.captured) < self.capture_limit:
                rem = self.capture_limit - len(self.captured)
                self.captured.extend(chunk[:rem])
                if chunk_len > rem:
                    self.truncated = True
            else:
                self.truncated = True

            if self.total_bytes > self.hard_limit:
                self.hard_limit_exceeded = True
                self.truncated = True
                if self.on_hard_limit_exceeded:
                    self.on_hard_limit_exceeded()
                break
        return bytes(self.captured)


@app.get("/health")
async def health():
    """Liveness check returning process alive and docker availability."""
    docker_ok = check_docker_operational()
    return {
        "status": "ok" if docker_ok else "degraded",
        "docker_available": docker_ok,
        "runtime": "docker" if docker_ok else "unavailable",
        "image": SANDBOX_IMAGE,
        "workspace_root": WORKSPACE_ROOT,
        "timestamp": time.time()
    }


@app.get("/readiness")
async def readiness():
    """
    Readiness probe validating:
    - Docker daemon reachable
    - Configured sandbox image exists
    - Image can start and execute code
    - Execution user is non-root
    - Expected binaries exist (python, git, node, npm)
    - Workspace storage available
    """
    now = time.time()
    if _readiness_cache["result"] is not None and (now - _readiness_cache["last_check"] < 30):
        is_ready, payload = _readiness_cache["result"]
        if not is_ready:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
        return payload

    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ("production", "prod")

    docker_ok = check_docker_operational()
    image_ok = False
    container_can_start = False
    non_root = False
    binaries = {"python": False, "git": False, "node": False, "npm": False}

    if docker_ok:
        try:
            inspect_res = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False
            )
            image_ok = (inspect_res.returncode == 0)
        except Exception:
            image_ok = False

        if image_ok:
            smoke_name = f"sakura-smoke-{uuid.uuid4().hex[:8]}"
            try:
                smoke_res = subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "--name", smoke_name,
                        "--network", "none",
                        "--security-opt", "no-new-privileges:true",
                        "--cap-drop", "ALL",
                        SANDBOX_IMAGE,
                        "sh", "-c",
                        "id -u && which python3 python git node npm"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False
                )
                if smoke_res.returncode == 0:
                    container_can_start = True
                    lines = smoke_res.stdout.strip().splitlines()
                    if lines:
                        uid_str = lines[0].strip()
                        non_root = (uid_str != "0")
                        out_text = smoke_res.stdout
                        binaries["python"] = ("python" in out_text)
                        binaries["git"] = ("git" in out_text)
                        binaries["node"] = ("node" in out_text)
                        binaries["npm"] = ("npm" in out_text)
            except Exception:
                pass
            finally:
                try:
                    subprocess.run(["docker", "rm", "-f", smoke_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                except Exception:
                    pass

    ws_root_ok = os.path.isdir(WORKSPACE_ROOT)

    if is_prod:
        is_ready = docker_ok and image_ok and container_can_start and non_root and all(binaries.values()) and ws_root_ok
    else:
        is_ready = docker_ok and image_ok and ws_root_ok

    payload = {
        "ready": is_ready,
        "docker_available": docker_ok,
        "image_available": image_ok,
        "container_can_start": container_can_start,
        "non_root_execution": non_root,
        "binaries": binaries,
        "workspace_root_available": ws_root_ok,
        "workspace_root": WORKSPACE_ROOT,
        "image": SANDBOX_IMAGE,
        "timestamp": now
    }
    _readiness_cache["last_check"] = now
    _readiness_cache["result"] = (is_ready, payload)

    if not is_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


@app.post("/execute")
async def execute_command(
    req: ExecuteRequest,
    _auth: bool = Depends(verify_service_token)
):
    """
    Executes an arbitrary shell command in an ephemeral isolated Docker container.
    Guarantees strict per-workspace isolation (child mounts only /workspace, never /workspaces).
    """
    start_time = time.time()
    timeout = req.timeout_seconds or 60
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ("production", "prod")

    cmd_display = " ".join(req.command) if isinstance(req.command, list) else str(req.command)

    # 1. Security validation of command string
    try:
        WorkspaceSecurity.validate_command(cmd_display)
    except SecurityException as e:
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Security Error: {str(e)}",
            "duration_ms": 0,
            "timed_out": False,
            "blocked": True,
            "isolation_unavailable": False,
            "output_truncated": False,
            "output_limit_exceeded": False
        }

    # 2. Strict UUID workspace validation & canonical path resolution
    canonical_ws_id = None
    if req.workspace_id:
        try:
            ws_uuid = uuid.UUID(str(req.workspace_id).strip())
            canonical_ws_id = str(ws_uuid)
        except (ValueError, TypeError, AttributeError):
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: workspace_id must be a valid UUID format.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }

        canonical_ws = os.path.realpath(os.path.join(WORKSPACE_ROOT, canonical_ws_id))
        canonical_root = os.path.realpath(WORKSPACE_ROOT)
        if os.path.commonpath([canonical_ws, canonical_root]) != canonical_root or canonical_ws == canonical_root:
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: Workspace ID escapes WORKSPACE_ROOT.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        if not os.path.exists(canonical_ws):
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Workspace Error: Workspace ID '{canonical_ws_id}' does not exist on disk.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        resolved_workspace = canonical_ws
    else:
        if is_prod:
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: workspace_id is required for execution in production.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        raw_path = os.path.realpath(os.path.abspath(req.workspace_path or "/workspace"))
        prohibited = ["/", "/etc", "/var/run", "/proc", "/sys", "/dev", "C:\\", "C:\\Windows"]
        if raw_path in prohibited or any(raw_path.startswith(p + "/") for p in ["/etc", "/proc", "/sys", "/dev"]):
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Security Error: Prohibited host path '{raw_path}' cannot be mounted.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        resolved_workspace = raw_path

    # 3. Working directory setup
    clean_rel = ""
    if req.cwd_relative:
        try:
            WorkspaceSecurity.resolve_safe_path(resolved_workspace, req.cwd_relative)
            clean_rel = req.cwd_relative.replace("\\", "/").strip("/")
        except SecurityException as e:
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Working directory error: {str(e)}",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }

    # 4. Check docker daemon availability
    if not check_docker_operational():
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Container isolation runtime is unavailable on sandbox host.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "timed_out": False,
            "blocked": False,
            "isolation_unavailable": True,
            "output_truncated": False,
            "output_limit_exceeded": False
        }

    # 5. Build Docker mount and execution specifications
    if isinstance(req.command, list):
        cmd_args = req.command
    else:
        cmd_args = ["sh", "-c", req.command]

    network_flag = "bridge" if req.allow_network else "none"
    mount_mode = "ro" if req.read_only else "rw"

    # PER-WORKSPACE ISOLATION: Mount ONLY this specific workspace to /workspace.
    # Never mount the parent /workspaces volume.
    vol_mountpoint = get_volume_host_mountpoint(WORKSPACES_VOLUME) if WORKSPACES_VOLUME else None
    if vol_mountpoint and canonical_ws_id:
        host_target = f"{vol_mountpoint}/{canonical_ws_id}"
    else:
        host_target = resolved_workspace

    mount_spec = f"{host_target}:/workspace:{mount_mode}"
    container_workdir = f"/workspace/{clean_rel}" if clean_rel else "/workspace"
    container_name = f"sakura-exec-{uuid.uuid4().hex}"

    docker_cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--user", "1001:1001",
        "--network", network_flag,
        f"--cpus={CPU_LIMIT}",
        f"--memory={MEMORY_MB}m",
        f"--pids-limit={PIDS_LIMIT}",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "-v", mount_spec,
        "-w", container_workdir
    ]

    # Explicit allowlist environment policy (no os.environ inheritance)
    safe_env = WorkspaceSecurity.build_safe_child_environment(req.environment or {})
    for k, v in safe_env.items():
        docker_cmd.extend(["-e", f"{k}={v}"])

    docker_cmd.append(SANDBOX_IMAGE)
    docker_cmd.extend(cmd_args)

    proc = None
    timed_out = False
    output_limit_exceeded = False
    stdout_drainer = None
    stderr_drainer = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        def kill_runaway_container():
            nonlocal output_limit_exceeded
            output_limit_exceeded = True
            try:
                subprocess.run(["docker", "kill", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass

        stdout_drainer = StreamDrainer(
            capture_limit=CAPTURE_LIMIT_BYTES,
            hard_limit=HARD_OUTPUT_LIMIT_BYTES,
            on_hard_limit_exceeded=kill_runaway_container
        )
        stderr_drainer = StreamDrainer(
            capture_limit=CAPTURE_LIMIT_BYTES,
            hard_limit=HARD_OUTPUT_LIMIT_BYTES,
            on_hard_limit_exceeded=kill_runaway_container
        )

        try:
            async def drain_all():
                so_task = asyncio.create_task(stdout_drainer.read(proc.stdout))
                se_task = asyncio.create_task(stderr_drainer.read(proc.stderr))
                so_bytes, se_bytes = await asyncio.gather(so_task, se_task)
                await proc.wait()
                return so_bytes, se_bytes

            stdout_bytes, stderr_bytes = await asyncio.wait_for(drain_all(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                subprocess.run(["docker", "kill", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            stdout_bytes = bytes(stdout_drainer.captured) if stdout_drainer else b""
            stderr_bytes = bytes(stderr_drainer.captured) if stderr_drainer else b""

        duration_ms = int((time.time() - start_time) * 1000)
        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        output_truncated = bool(
            (stdout_drainer and stdout_drainer.truncated)
            or (stderr_drainer and stderr_drainer.truncated)
            or output_limit_exceeded
        )

        if output_limit_exceeded:
            stderr_str += f"\n[OUTPUT HARD LIMIT EXCEEDED: Runaway process terminated after exceeding {HARD_OUTPUT_LIMIT_BYTES} bytes]"
        elif stdout_drainer and stdout_drainer.truncated:
            stdout_str += f"\n[OUTPUT TRUNCATED: Exceeded maximum allowed buffer limit of {CAPTURE_LIMIT_BYTES} bytes]"

        exit_code = proc.returncode if (proc is not None and not timed_out) else -1

        return {
            "success": (exit_code == 0) and not timed_out and not output_limit_exceeded,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": exit_code,
            "stdout": stdout_str,
            "stderr": stderr_str if not timed_out else (stderr_str + f"\nExecution timed out after {timeout} seconds."),
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "blocked": False,
            "isolation_unavailable": False,
            "output_truncated": output_truncated,
            "output_limit_exceeded": output_limit_exceeded
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution error: {str(e)}",
            "duration_ms": duration_ms,
            "timed_out": False,
            "blocked": False,
            "isolation_unavailable": False,
            "output_truncated": False,
            "output_limit_exceeded": False
        }
    finally:
        # Idempotent cleanup: unconditionally ensure execution container is removed from Docker
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False
            )
        except Exception:
            pass


@app.post("/tests")
async def run_tests(
    req: TestExecutionRequest,
    _auth: bool = Depends(verify_service_token)
):
    """Executes test commands within the container isolation boundary."""
    cmd = req.test_command
    if req.test_targets:
        if isinstance(cmd, list):
            cmd = list(cmd) + req.test_targets
        else:
            cmd = f"{cmd} " + " ".join(req.test_targets)

    exec_req = ExecuteRequest(
        command=cmd,
        timeout_seconds=req.timeout_seconds,
        workspace_id=req.workspace_id,
        workspace_path=req.workspace_path,
        cwd_relative=req.cwd_relative,
        environment=req.environment,
        allow_network=False,
        read_only=False,
        tool_name="run_tests"
    )
    return await execute_command(exec_req, _auth=True)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
