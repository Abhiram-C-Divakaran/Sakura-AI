#!/usr/bin/env python3
"""
Sakura AI — Production / Staging Environment Pre-Flight Validator
Checks all required runtime secrets, driver consistency, proxy CIDRs,
canonical URLs, and storage configuration before starting services.

Exit code 0: all checks passed.
Exit code 1: one or more blocking configuration errors found.
"""

import os
import sys
import ipaddress
from urllib.parse import urlparse
from typing import List, Tuple

PLACEHOLDER_SUBSTRINGS = (
    "changeme",
    "change-me",
    "replace-me",
    "your-secret",
    "your_secret",
    "example",
    "todo",
    "test-secret",
)


def _looks_placeholder(val: str) -> bool:
    low = val.strip().lower()
    return any(p in low for p in PLACEHOLDER_SUBSTRINGS)


def validate_environment(env: dict) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    environment = (env.get("ENVIRONMENT") or "production").strip().lower()
    is_prod = environment in ("production", "prod", "staging")

    # 1. Required secrets & minimum entropy length
    secret_specs = [
        ("POSTGRES_PASSWORD", 12),
        ("JWT_SECRET", 32),
        ("INTEGRATION_ENCRYPTION_KEY", 32),
        ("SAKURA_SANDBOX_SERVICE_TOKEN", 24),
        ("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY", 32),
    ]
    for name, min_len in secret_specs:
        val = (env.get(name) or "").strip()
        if not val:
            errors.append(f"{name} is missing.")
        elif len(val) < min_len:
            errors.append(f"{name} must be at least {min_len} characters (got {len(val)}).")
        elif is_prod and _looks_placeholder(val):
            errors.append(f"{name} appears to contain a placeholder value.")

    # 2. Database URL driver consistency
    db_url = (env.get("DATABASE_URL") or "").strip()
    if db_url:
        if db_url.startswith("sqlite"):
            errors.append("DATABASE_URL must use PostgreSQL (postgresql+psycopg2://) in staging/production, not SQLite.")
        elif db_url.startswith(("postgresql://", "postgres://")):
            warnings.append("DATABASE_URL uses generic postgresql://; explicitly set postgresql+psycopg2:// for clarity.")
        elif not db_url.startswith("postgresql+psycopg2://"):
            errors.append(f"Unsupported DATABASE_URL scheme: {db_url.split('://', 1)[0]}")

    # 3. Redis URL required for rate limiting, queues, and capability replay protection
    redis_url = (env.get("REDIS_URL") or "").strip()
    if not redis_url:
        errors.append("REDIS_URL is required for durable queues, rate limiting, and sandbox capability replay protection.")
    elif not redis_url.startswith(("redis://", "rediss://")):
        errors.append("REDIS_URL must start with redis:// or rediss://.")

    # 4. Embedded workers must be disabled in multi-service deployments
    for flag in ("SAKURA_EMBEDDED_WORKER", "SAKURA_EMBEDDED_SCHEDULER", "SAKURA_EMBEDDED_CODING_WORKER"):
        if (env.get(flag) or "false").strip().lower() == "true":
            errors.append(f"{flag} must be 'false' in staging/production (run dedicated worker services instead).")

    # 5. Storage backend configuration
    storage_backend = (env.get("SAKURA_STORAGE_BACKEND") or "s3").strip().lower()
    if storage_backend == "s3":
        for key in ("SAKURA_STORAGE_BUCKET", "SAKURA_STORAGE_ACCESS_KEY", "SAKURA_STORAGE_SECRET_KEY"):
            if not (env.get(key) or "").strip():
                errors.append(f"{key} is required when SAKURA_STORAGE_BACKEND=s3.")
    elif storage_backend == "local":
        storage_root = (env.get("SAKURA_STORAGE_ROOT") or "").strip()
        if not storage_root or not os.path.isabs(storage_root) or storage_root.endswith("uploaded_documents"):
            errors.append("SAKURA_STORAGE_ROOT must be an absolute durable mount path (e.g. /data/library) for local backend.")
        warnings.append("SAKURA_STORAGE_BACKEND=local is single-node only; use S3-compatible object storage for multi-replica deployments.")
    else:
        errors.append(f"Unsupported SAKURA_STORAGE_BACKEND: {storage_backend}")

    # 6. Trusted proxy CIDRs for proxy-aware rate limiting (strict explicit CIDR policy)
    proxy_cidrs = (env.get("TRUSTED_PROXY_CIDRS") or "").strip()
    if not proxy_cidrs:
        if is_prod:
            errors.append("TRUSTED_PROXY_CIDRS must be explicitly configured in staging/production (e.g., 127.0.0.1/32 or your exact proxy CIDR).")
        else:
            warnings.append("TRUSTED_PROXY_CIDRS is unset; X-Forwarded-For headers will be ignored.")
    else:
        for item in proxy_cidrs.split(","):
            entry = item.strip()
            if not entry:
                continue
            try:
                net = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                errors.append(f"Invalid CIDR in TRUSTED_PROXY_CIDRS: '{entry}'")
                continue
            if net.prefixlen == 0:
                errors.append(f"Wildcard CIDR '{entry}' is forbidden in TRUSTED_PROXY_CIDRS.")
            elif isinstance(net, ipaddress.IPv4Network) and net.prefixlen < 8:
                errors.append(f"Overly broad IPv4 CIDR '{entry}' is forbidden in TRUSTED_PROXY_CIDRS.")
            elif isinstance(net, ipaddress.IPv4Network) and net.prefixlen <= 12:
                warnings.append(f"TRUSTED_PROXY_CIDRS contains a broad range ('{entry}'); prefer the exact reverse-proxy subnet/IP.")

    # 7. SMTP & canonical PUBLIC_APP_URL consistency
    smtp_host = (env.get("SMTP_HOST") or "").strip()
    smtp_from = (env.get("SMTP_FROM_EMAIL") or "").strip()
    public_url = (env.get("PUBLIC_APP_URL") or "").strip()
    if smtp_host or smtp_from:
        if not (smtp_host and smtp_from):
            errors.append("Both SMTP_HOST and SMTP_FROM_EMAIL must be set together.")
        if not public_url:
            errors.append("PUBLIC_APP_URL (https://...) is required when SMTP password reset is enabled.")
        else:
            parsed = urlparse(public_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not host or host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                errors.append(f"PUBLIC_APP_URL must be a canonical non-localhost https:// URL (got '{public_url}').")
    else:
        warnings.append("SMTP_HOST / SMTP_FROM_EMAIL not set; password reset will remain disabled truthfully.")

    # 8. At least one LLM provider configured
    llm_keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_HOST")
    if not any((env.get(k) or "").strip() for k in llm_keys):
        warnings.append("No LLM provider key configured (OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY, or OLLAMA_BASE_URL).")

    return errors, warnings


def main() -> int:
    errors, warnings = validate_environment(dict(os.environ))
    for w in warnings:
        print(f"[WARN]  {w}")
    for e in errors:
        print(f"[ERROR] {e}", file=sys.stderr)
    if errors:
        print(f"\nEnvironment validation FAILED with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print(f"\nEnvironment validation PASSED ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
