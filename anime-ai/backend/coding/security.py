import os
import re
from typing import List

class SecurityException(Exception):
    """Raised when a path or command violates security policy."""
    pass

class WorkspaceSecurity:
    """Enforces sandbox boundary constraints on file paths and shell operations."""

    BLOCKED_COMMAND_PATTERNS = [
        r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+/",
        r"\bmkfs\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bdd\s+if=",
        r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # Fork bomb
        r"\bdrop\s+database\b",
        r"\bformat\s+[c-zC-Z]:",
    ]

    DISALLOWED_ENV_VARS = {
        "JWT_SECRET",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "TAVILY_API_KEY",
        "COHERE_API_KEY",
    }

    @staticmethod
    def resolve_safe_path(workspace_root: str, relative_path: str) -> str:
        """
        Resolves relative_path within workspace_root.
        Guarantees that the resulting canonical path cannot escape workspace_root.
        """
        canonical_root = os.path.realpath(os.path.abspath(workspace_root))
        
        # Clean leading slashes/backslashes to prevent absolute path override
        cleaned = relative_path.replace("\\", "/")
        if cleaned.startswith("/"):
            cleaned = cleaned.lstrip("/")
            
        target = os.path.realpath(os.path.abspath(os.path.join(canonical_root, cleaned)))
        
        # Verify prefix containment
        common = os.path.commonpath([canonical_root, target])
        if common != canonical_root:
            raise SecurityException(
                f"Path traversal detected: '{relative_path}' escapes workspace root '{workspace_root}'"
            )
            
        return target

    @staticmethod
    def validate_command(command: str) -> None:
        """Checks for obviously destructive or hostile shell commands."""
        for pattern in WorkspaceSecurity.BLOCKED_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise SecurityException(f"Command rejected by security policy: matches forbidden pattern '{pattern}'")

    @staticmethod
    def sanitize_environment(base_env: dict = None) -> dict:
        """Strips backend secrets and sensitive keys from the environment passed to code runs."""
        env = dict(base_env or os.environ)
        for secret_key in WorkspaceSecurity.DISALLOWED_ENV_VARS:
            env.pop(secret_key, None)
        # Force non-interactive modes
        env["CI"] = "true"
        env["NONINTERACTIVE"] = "1"
        env["DEBIAN_FRONTEND"] = "noninteractive"
        return env

resolve_safe_path = WorkspaceSecurity.resolve_safe_path
validate_command = WorkspaceSecurity.validate_command
sanitize_environment = WorkspaceSecurity.sanitize_environment
SecurityViolationError = SecurityException

def is_command_safe(command: str) -> bool:
    try:
        WorkspaceSecurity.validate_command(command)
        return True
    except SecurityException:
        return False
