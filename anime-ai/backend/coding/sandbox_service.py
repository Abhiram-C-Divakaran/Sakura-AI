"""
Sakura AI — Dedicated Sandbox Executor Service
Internal service exposing authenticated HTTP endpoints for isolated code execution.
Runs as a standalone service with access to Docker daemon (the main backend API container
does NOT have Docker daemon access).
"""

import os
import time
import shutil
import hmac
import asyncio
import subprocess
from typing import Dict, Any, Optional, List, Union
from fastapi import FastAPI, Header, HTTPException, Depends, status
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
MAX_OUTPUT_CHARS = 100000


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
    workspace_path: Optional[str] = "/workspace"
    cwd_relative: Optional[str] = None
    environment: Optional[Dict[str, str]] = None
    allow_network: bool = False
    read_only: bool = False
    tool_name: str = "run_command"


class TestExecutionRequest(BaseModel):
    test_command: Union[str, List[str]] = "pytest"
    test_targets: Optional[List[str]] = None
    timeout_seconds: Optional[int] = 120
    workspace_path: Optional[str] = "/workspace"
    cwd_relative: Optional[str] = None
    environment: Optional[Dict[str, str]] = None


@app.get("/health")
async def health():
    """Health check returning container isolation status."""
    docker_ok = check_docker_operational()
    return {
        "status": "ok" if docker_ok else "degraded",
        "docker_available": docker_ok,
        "runtime": "docker" if docker_ok else "unavailable",
        "image": SANDBOX_IMAGE,
        "timestamp": time.time()
    }


@app.post("/execute")
async def execute_command(
    req: ExecuteRequest,
    _auth: bool = Depends(verify_service_token)
):
    """Executes an arbitrary shell command in an ephemeral isolated Docker container."""
    start_time = time.time()
    timeout = req.timeout_seconds or 60

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
            "isolation_unavailable": False
        }

    # 2. Path security and working directory setup
    workspace_dir = os.path.realpath(os.path.abspath(req.workspace_path or "/workspace"))
    container_workdir = "/workspace"
    if req.cwd_relative:
        try:
            # Validate traversal
            WorkspaceSecurity.resolve_safe_path(workspace_dir, req.cwd_relative)
            clean_rel = req.cwd_relative.replace("\\", "/").strip("/")
            container_workdir = f"/workspace/{clean_rel}"
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
                "isolation_unavailable": False
            }

    # 3. Check docker daemon availability
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
            "isolation_unavailable": True
        }

    # 4. Command invocation
    if isinstance(req.command, list):
        cmd_args = req.command
    else:
        cmd_args = ["sh", "-c", req.command]

    network_flag = "bridge" if req.allow_network else "none"
    mount_mode = "ro" if req.read_only else "rw"

    docker_cmd = [
        "docker", "run", "--rm",
        "--user", "1001:1001",
        "--network", network_flag,
        f"--cpus={CPU_LIMIT}",
        f"--memory={MEMORY_MB}m",
        f"--pids-limit={PIDS_LIMIT}",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "-v", f"{workspace_dir}:/workspace:{mount_mode}",
        "-w", container_workdir
    ]

    # Add environment variables safely (scrubbing secrets)
    safe_env = WorkspaceSecurity.sanitize_environment(req.environment or {})
    for k, v in safe_env.items():
        docker_cmd.extend(["-e", f"{k}={v}"])

    docker_cmd.append(SANDBOX_IMAGE)
    docker_cmd.extend(cmd_args)

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
            stdout_str = stdout_data.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
            stderr_str = stderr_data.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]

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
                "isolation_unavailable": False
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
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds.",
                "duration_ms": duration_ms,
                "timed_out": True,
                "blocked": False,
                "isolation_unavailable": False
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
            "isolation_unavailable": True
        }


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
