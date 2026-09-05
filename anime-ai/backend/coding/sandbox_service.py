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
from typing import Dict, Any, Optional, List, Union
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
MAX_OUTPUT_BYTES = int(os.getenv("SAKURA_MAX_OUTPUT_BYTES", str(512 * 1024)))
WORKSPACE_ROOT = os.path.realpath(os.path.abspath(os.getenv("SAKURA_WORKSPACE_ROOT", "/workspaces")))
WORKSPACES_VOLUME = os.getenv("SAKURA_WORKSPACES_VOLUME", "")

os.makedirs(WORKSPACE_ROOT, exist_ok=True)


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
        # Allow dev/test when no token is explicitly configured
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


async def _read_stream_bounded(stream: asyncio.StreamReader, max_bytes: int):
    """Reads stream asynchronously in chunks up to max_bytes, returning (data_bytes, is_truncated)."""
    chunks = []
    total = 0
    truncated = False
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        total += len(chunk)
        if total <= max_bytes:
            chunks.append(chunk)
        else:
            overflow = max_bytes - (total - len(chunk))
            if overflow > 0:
                chunks.append(chunk[:overflow])
            truncated = True
            break
    return b"".join(chunks), truncated


@app.get("/health")
async def health():
    """Liveness check returning container isolation status."""
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
    """Readiness probe validating Docker operational status, runtime image, and workspace root."""
    docker_ok = check_docker_operational()
    image_ok = False
    if docker_ok:
        try:
            res = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False
            )
            image_ok = (res.returncode == 0)
        except Exception:
            image_ok = False

    ws_root_ok = os.path.isdir(WORKSPACE_ROOT)
    is_ready = docker_ok and image_ok and ws_root_ok

    payload = {
        "ready": is_ready,
        "docker_available": docker_ok,
        "image_available": image_ok,
        "workspace_root_available": ws_root_ok,
        "workspace_root": WORKSPACE_ROOT,
        "image": SANDBOX_IMAGE,
        "timestamp": time.time()
    }
    if not is_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


@app.post("/execute")
async def execute_command(
    req: ExecuteRequest,
    _auth: bool = Depends(verify_service_token)
):
    """Executes an arbitrary shell command in an ephemeral isolated Docker container."""
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
            "output_truncated": False
        }

    # 2. Workspace resolution & path boundary checks
    if req.workspace_id:
        if not re.match(r"^[a-zA-Z0-9_\-]+$", req.workspace_id):
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: Invalid workspace ID format.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False
            }
        canonical_ws = os.path.realpath(os.path.join(WORKSPACE_ROOT, req.workspace_id))
        if not canonical_ws.startswith(WORKSPACE_ROOT + os.sep) and canonical_ws != WORKSPACE_ROOT:
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
                "output_truncated": False
            }
        if not os.path.exists(canonical_ws):
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Workspace Error: Workspace ID '{req.workspace_id}' does not exist on disk.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False
            }
        resolved_workspace = canonical_ws
        use_shared_volume = bool(WORKSPACES_VOLUME)
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
                "output_truncated": False
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
                "output_truncated": False
            }
        resolved_workspace = raw_path
        use_shared_volume = False

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
                "output_truncated": False
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
            "output_truncated": False
        }

    # 5. Command invocation & Docker flags
    if isinstance(req.command, list):
        cmd_args = req.command
    else:
        cmd_args = ["sh", "-c", req.command]

    network_flag = "bridge" if req.allow_network else "none"
    mount_mode = "ro" if req.read_only else "rw"

    if use_shared_volume:
        mount_spec = f"{WORKSPACES_VOLUME}:/workspaces:{mount_mode}"
        container_workdir = f"/workspaces/{req.workspace_id}/{clean_rel}" if clean_rel else f"/workspaces/{req.workspace_id}"
    else:
        mount_spec = f"{resolved_workspace}:/workspace:{mount_mode}"
        container_workdir = f"/workspace/{clean_rel}" if clean_rel else "/workspace"

    container_name = f"sakura-exec-{uuid.uuid4().hex[:12]}"

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

    # Add environment variables safely (scrubbing secrets)
    safe_env = WorkspaceSecurity.sanitize_environment(req.environment or {})
    for k, v in safe_env.items():
        docker_cmd.extend(["-e", f"{k}={v}"])

    docker_cmd.append(SANDBOX_IMAGE)
    docker_cmd.extend(cmd_args)

    proc = None
    output_truncated = False
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            # Incremental bounded streaming consumption
            async def consume_streams():
                stdout_fut = asyncio.create_task(_read_stream_bounded(proc.stdout, MAX_OUTPUT_BYTES))
                stderr_fut = asyncio.create_task(_read_stream_bounded(proc.stderr, MAX_OUTPUT_BYTES))
                stdout_res, stderr_res = await asyncio.gather(stdout_fut, stderr_fut)
                await proc.wait()
                return stdout_res, stderr_res

            (stdout_bytes, stdout_trunc), (stderr_bytes, stderr_trunc) = await asyncio.wait_for(
                consume_streams(),
                timeout=timeout
            )
            output_truncated = stdout_trunc or stderr_trunc

            duration_ms = int((time.time() - start_time) * 1000)
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            if stdout_trunc:
                stdout_str += f"\n[OUTPUT TRUNCATED: Exceeded maximum allowed buffer limit of {MAX_OUTPUT_BYTES} bytes]"
            if stderr_trunc:
                stderr_str += f"\n[OUTPUT TRUNCATED: Exceeded maximum allowed buffer limit of {MAX_OUTPUT_BYTES} bytes]"

            return {
                "success": proc.returncode == 0,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": proc.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "duration_ms": duration_ms,
                "timed_out": False,
                "blocked": False,
                "isolation_unavailable": False,
                "output_truncated": output_truncated
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds.",
                "duration_ms": duration_ms,
                "timed_out": True,
                "blocked": False,
                "isolation_unavailable": False,
                "output_truncated": False
            }
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Docker executor failure: {str(e)}",
            "duration_ms": duration_ms,
            "timed_out": False,
            "blocked": False,
            "isolation_unavailable": True,
            "output_truncated": False
        }
    finally:
        # Guarantee child container is destroyed on completion, timeout, cancellation, or error
        if check_docker_operational():
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
