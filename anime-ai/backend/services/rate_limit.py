"""
Sakura AI — Proxy-Aware Sliding-Window Rate Limiter
Provides Redis-backed rate limiting with:
- Strict trusted-proxy CIDR handling for X-Forwarded-For (never trusts spoofed headers)
- Fail-closed behavior in production when Redis is unavailable on security-sensitive endpoints
- Thread-safe in-memory fallback strictly for development/test environments
"""

import os
import time
import ipaddress
import threading
from collections import deque
from typing import Dict, Deque, List, Union
from fastapi import HTTPException, Request, status

_LOCAL_BUCKETS: Dict[str, Deque[float]] = {}
_LOCAL_LOCK = threading.Lock()

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


def reset_rate_limits() -> None:
    """Clears local rate-limit buckets (used for test isolation)."""
    with _LOCAL_LOCK:
        _LOCAL_BUCKETS.clear()


def validate_trusted_proxy_cidrs(raw: str | None) -> tuple[List[IPNetwork], List[str]]:
    """
    Parses and strictly validates comma-separated trusted proxy CIDRs/IPs.
    Rejects malformed entries and overly broad wildcard CIDRs (0.0.0.0/0, ::/0).
    Returns (valid_networks, errors).
    """
    text = (raw or "").strip()
    if not text:
        return [], []
    networks: List[IPNetwork] = []
    errors: List[str] = []
    for entry in text.split(","):
        item = entry.strip()
        if not item:
            continue
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            errors.append(f"Invalid CIDR in TRUSTED_PROXY_CIDRS: '{item}'")
            continue
        if net.prefixlen == 0:
            errors.append(f"Wildcard CIDR '{item}' is forbidden in TRUSTED_PROXY_CIDRS.")
            continue
        if isinstance(net, ipaddress.IPv4Network) and net.prefixlen < 8:
            errors.append(f"Overly broad IPv4 CIDR '{item}' is forbidden in TRUSTED_PROXY_CIDRS.")
            continue
        networks.append(net)
    return networks, errors


def _parse_trusted_proxy_cidrs() -> List[IPNetwork]:
    nets, _ = validate_trusted_proxy_cidrs(os.getenv("TRUSTED_PROXY_CIDRS"))
    return nets


def _ip_in_networks(ip_str: str, networks: List[IPNetwork]) -> bool:
    if not ip_str or not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False
    return any(addr in net for net in networks)


def get_client_ip(request: Request) -> str:
    """
    Extracts canonical client IP safely:
    - Only trusts X-Forwarded-For when request.client.host belongs to TRUSTED_PROXY_CIDRS.
    - When trusted, walks X-Forwarded-For right-to-left skipping trusted proxy hops so
      attacker-prepended spoofed IPs are ignored.
    - When TRUSTED_PROXY_CIDRS is unset or peer is untrusted, ignores X-Forwarded-For completely.
    """
    peer_ip = (request.client.host if request.client and request.client.host else "").strip()
    trusted_nets = _parse_trusted_proxy_cidrs()

    if peer_ip and trusted_nets and _ip_in_networks(peer_ip, trusted_nets):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            # Walk right-to-left (nearest proxy -> furthest), returning first non-trusted IP
            for candidate in reversed(hops):
                try:
                    ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                if not _ip_in_networks(candidate, trusted_nets):
                    return candidate
            if hops:
                return hops[0]

    return peer_ip or "unknown"


def _check_redis_limit(redis_key: str, limit: int, window_seconds: int):
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None
    client = None
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        pipe = client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def enforce_rate_limit(
    bucket: str,
    identifier: str,
    limit: int,
    window_seconds: int,
    *,
    fail_closed_in_prod: bool = False,
) -> None:
    """
    Enforces a bounded request rate for (bucket, identifier).
    - Raises HTTP 429 when the limit is exceeded.
    - In production, when fail_closed_in_prod=True and Redis is unavailable,
      raises HTTP 503 rather than silently downgrading to per-worker local memory.
    """
    if os.getenv("SAKURA_DISABLE_RATE_LIMITS", "false").lower() == "true":
        return

    key = f"sakura:rl:{bucket}:{identifier}"
    redis_allowed = _check_redis_limit(key, limit, window_seconds)
    if redis_allowed is True:
        return
    if redis_allowed is False:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait before trying again.",
        )

    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    is_prod = env in ("production", "prod")
    if is_prod and fail_closed_in_prod:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting backend is temporarily unavailable. Please retry shortly.",
        )

    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCAL_LOCK:
        dq = _LOCAL_BUCKETS.get(key)
        if dq is None:
            dq = deque()
            _LOCAL_BUCKETS[key] = dq
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait before trying again.",
            )
        dq.append(now)
