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

def _is_dir_writable(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    probe = os.path.join(path, f".sakura_probe_{uuid.uuid4().hex[:8]}")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


default_ws_root = os.getenv("SAKURA_WORKSPACE_ROOT")
if not default_ws_root:
    if os.name != "nt" and _is_dir_writable("/workspaces"):
        default_ws_root = "/workspaces"
    else:
        default_ws_root = os.path.join(tempfile.gettempdir(), "sakura_workspaces")
WORKSPACE_ROOT = os.path.realpath(os.path.abspath(default_ws_root))
WORKSPACES_VOLUME = os.getenv("SAKURA_WORKSPACES_VOLUME", "")
SANDBOX_CHILD_UID = int(os.getenv("SAKURA_SANDBOX_UID", "1001"))
SANDBOX_CHILD_GID = int(os.getenv("SAKURA_SANDBOX_GID", "1001"))


def _ensure_workspace_root_exists() -> str:
    os.makedirs(WORKSPACE_ROOT, exist_ok=True)
    # Ensure shared volume root is owned by UID/GID 1001 (0770) so non-root backend-api
    # and coding-worker containers can create/read workspace directories without root!
    ensure_workspace_ownership(WORKSPACE_ROOT, recursive=False)
    return WORKSPACE_ROOT


@app.on_event("startup")
async def _init_sandbox_workspace_root() -> None:
    _ensure_workspace_root_exists()


def ensure_workspace_ownership(ws_path: str, *, recursive: bool = True) -> None:
    """
    Enforces explicit POSIX ownership (UID/GID 1001) and restrictive owner+group
    permissions (0770 dirs / 0660 files; NEVER world-writable 0777) so non-root
    sandbox child containers and backend services share workspace files safely.
    """
    if os.name == "nt" or not os.path.exists(ws_path):
        return

    def _set_perms(target: str, is_dir: bool) -> None:
        try:
            os.chown(target, SANDBOX_CHILD_UID, SANDBOX_CHILD_GID)
        except (PermissionError, OSError):
            pass
        try:
            current_mode = os.stat(target).st_mode
            if is_dir:
                os.chmod(target, 0o770)
            else:
                # Preserve executable bit for owner/group if set, never grant world-write
                exec_bits = 0o110 if (current_mode & 0o111) else 0
                os.chmod(target, 0o660 | exec_bits)
        except (PermissionError, OSError):
            pass

    _set_perms(ws_path, os.path.isdir(ws_path))
    if recursive and os.path.isdir(ws_path):
        for root, dirs, files in os.walk(ws_path):
            for d in dirs:
                _set_perms(os.path.join(root, d), True)
            for f in files:
                _set_perms(os.path.join(root, f), False)

_readiness_cache: Dict[str, Any] = {"last_check": 0.0, "result": None}
_ACTIVE_EXECUTIONS: Dict[str, Tuple[str, Any]] = {}


def check_docker_status() -> Tuple[bool, Optional[str]]:
    """Checks if the Docker CLI and daemon are operational, returning (ok, error_detail)."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return False, "docker CLI binary not found in PATH"
    try:
        res = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if res.returncode == 0:
            return True, None
        err = (res.stderr or res.stdout or f"exit code {res.returncode}").strip()
        return False, err[:300]
    except Exception as e:
        return False, str(e)[:300]


def check_docker_operational() -> bool:
    """Checks if the Docker CLI and daemon are operational on host."""
    ok, _ = check_docker_status()
    return ok


def check_redis_status() -> Tuple[bool, Optional[str]]:
    """Checks Redis connectivity for capability nonce replay protection."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return False, "REDIS_URL not configured"
    client = None
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        if client.ping():
            return True, None
        return False, "Redis ping returned false"
    except Exception as e:
        return False, str(e)[:300]
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


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
    network_authorization_id: Optional[str] = None
    network_capability: Optional[str] = None
    execution_id: Optional[str] = None
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
    - Workspace storage & configured Docker volume available
    - Redis reachable (required in production for capability replay protection)
    """
    now = time.time()
    # Only cache positive readiness checks so transient startup delays recover immediately
    if _readiness_cache["result"] is not None and (now - _readiness_cache["last_check"] < 30):
        is_ready, payload = _readiness_cache["result"]
        if is_ready:
            return payload

    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ("production", "prod")

    docker_ok, docker_error = check_docker_status()
    redis_ok, redis_error = check_redis_status()
    image_ok = False
    image_error = None
    container_can_start = False
    non_root = False
    smoke_returncode = None
    smoke_stderr = None
    binaries = {"python": False, "git": False, "node": False, "npm": False}

    if docker_ok:
        try:
            inspect_res = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            image_ok = (inspect_res.returncode == 0)
            if not image_ok:
                image_error = (inspect_res.stderr or inspect_res.stdout or f"exit {inspect_res.returncode}").strip()[:300]
        except Exception as e:
            image_ok = False
            image_error = str(e)[:300]

        if image_ok:
            smoke_name = f"sakura-smoke-{uuid.uuid4().hex[:8]}"
            smoke_script = (
                'echo "UID=$(id -u)"; '
                'for b in python3 python git node npm; do '
                'if command -v "$b" >/dev/null 2>&1; then echo "BIN:$b=1"; else echo "BIN:$b=0"; fi; '
                'done'
            )
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
                        smoke_script
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False
                )
                smoke_returncode = smoke_res.returncode
                if smoke_res.stderr:
                    smoke_stderr = smoke_res.stderr.strip()[:300]
                if smoke_res.returncode == 0:
                    container_can_start = True
                    out_lines = [ln.strip() for ln in smoke_res.stdout.splitlines() if ln.strip()]
                    found_bins: Dict[str, bool] = {}
                    for ln in out_lines:
                        if ln.startswith("UID="):
                            uid_str = ln.split("=", 1)[1].strip()
                            non_root = (uid_str.isdigit() and uid_str != "0")
                        elif ln.startswith("BIN:") and "=" in ln:
                            bname, bval = ln[4:].split("=", 1)
                            found_bins[bname.strip()] = (bval.strip() == "1")
                    binaries["python"] = bool(found_bins.get("python3") or found_bins.get("python"))
                    binaries["git"] = bool(found_bins.get("git"))
                    binaries["node"] = bool(found_bins.get("node"))
                    binaries["npm"] = bool(found_bins.get("npm"))
            except Exception as e:
                smoke_stderr = str(e)[:300]
            finally:
                try:
                    subprocess.run(["docker", "rm", "-f", smoke_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                except Exception:
                    pass

    ws_root_ok = os.path.isdir(WORKSPACE_ROOT)
    configured_vol = os.getenv("SAKURA_WORKSPACES_VOLUME", WORKSPACES_VOLUME).strip()
    volume_ok = True
    if configured_vol:
        volume_ok = get_volume_host_mountpoint(configured_vol) is not None if docker_ok else False

    redis_required = is_prod or bool(os.getenv("REDIS_URL", "").strip())
    redis_gate_ok = redis_ok if redis_required else True

    from config.settings import KNOWN_DEV_SECRETS
    svc_token_val = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", SERVICE_TOKEN).strip()
    cap_key_val = os.getenv("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY", "").strip()
    service_token_configured = bool(svc_token_val and svc_token_val not in KNOWN_DEV_SECRETS)
    capability_signing_key_configured = bool(
        cap_key_val and len(cap_key_val) >= 32 and cap_key_val not in KNOWN_DEV_SECRETS
    )

    if is_prod:
        is_ready = (
            docker_ok
            and image_ok
            and container_can_start
            and non_root
            and all(binaries.values())
            and ws_root_ok
            and volume_ok
            and redis_gate_ok
            and service_token_configured
            and capability_signing_key_configured
        )
    else:
        is_ready = docker_ok and image_ok and container_can_start and non_root and ws_root_ok and volume_ok

    payload = {
        "ready": is_ready,
        "docker_available": docker_ok,
        "docker_error": docker_error,
        "image_available": image_ok,
        "image_error": image_error,
        "container_can_start": container_can_start,
        "non_root_execution": non_root,
        "smoke_returncode": smoke_returncode,
        "smoke_stderr": smoke_stderr,
        "binaries": binaries,
        "workspace_root_available": ws_root_ok,
        "workspace_volume_available": volume_ok,
        "workspace_volume": configured_vol or None,
        "workspace_root": WORKSPACE_ROOT,
        "redis_available": redis_ok,
        "redis_error": redis_error if not redis_ok else None,
        "service_token_configured": service_token_configured,
        "capability_signing_key_configured": capability_signing_key_configured,
        "image": SANDBOX_IMAGE,
        "timestamp": now
    }
    if is_ready:
        _readiness_cache["last_check"] = now
        _readiness_cache["result"] = (True, payload)
    else:
        _readiness_cache["last_check"] = 0.0
        _readiness_cache["result"] = None

    if not is_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


@app.post("/workspaces/{workspace_id}")
async def provision_workspace(
    workspace_id: str,
    _auth: bool = Depends(verify_service_token)
):
    """Provisions an isolated workspace directory within WORKSPACE_ROOT."""
    try:
        val = uuid.UUID(workspace_id)
        canonical_id = str(val)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid workspace UUID format")

    _ensure_workspace_root_exists()
    ws_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, canonical_id))
    canonical_root = os.path.realpath(WORKSPACE_ROOT)
    if os.path.commonpath([ws_path, canonical_root]) != canonical_root or ws_path == canonical_root:
        raise HTTPException(status_code=400, detail="Workspace path escapes WORKSPACE_ROOT")

    os.makedirs(ws_path, exist_ok=True)
    ensure_workspace_ownership(ws_path, recursive=True)
    return {
        "status": "ok",
        "workspace_id": canonical_id,
        "path": ws_path,
        "uid": SANDBOX_CHILD_UID,
        "gid": SANDBOX_CHILD_GID,
    }


class CloneRequest(BaseModel):
    repository_url: str
    branch: Optional[str] = "main"
    capability_token: str
    timeout_seconds: Optional[int] = 120


@app.post("/workspaces/{workspace_id}/clone")
async def clone_repository(
    workspace_id: str,
    req: CloneRequest,
    _auth: bool = Depends(verify_service_token)
):
    """
    Executes a scoped git clone operation inside an ephemeral Docker container.
    Requires a valid signed repository_clone capability token.
    Enables outbound network strictly for the duration of the clone operation.
    """
    start_time = time.time()
    timeout = req.timeout_seconds or 120

    try:
        ws_uuid = uuid.UUID(str(workspace_id).strip())
        canonical_ws_id = str(ws_uuid)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid workspace UUID format")

    canonical_ws = os.path.realpath(os.path.join(WORKSPACE_ROOT, canonical_ws_id))
    canonical_root = os.path.realpath(WORKSPACE_ROOT)
    if os.path.commonpath([canonical_ws, canonical_root]) != canonical_root or canonical_ws == canonical_root:
        raise HTTPException(status_code=400, detail="Workspace path escapes WORKSPACE_ROOT")
    os.makedirs(canonical_ws, exist_ok=True)
    ensure_workspace_ownership(canonical_ws, recursive=True)

    from coding.capabilities import verify_and_consume_capability, CapabilityError
    from coding.security import WorkspaceSecurity, SecurityException

    try:
        WorkspaceSecurity.validate_repository_url(req.repository_url)
        if req.branch:
            WorkspaceSecurity.validate_branch_name(req.branch)
    except SecurityException as e:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Security Error: {str(e)}",
            "duration_ms": 0,
            "blocked": True
        }

    expected_clone_cmd = ["git", "clone", "--depth", "1", "--branch", req.branch or "main", req.repository_url, "."]
    try:
        verify_and_consume_capability(
            capability_token=req.capability_token,
            expected_scope="repository_clone",
            expected_workspace_id=canonical_ws_id,
            expected_command=expected_clone_cmd,
            expected_repository_url=req.repository_url,
            expected_branch=req.branch
        )
    except CapabilityError as e:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Security Error: Repository clone blocked ({str(e)}). Valid signed capability is required.",
            "duration_ms": 0,
            "blocked": True
        }

    if not check_docker_operational():
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Container isolation runtime is unavailable on sandbox host.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "isolation_unavailable": True
        }

    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ("production", "prod")
    workspaces_volume = os.getenv("SAKURA_WORKSPACES_VOLUME", WORKSPACES_VOLUME).strip()
    host_root = get_volume_host_mountpoint(workspaces_volume) if workspaces_volume else None
    if workspaces_volume and not host_root:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Volume resolution failure: Configured Docker workspaces volume '{workspaces_volume}' cannot be resolved on host.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "isolation_unavailable": True
        }
    if is_prod and not host_root:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Volume resolution failure: Docker workspace volume resolution is required in production.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "isolation_unavailable": True
        }

    container_name = f"sakura-clone-{uuid.uuid4().hex[:12]}"
    mount_source = os.path.join(host_root, canonical_ws_id) if host_root else canonical_ws

    safe_env = WorkspaceSecurity.build_safe_child_environment()
    env_args = []
    for k, v in safe_env.items():
        env_args.extend(["-e", f"{k}={v}"])

    docker_run_cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--user", "1001:1001",
        "--network", "bridge",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "--cpus", str(CPU_LIMIT),
        "--memory", f"{MEMORY_MB}m",
        "--pids-limit", str(PIDS_LIMIT),
        "-v", f"{mount_source}:/workspace:rw",
        "-w", "/workspace",
        *env_args,
        SANDBOX_IMAGE,
        *expected_clone_cmd
    ]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_run_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_drainer = StreamDrainer(CAPTURE_LIMIT_BYTES, HARD_OUTPUT_LIMIT_BYTES)
        stderr_drainer = StreamDrainer(CAPTURE_LIMIT_BYTES, HARD_OUTPUT_LIMIT_BYTES)

        stdout_data, stderr_data = await asyncio.wait_for(
            asyncio.gather(stdout_drainer.read(proc.stdout), stderr_drainer.read(proc.stderr)),
            timeout=timeout
        )
        await proc.wait()
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout_data.decode("utf-8", errors="replace"),
            "stderr": stderr_data.decode("utf-8", errors="replace"),
            "duration_ms": duration_ms,
            "timed_out": False,
            "blocked": False
        }
    except asyncio.CancelledError:
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                pass
        raise
    except asyncio.TimeoutError:
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                pass
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Repository clone timed out after {timeout} seconds.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "timed_out": True
        }
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass


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
        if not req.read_only:
            # Ensure backend-created files inside this workspace are owned/writable by UID/GID 1001
            ensure_workspace_ownership(resolved_workspace, recursive=True)
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

    # 4. Validate network authorization policy via cryptographically signed capability
    # Strictly requires a signed 'network_exec' capability (never raw authorization UUIDs or clone tokens)
    network_flag = "none"
    if req.allow_network:
        is_authorized = False
        cap_token = req.network_capability
        if not canonical_ws_id:
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: Outbound network access blocked. A valid workspace_id and signed network_exec capability are required.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        if cap_token:
            from coding.capabilities import verify_and_consume_capability, CapabilityError
            try:
                verify_and_consume_capability(
                    capability_token=cap_token,
                    expected_scope="network_exec",
                    expected_workspace_id=canonical_ws_id,
                    expected_command=req.command
                )
                is_authorized = True
            except CapabilityError as e:
                return {
                    "success": False,
                    "tool": req.tool_name,
                    "command": cmd_display,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Security Error: Outbound network access blocked ({str(e)}). Server authorization is required for network access (valid signed capability is required).",
                    "duration_ms": 0,
                    "timed_out": False,
                    "blocked": True,
                    "isolation_unavailable": False,
                    "output_truncated": False,
                    "output_limit_exceeded": False
                }
            except Exception:
                is_authorized = False

        if not is_authorized:
            return {
                "success": False,
                "tool": req.tool_name,
                "command": cmd_display,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Security Error: Outbound network access blocked. Server authorization is required for network access (valid signed capability token is required).",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True,
                "isolation_unavailable": False,
                "output_truncated": False,
                "output_limit_exceeded": False
            }
        network_flag = "bridge"

    # 5. Check docker daemon availability
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

    # 6. Build Docker mount and execution specifications
    if isinstance(req.command, list):
        cmd_args = req.command
    else:
        cmd_args = ["sh", "-c", req.command]

    mount_mode = "ro" if req.read_only else "rw"

    # PER-WORKSPACE ISOLATION: Mount ONLY this specific workspace to /workspace.
    # Never mount the parent /workspaces volume.
    workspaces_volume = os.getenv("SAKURA_WORKSPACES_VOLUME", WORKSPACES_VOLUME)
    vol_mountpoint = get_volume_host_mountpoint(workspaces_volume) if workspaces_volume else None
    if workspaces_volume and not vol_mountpoint:
        # Configured volume cannot be inspected -> FAIL CLOSED
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Volume resolution failure: Configured Docker workspaces volume '{workspaces_volume}' cannot be resolved on host.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "timed_out": False,
            "blocked": False,
            "isolation_unavailable": True,
            "output_truncated": False,
            "output_limit_exceeded": False
        }

    if is_prod and not vol_mountpoint:
        # In production, volume resolution is strictly required
        return {
            "success": False,
            "tool": req.tool_name,
            "command": cmd_display,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Volume resolution failure: Docker workspace volume resolution is required in production.",
            "duration_ms": int((time.time() - start_time) * 1000),
            "timed_out": False,
            "blocked": False,
            "isolation_unavailable": True,
            "output_truncated": False,
            "output_limit_exceeded": False
        }

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

    exec_id = (req.execution_id or uuid.uuid4().hex).strip()
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _ACTIVE_EXECUTIONS[exec_id] = (container_name, proc)

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
        except asyncio.CancelledError:
            try:
                subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            except Exception:
                pass
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    pass
            raise
        except asyncio.TimeoutError:
            timed_out = True
            try:
                subprocess.run(["docker", "kill", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
            if proc:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
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
        _ACTIVE_EXECUTIONS.pop(exec_id, None)
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


@app.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    _auth: bool = Depends(verify_service_token)
):
    """Terminates an active sandbox execution container by execution_id."""
    entry = _ACTIVE_EXECUTIONS.pop(execution_id.strip(), None)
    if not entry:
        return {"cancelled": False, "execution_id": execution_id, "reason": "not_running"}

    container_name, proc = entry
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
    if proc is not None:
        try:
            proc.kill()
        except Exception:
            pass
    return {"cancelled": True, "execution_id": execution_id, "container_name": container_name}


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
