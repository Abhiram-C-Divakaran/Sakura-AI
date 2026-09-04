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
        Rejects:
        - Absolute POSIX paths (e.g. /etc/passwd)
        - Windows absolute drive paths (e.g. C:\\...)
        - UNC paths (e.g. \\\\server\\share)
        - Relative traversals escaping workspace root (e.g. ../../foo)
        - Symlink escapes through canonicalization
        """
        if not relative_path or not isinstance(relative_path, str):
            raise SecurityException("Relative path cannot be empty.")

        # Disallow null bytes
        if "\0" in relative_path:
            raise SecurityException("Path contains forbidden null byte.")

        # Reject absolute paths (POSIX, Windows drive, UNC)
        norm_path = relative_path.strip()
        if (
            norm_path.startswith("/")
            or norm_path.startswith("\\")
            or re.match(r"^[a-zA-Z]:", norm_path)
            or norm_path.startswith("//")
            or norm_path.startswith(r"\\")
            or os.path.isabs(norm_path)
        ):
            raise SecurityException(
                f"Absolute paths are not permitted as workspace-relative inputs: '{relative_path}'"
            )

        canonical_root = os.path.realpath(os.path.abspath(workspace_root))
        target = os.path.realpath(os.path.abspath(os.path.join(canonical_root, norm_path)))

        # Verify prefix containment
        try:
            common = os.path.commonpath([canonical_root, target])
        except ValueError:
            # Different drives on Windows
            raise SecurityException(
                f"Path traversal detected: '{relative_path}' resolves to different drive than workspace root."
            )

        if common != canonical_root or (target != canonical_root and not target.startswith(canonical_root + os.sep)):
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

    @staticmethod
    def validate_repository_url(url: str) -> None:
        """
        Validates git repository URLs to prevent shell injection, flag injection,
        and unsupported schemes.
        """
        if not url or not isinstance(url, str):
            raise SecurityException("Repository URL cannot be empty.")
        if len(url) > 500:
            raise SecurityException("Repository URL exceeds maximum allowed length (500 chars).")

        # Reject dangerous shell metacharacters
        dangerous_chars = [";", "&", "|", "`", "$", "\n", "\r", "<", ">", "(", ")", '"', "'", "\0"]
        for ch in dangerous_chars:
            if ch in url:
                raise SecurityException(f"Repository URL contains illegal character: {repr(ch)}")

        # Disallow dangerous pseudo-schemes
        lower_url = url.lower()
        if lower_url.startswith(("-", "ext::", "fd::")):
            raise SecurityException("Repository URL contains prohibited transport prefix.")
        if any(lower_url.startswith(s) for s in ["file://", "ftp://", "gopher://", "ldap://"]):
            raise SecurityException("Repository URL scheme not allowed (must be https or git/ssh).")

        # Validate against allowed patterns (https:// or git@)
        https_pattern = r"^https://[a-zA-Z0-9._~%:-]+(/[a-zA-Z0-9._~%/-]+)+(\.git)?/?$"
        ssh_pattern = r"^git@[a-zA-Z0-9._~%-]+:[a-zA-Z0-9._~%/-]+(\.git)?$"
        if not (re.match(https_pattern, url) or re.match(ssh_pattern, url)):
            raise SecurityException("Repository URL must be a valid HTTPS or SSH Git URL.")

    @staticmethod
    def validate_branch_name(branch: str) -> None:
        """
        Validates git branch/ref names to prevent flag injection and shell exploitation.
        """
        if not branch or not isinstance(branch, str):
            raise SecurityException("Branch name cannot be empty.")
        if len(branch) > 200:
            raise SecurityException("Branch name exceeds maximum allowed length (200 chars).")
        if branch.startswith("-"):
            raise SecurityException("Branch name cannot start with a dash (flag injection protection).")

        # Git ref safe character regex
        ref_pattern = r"^[a-zA-Z0-9._/-]+$"
        if not re.match(ref_pattern, branch):
            raise SecurityException(f"Branch name '{branch}' contains invalid ref characters.")

        if ".." in branch or branch.endswith("/") or branch.endswith(".lock") or "@{" in branch:
            raise SecurityException(f"Branch name '{branch}' violates Git ref naming rules.")

resolve_safe_path = WorkspaceSecurity.resolve_safe_path
validate_command = WorkspaceSecurity.validate_command
sanitize_environment = WorkspaceSecurity.sanitize_environment
validate_repository_url = WorkspaceSecurity.validate_repository_url
validate_branch_name = WorkspaceSecurity.validate_branch_name
SecurityViolationError = SecurityException


def is_command_safe(command: str) -> bool:
    try:
        WorkspaceSecurity.validate_command(command)
        return True
    except SecurityException:
        return False
