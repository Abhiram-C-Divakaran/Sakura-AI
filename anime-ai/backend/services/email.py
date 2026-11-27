"""
Sakura AI — Email Delivery Service
Sends transactional emails (such as password reset links) through an explicitly
configured SMTP provider and canonical PUBLIC_APP_URL. Never fakes email delivery
or generates localhost reset URLs in production.
"""

import os
import smtplib
from typing import Optional
from urllib.parse import urlparse
from email.message import EmailMessage


class EmailNotConfiguredError(RuntimeError):
    """Raised when email delivery is requested but no email provider is configured."""
    pass


def is_email_configured() -> bool:
    """Returns True only when SMTP host and sender address are explicitly configured."""
    host = (os.getenv("SMTP_HOST") or "").strip()
    sender = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    return bool(host and sender)


def get_canonical_public_app_url() -> Optional[str]:
    """
    Returns the canonical base URL for external links (e.g. password reset).
    - In production: PUBLIC_APP_URL MUST be explicitly configured with https://
      and MUST NOT reference localhost or loopback addresses.
    - In development/test: returns PUBLIC_APP_URL if set, else http://localhost:3000.
    """
    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    is_prod = env in ("production", "prod")
    raw = (os.getenv("PUBLIC_APP_URL") or "").strip().rstrip("/")

    if is_prod:
        if not raw:
            return None
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return None
        return raw

    if raw:
        parsed = urlparse(raw)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            return raw
        return None
    return "http://localhost:3000"


def is_password_reset_enabled() -> bool:
    """Returns True only when both SMTP delivery and a valid canonical PUBLIC_APP_URL are configured."""
    return is_email_configured() and bool(get_canonical_public_app_url())


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    """
    Sends a password reset link via configured SMTP server.
    Raises EmailNotConfiguredError if SMTP is not configured.
    """
    host = (os.getenv("SMTP_HOST") or "").strip()
    sender = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    if not host or not sender:
        raise EmailNotConfiguredError(
            "Password reset email delivery is not configured on this deployment."
        )

    port = int(os.getenv("SMTP_PORT", "587"))
    username = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    msg = EmailMessage()
    msg["Subject"] = "Reset your Sakura AI password"
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(
        "We received a request to reset your Sakura AI password.\n\n"
        f"Use this single-use link (valid for 30 minutes):\n{reset_url}\n\n"
        "If you did not request a password reset, you can safely ignore this message.\n"
    )

    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.send_message(msg)
