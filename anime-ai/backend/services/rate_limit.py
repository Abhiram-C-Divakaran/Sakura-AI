"""
Sakura AI — Sliding-Window Rate Limiter
Provides Redis-backed rate limiting with a thread-safe in-memory fallback for
single-node dev/test environments.
"""

import os
import time
import threading
from collections import deque
from typing import Dict, Deque
from fastapi import HTTPException, Request, status

_LOCAL_BUCKETS: Dict[str, Deque[float]] = {}
_LOCAL_LOCK = threading.Lock()


def reset_rate_limits() -> None:
    """Clears local rate-limit buckets (used for test isolation)."""
    with _LOCAL_LOCK:
        _LOCAL_BUCKETS.clear()


def get_client_ip(request: Request) -> str:
    """Extracts client IP cleanly without trusting unbounded headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _check_redis_limit(redis_key: str, limit: int, window_seconds: int):
    redis_url = os.getenv("REDIS_URL", "")
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


def enforce_rate_limit(bucket: str, identifier: str, limit: int, window_seconds: int) -> None:
    """
    Enforces a bounded request rate for (bucket, identifier).
    Raises HTTP 429 when the limit is exceeded.
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
