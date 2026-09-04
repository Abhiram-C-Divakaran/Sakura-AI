"""
Sakura AI — Symmetric Secret Encryption at Rest
Uses Fernet encryption with a key derived via SHA-256 from the application JWT_SECRET.
Ensures integration tokens, OAuth secrets, and credentials are never persisted in plaintext.
"""
import base64
import hashlib
from cryptography.fernet import Fernet
from config.settings import get_settings


def _get_fernet_instance() -> Fernet:
    settings = get_settings()
    # Derive a 32-byte key from jwt_secret using SHA-256
    digest = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypts a secret string at rest returning a URL-safe base64 ciphertext."""
    if not plaintext:
        return ""
    f = _get_fernet_instance()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypts ciphertext at rest returning original plaintext string."""
    if not ciphertext:
        return ""
    f = _get_fernet_instance()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""
