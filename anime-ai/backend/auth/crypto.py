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
    is_prod = settings.environment in ["production", "prod"]
    if is_prod and not settings.integration_encryption_key:
        raise ValueError(
            "Production security error: INTEGRATION_ENCRYPTION_KEY must be configured "
            "independently of JWT_SECRET."
        )
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
    pt, _ = decrypt_and_upgrade_secret(ciphertext, custom_key)
    return pt


def decrypt_and_upgrade_secret(ciphertext: str, custom_key: Optional[str] = None) -> tuple:
    """
    Decrypts ciphertext and determines if it requires rotation/re-encryption.
    Returns (plaintext, upgraded_ciphertext_or_none).
    If the ciphertext was legacy (plain unversioned or decrypted via legacy JWT key),
    returns the plaintext and newly encrypted versioned envelope using the current
    INTEGRATION_ENCRYPTION_KEY.
    """
    if not ciphertext or not isinstance(ciphertext, str):
        return "", None

    raw_payload = ciphertext.strip()
    is_versioned = False
    target_ct = raw_payload

    if raw_payload.startswith("{") and raw_payload.endswith("}"):
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict) and "ciphertext" in parsed:
                target_ct = parsed["ciphertext"]
                is_versioned = True
        except Exception:
            target_ct = raw_payload

    # 1. Try decrypting with integration encryption key
    f_int = _get_integration_fernet(custom_key)
    try:
        plaintext = f_int.decrypt(target_ct.encode("utf-8")).decode("utf-8")
        if is_versioned:
            return plaintext, None
        return plaintext, encrypt_secret(plaintext, custom_key)
    except Exception:
        pass

    # 2. Transparent backward compatibility: Try decrypting with legacy JWT_SECRET key
    try:
        f_legacy = _get_legacy_fernet()
        plaintext = f_legacy.decrypt(target_ct.encode("utf-8")).decode("utf-8")
        # Upgrade legacy encryption to current INTEGRATION_ENCRYPTION_KEY
        new_envelope = encrypt_secret(plaintext, custom_key)
        return plaintext, new_envelope
    except Exception:
        return "", None
