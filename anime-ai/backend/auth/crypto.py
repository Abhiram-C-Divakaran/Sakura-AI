"""
Sakura AI — Symmetric Secret Encryption at Rest
Uses Fernet encryption with an independent INTEGRATION_ENCRYPTION_KEY separate from JWT_SECRET.
Ensures integration tokens, OAuth secrets, and third-party credentials are never persisted in plaintext.
Supports versioned encrypted payloads with transparent backward-compatibility for legacy JWT-derived ciphertexts.
"""
import json
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from config.settings import get_settings


def _derive_fernet(secret_str: str) -> Fernet:
    """Derives a deterministic 32-byte Fernet key from any high-entropy secret string."""
    digest = hashlib.sha256(secret_str.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _get_integration_fernet(custom_key: Optional[str] = None) -> Fernet:
    """Returns the canonical Fernet instance derived from INTEGRATION_ENCRYPTION_KEY."""
    if custom_key:
        return _derive_fernet(custom_key)
    settings = get_settings()
    key_str = settings.integration_encryption_key or settings.jwt_secret
    return _derive_fernet(key_str)


def _get_legacy_fernet() -> Fernet:
    """Returns the legacy Fernet instance derived from JWT_SECRET for migration."""
    settings = get_settings()
    return _derive_fernet(settings.jwt_secret)


def encrypt_secret(plaintext: str, custom_key: Optional[str] = None) -> str:
    """
    Encrypts a secret string using the dedicated integration encryption key.
    Returns a versioned JSON envelope: {"version": 1, "ciphertext": "..."}.
    """
    if not plaintext:
        return ""
    f = _get_integration_fernet(custom_key)
    ct = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return json.dumps({"version": 1, "ciphertext": ct})


def decrypt_secret(ciphertext: str, custom_key: Optional[str] = None) -> str:
    """
    Decrypts a stored ciphertext string.
    First attempts decryption of versioned envelope with the current integration encryption key.
    Falls back transparently to legacy JWT_SECRET-derived decryption for backward compatibility.
    """
    if not ciphertext or not isinstance(ciphertext, str):
        return ""

    raw_payload = ciphertext.strip()
    target_ct = raw_payload

    # 1. Attempt parsing versioned JSON envelope
    if raw_payload.startswith("{") and raw_payload.endswith("}"):
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict) and "ciphertext" in parsed:
                target_ct = parsed["ciphertext"]
        except Exception:
            target_ct = raw_payload

    # 2. Try decrypting with integration encryption key
    f_int = _get_integration_fernet(custom_key)
    try:
        return f_int.decrypt(target_ct.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        pass

    # 3. Transparent backward compatibility: Try decrypting with legacy JWT_SECRET key
    try:
        f_legacy = _get_legacy_fernet()
        return f_legacy.decrypt(target_ct.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""
