"""
Sakura AI — Email Delivery Service
Sends transactional emails (such as password reset links) through an explicitly
configured SMTP provider. Never fakes email delivery when unconfigured.
"""

import os
import smtplib
from email.message import EmailMessage


class EmailNotConfiguredError(RuntimeError):
    """Raised when email delivery is requested but no email provider is configured."""
    pass


def is_email_configured() -> bool:
    """Returns True only when SMTP host and sender address are explicitly configured."""
    host = (os.getenv("SMTP_HOST") or "").strip()
    sender = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    return bool(host and sender)


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
