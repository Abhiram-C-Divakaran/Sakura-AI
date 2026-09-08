"""
Sakura AI — Cryptographic Sandbox Execution Capabilities
Mints, verifies, and consumes HMAC-SHA256 execution capability tokens with
atomic one-time nonce replay protection, replacing direct database lookups
inside the sandbox executor service.
"""

import os
import time
import json
import uuid
import hmac
import base64
import hashlib
import logging
from typing import Optional, Dict, Any, Union, List

logger = logging.getLogger("sakura.coding.capabilities")

CAPABILITY_VERSION = "1.0"
DEFAULT_CAPABILITY_TTL_SECONDS = 60

# In-memory fallback nonce set for test/dev when Redis is unavailable
_LOCAL_NONCE_CACHE: Dict[str, float] = {}


def clear_consumed_capabilities() -> None:
    """Clears local nonce cache for test isolation."""
    _LOCAL_NONCE_CACHE.clear()


class CapabilityError(Exception):
    """Base exception for sandbox capability validation failures."""
    pass


class CapabilitySignatureError(CapabilityError):
    pass


class CapabilityExpiredError(CapabilityError):
    pass


class CapabilityReplayError(CapabilityError):
    pass


class CapabilityScopeError(CapabilityError):
    pass


class CapabilityMismatchError(CapabilityError):
    pass


def get_capability_signing_key() -> str:
    """Resolves the dedicated signing secret from environment."""
    key = os.getenv("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY", "").strip()
    if not key:
        env = os.getenv("ENVIRONMENT", "development").lower()
        if env in ["production", "prod"]:
            raise RuntimeError(
                "FATAL PRODUCTION SECURITY ERROR: SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY must be configured in production."
            )
        return "sakura_dev_capability_signing_key_32_chars_ok!"
    return key


def compute_command_hash(command: Union[str, List[str]]) -> str:
    """Produces a deterministic SHA-256 hash of a command string or argument list."""
    if isinstance(command, list):
        canonical_str = "\x1f".join(str(part) for part in command)
    else:
        canonical_str = str(command).strip()
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def compute_url_hash(url: Optional[str]) -> Optional[str]:
    """Produces SHA-256 hash of a normalized repository URL."""
    if not url:
        return None
    normalized = url.strip().rstrip("/").lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mint_sandbox_capability(
    workspace_id: Union[str, uuid.UUID],
    command: Union[str, List[str]],
    scope: str = "network_exec",
    authorization_id: Optional[Union[str, uuid.UUID]] = None,
    ttl_seconds: int = DEFAULT_CAPABILITY_TTL_SECONDS,
    repository_url: Optional[str] = None,
    branch: Optional[str] = None,
    secret_key: Optional[str] = None
) -> str:
    """
    Cryptographically mints a signed execution capability token.
    Binds version, authorization_id, scope, workspace_id, command_hash, expiry, and nonce.
    """
    key = (secret_key or get_capability_signing_key()).encode("utf-8")
    now = time.time()
    expires_at = now + ttl_seconds
    nonce = uuid.uuid4().hex
    auth_id_str = str(authorization_id or uuid.uuid4())

    payload = {
        "version": CAPABILITY_VERSION,
        "auth_id": auth_id_str,
        "scope": scope,
        "ws_id": str(workspace_id),
        "cmd_hash": compute_command_hash(command),
        "issued_at": now,
        "expires_at": expires_at,
        "nonce": nonce,
        "repo_hash": compute_url_hash(repository_url),
        "branch": branch.strip() if branch else None,
    }

    raw_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    sig_bytes = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_hex = sig_bytes.hex()

    return f"{payload_b64}.{sig_hex}"


def decode_capability_payload(capability_token: str) -> Dict[str, Any]:
    """Decodes capability payload without signature verification (for inspect/debug)."""
    if not capability_token or "." not in capability_token:
        raise CapabilityError("Malformed capability token format.")
    payload_b64, _ = capability_token.split(".", 1)
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)
    try:
        raw_json = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        return json.loads(raw_json.decode("utf-8"))
    except Exception as e:
        raise CapabilityError(f"Failed to decode capability payload: {e}") from e


def _consume_nonce_redis(nonce: str, ttl_seconds: int) -> bool:
    """Attempts atomic nonce consumption in Redis via SET NX EX."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        nonce_key = f"sakura:capability:nonce:{nonce}"
        res = client.set(nonce_key, "used", nx=True, ex=max(int(ttl_seconds) + 10, 120))
        return bool(res)
    except Exception as e:
        logger.debug(f"Redis capability nonce check unavailable: {e}")
        return False


def _consume_nonce_memory(nonce: str, expires_at: float) -> bool:
    """Fallback in-memory nonce cache for dev/test environments."""
    now = time.time()
    # Prune expired nonces
    expired = [k for k, exp in _LOCAL_NONCE_CACHE.items() if exp < now]
    for k in expired:
        _LOCAL_NONCE_CACHE.pop(k, None)

    if nonce in _LOCAL_NONCE_CACHE:
        return False
    _LOCAL_NONCE_CACHE[nonce] = expires_at
    return True


def consume_nonce(nonce: str, expires_at: float) -> bool:
    """Atomically consumes capability nonce, prioritizing Redis in production."""
    ttl_seconds = max(int(expires_at - time.time()), 1)
    env = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = env in ["production", "prod"]

    consumed = _consume_nonce_redis(nonce, ttl_seconds)
    if consumed:
        return True

    if is_prod:
        # In production, require Redis atomic state for multiple executor replicas
        logger.error("Production capability verification failed: Redis nonce store unavailable.")
        return False

    return _consume_nonce_memory(nonce, expires_at)


def verify_and_consume_capability(
    capability_token: str,
    expected_scope: Optional[Union[str, List[str], Set[str]]] = None,
    expected_workspace_id: Optional[Union[str, uuid.UUID]] = None,
    expected_command: Optional[Union[str, List[str]]] = None,
    expected_repository_url: Optional[str] = None,
    expected_branch: Optional[str] = None,
    secret_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Verifies capability signature, expiration, scope, workspace, and command bindings,
    and consumes the one-time nonce atomically.
    Fails closed on any discrepancy.
    """
    if not capability_token or "." not in capability_token:
        raise CapabilityError("Malformed capability token format.")

    payload_b64, provided_sig = capability_token.split(".", 1)
    key = (secret_key or get_capability_signing_key()).encode("utf-8")

    expected_sig = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise CapabilitySignatureError("Capability signature verification failed.")

    payload = decode_capability_payload(capability_token)

    # 1. Version
    if payload.get("version") != CAPABILITY_VERSION:
        raise CapabilityError(f"Unsupported capability version '{payload.get('version')}'.")

    # 2. Expiry
    now = time.time()
    expires_at = float(payload.get("expires_at", 0))
    if expires_at <= now:
        raise CapabilityExpiredError(f"Capability expired at {expires_at} (current time {now}).")

    # 3. Scope
    actual_scope = payload.get("scope")
    if expected_scope is not None:
        if isinstance(expected_scope, (list, tuple, set)):
            if actual_scope not in expected_scope:
                raise CapabilityScopeError(f"Capability scope mismatch: expected one of {expected_scope}, got '{actual_scope}'.")
        elif actual_scope != expected_scope:
            raise CapabilityScopeError(f"Capability scope mismatch: expected '{expected_scope}', got '{actual_scope}'.")

    # 4. Workspace match
    if expected_workspace_id is not None:
        actual_ws_id = payload.get("ws_id")
        if str(actual_ws_id).strip() != str(expected_workspace_id).strip():
            raise CapabilityMismatchError(f"Capability workspace mismatch: expected '{expected_workspace_id}', got '{actual_ws_id}'.")

    # 5. Command hash match
    if expected_command is not None:
        expected_cmd_hash = compute_command_hash(expected_command)
        actual_cmd_hash = payload.get("cmd_hash")
        if actual_cmd_hash != expected_cmd_hash:
            raise CapabilityMismatchError("Capability command hash mismatch.")

    # 6. Repository bindings if applicable
    if expected_repository_url is not None:
        expected_repo_hash = compute_url_hash(expected_repository_url)
        actual_repo_hash = payload.get("repo_hash")
        if actual_repo_hash != expected_repo_hash:
            raise CapabilityMismatchError("Capability repository URL hash mismatch.")

    if expected_branch is not None and payload.get("branch"):
        if payload.get("branch") != expected_branch.strip():
            raise CapabilityMismatchError("Capability branch mismatch.")

    # 7. One-time nonce consumption
    nonce = payload.get("nonce")
    if not nonce:
        raise CapabilityError("Missing capability nonce.")

    if not consume_nonce(nonce, expires_at):
        raise CapabilityReplayError("Capability token has already been consumed or replayed.")

    return payload
