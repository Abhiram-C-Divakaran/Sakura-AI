"""
Sakura AI — Durable Multi-Worker Per-User Usage Quotas
Enforces persistent daily usage caps across chat, image generation, coding tasks,
file uploads, and scheduled jobs using transaction-safe atomic database updates.
"""

import os
import uuid
from typing import Dict, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.models import UserUsageQuota, utc_now

DEFAULT_DAILY_QUOTAS: Dict[str, tuple[str, int]] = {
    "chat": ("SAKURA_QUOTA_CHAT_DAILY", 500),
    "image_generation": ("SAKURA_QUOTA_IMAGE_DAILY", 50),
    "coding_task": ("SAKURA_QUOTA_CODING_DAILY", 50),
    "file_upload": ("SAKURA_QUOTA_UPLOAD_DAILY", 100),
    "scheduled_job": ("SAKURA_QUOTA_SCHEDULED_DAILY", 30),
}


def get_daily_quota_limit(category: str) -> int:
    """Returns configured daily quota limit for a usage category."""
    if category not in DEFAULT_DAILY_QUOTAS:
        raise ValueError(f"Unknown quota category: {category}")
    env_var, default_limit = DEFAULT_DAILY_QUOTAS[category]
    raw = (os.getenv(env_var) or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return default_limit


def current_quota_window_key() -> str:
    """Returns the canonical UTC daily window key (YYYY-MM-DD)."""
    return utc_now().strftime("%Y-%m-%d")


def reserve_user_quota_in_session(
    db: Session,
    user_id: uuid.UUID,
    category: str,
    amount: int = 1,
) -> Dict[str, Any]:
    """
    Atomically checks and reserves `amount` units against a user's daily quota
    WITHOUT committing the caller's outer database transaction.
    - Uses a SAVEPOINT (`begin_nested`) to safely initialize the counter row on race.
    - Performs an atomic conditional UPDATE (`usage_count + amount <= limit`) safe across
      concurrent PostgreSQL and SQLite workers.
    - If the caller rolls back the transaction (e.g., job creation fails), the quota
      reservation automatically rolls back atomically.
    Raises HTTP 429 when the quota is insufficient.
    """
    limit = get_daily_quota_limit(category)
    step = max(1, int(amount))
    window_key = current_quota_window_key()

    if os.getenv("SAKURA_DISABLE_QUOTAS", "false").lower() == "true":
        return {
            "category": category,
            "window": window_key,
            "used": 0,
            "limit": limit,
            "remaining": limit,
        }

    if limit < step:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily usage quota exceeded for {category} (requested {step}, limit: {limit} per UTC day).",
        )

    now = utc_now()
    existing = db.query(UserUsageQuota).filter(
        UserUsageQuota.user_id == user_id,
        UserUsageQuota.category == category,
        UserUsageQuota.window_key == window_key,
    ).first()

    if existing is None:
        try:
            with db.begin_nested():
                db.add(
                    UserUsageQuota(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        category=category,
                        window_key=window_key,
                        usage_count=0,
                        updated_at=now,
                    )
                )
                db.flush()
        except IntegrityError:
            # Another concurrent worker inserted the window row first; savepoint rolled back cleanly.
            pass

    updated = db.query(UserUsageQuota).filter(
        UserUsageQuota.user_id == user_id,
        UserUsageQuota.category == category,
        UserUsageQuota.window_key == window_key,
        (UserUsageQuota.usage_count + step) <= limit,
    ).update(
        {
            UserUsageQuota.usage_count: UserUsageQuota.usage_count + step,
            UserUsageQuota.updated_at: now,
        },
        synchronize_session=False,
    )
    if updated != 1:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily usage quota exceeded for {category} (limit: {limit} per UTC day).",
        )

    rec = db.query(UserUsageQuota).filter(
        UserUsageQuota.user_id == user_id,
        UserUsageQuota.category == category,
        UserUsageQuota.window_key == window_key,
    ).first()
    used = int(rec.usage_count) if rec else step
    return {
        "category": category,
        "window": window_key,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
    }


def enforce_user_quota(
    db: Session,
    user_id: uuid.UUID,
    category: str,
    amount: int = 1,
) -> Dict[str, Any]:
    """
    Standalone quota check + commit for endpoints that do not require an enclosing transaction.
    """
    try:
        res = reserve_user_quota_in_session(db, user_id, category, amount=amount)
        db.commit()
        return res
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def get_user_quota_summary(db: Session, user_id: uuid.UUID) -> Dict[str, Any]:
    """Returns current UTC day quota usage across all tracked categories."""
    window_key = current_quota_window_key()
    rows = db.query(UserUsageQuota).filter(
        UserUsageQuota.user_id == user_id,
        UserUsageQuota.window_key == window_key,
    ).all()
    counts = {r.category: int(r.usage_count or 0) for r in rows}

    summary = {}
    for category in DEFAULT_DAILY_QUOTAS:
        limit = get_daily_quota_limit(category)
        used = counts.get(category, 0)
        summary[category] = {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
        }
    return {"window": window_key, "quotas": summary}
