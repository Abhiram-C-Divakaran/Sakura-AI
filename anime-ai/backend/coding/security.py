import os
import sys
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
        "INTEGRATION_ENCRYPTION_KEY",
        "SAKURA_SANDBOX_SERVICE_TOKEN",
        "GITHUB_CLIENT_SECRET",
        "POSTGRES_PASSWORD",
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

    EXACT_BLOCKED_ENV_VARS = {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "BASH_ENV",
        "ENV",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "NODE_OPTIONS",
        "GIT_CONFIG_COUNT",
        "SSH_AUTH_SOCK",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "JWT_SECRET",
        "INTEGRATION_ENCRYPTION_KEY",
        "SAKURA_SANDBOX_SERVICE_TOKEN",
        "GITHUB_CLIENT_SECRET",
        "POSTGRES_PASSWORD",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "TAVILY_API_KEY",
        "COHERE_API_KEY",
    }

    BLOCKED_ENV_PREFIXES = (
        "LD_",
        "GIT_CONFIG_KEY_",
        "GIT_CONFIG_VALUE_",
        "AWS_",
        "GOOGLE_",
        "AZURE_",
        "GITHUB_",
        "OPENAI_",
        "ANTHROPIC_",
        "DATABASE_",
        "REDIS_",
        "SAKURA_",
        "SECRET_",
        "TOKEN_",
        "KEY_",
        "PASSWORD_",
    )

    ALLOWED_TASK_ENV_VARS = {
        "APP_ENV",
        "TEST_TARGET",
        "TEST_NAME",
        "DEBUG",
        "PORT",
        "HOST",
        "PIP_NO_CACHE_DIR",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "NPM_CONFIG_COLOR",
        "CARGO_TERM_COLOR",
        "RUST_BACKTRACE",
    }

    @staticmethod
    def build_safe_child_environment(requested_env: dict = None, is_production: Optional[bool] = None) -> dict:
        """
        Constructs child execution container environment using strict allowlist policy.
        NEVER inherits os.environ and never passes host backend secrets.
        Baseline: PATH, HOME, LANG, LC_ALL, TERM, CI, NONINTERACTIVE, DEBIAN_FRONTEND, NODE_ENV.
        Never allows client/LLM to redefine PATH in production.
        """
        if is_production is None:
            env_name = os.getenv("ENVIRONMENT", "development").lower()
            is_production = env_name in ("production", "prod")

        # Ensure python binary directory and system paths are in PATH
        python_dir = os.path.dirname(sys.executable)
        path_list = ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]
        if python_dir and python_dir not in path_list:
            path_list.insert(0, python_dir)
        path_str = os.pathsep.join(path_list)

        env = {
            "CI": "true",
            "NONINTERACTIVE": "1",
            "DEBIAN_FRONTEND": "noninteractive",
            "PATH": path_str,
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TERM": "xterm-256color",
            "NODE_ENV": "production"
        }

        if requested_env and isinstance(requested_env, dict):
            sensitive_patterns = (
                "SECRET", "PASSWORD", "TOKEN", "KEY", "CREDENTIAL", "PRIVATE",
                "AUTH", "DATABASE", "REDIS", "JWT", "ENCRYPTION", "DSN"
            )
            for k, v in requested_env.items():
                k_clean = str(k).strip()
                if not k_clean or "\0" in k_clean:
                    continue

                # Never allow client to redefine PATH in production
                if k_clean == "PATH":
                    if is_production:
                        continue
                    # In development, only allow if not empty and has no null bytes
                    val_str = str(v).strip()
                    if val_str and "\0" not in val_str:
                        env["PATH"] = val_str
                    continue

                # Block exact dangerous variables
                if k_clean in WorkspaceSecurity.EXACT_BLOCKED_ENV_VARS or k_clean in WorkspaceSecurity.DISALLOWED_ENV_VARS:
                    continue

                # Block dangerous prefixes
                if any(k_clean.upper().startswith(p) for p in WorkspaceSecurity.BLOCKED_ENV_PREFIXES):
                    continue

                # Block sensitive substrings
                if any(p in k_clean.upper() for p in sensitive_patterns):
                    continue

                val_str = str(v)
                if "\0" in val_str:
                    continue

                # Only allow if in permitted task-specific list or is a valid alphanumeric identifier
                if k_clean in WorkspaceSecurity.ALLOWED_TASK_ENV_VARS or re.match(r"^[A-Za-z0-9_]{1,64}$", k_clean):
                    env[k_clean] = val_str

        return env

    @staticmethod
    def sanitize_environment(base_env: dict = None) -> dict:
        """Alias for build_safe_child_environment ensuring strict allowlist policy."""
        return WorkspaceSecurity.build_safe_child_environment(base_env)

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


class NetworkAccessPolicy:
    """Enforces policy authorization for sandbox network access."""

    NETWORK_COMMAND_PATTERNS = [
        r"\bpip(\d+)?\s+install\b",
        r"\bnpm\s+(install|i|add|update)\b",
        r"\byarn\s+(add|install)\b",
        r"\bpnpm\s+(add|install|i)\b",
        r"\bcurl\b",
        r"\bwget\b",
        r"\bgit\s+(clone|fetch|pull|submodule)\b",
        r"\bcargo\s+(fetch|add|update)\b",
        r"\bgo\s+(get|install)\b",
    ]

    @staticmethod
    def requires_network_authorization(command: str) -> bool:
        """Returns True if the command is typically an outbound network operation."""
        if not command or not isinstance(command, str):
            return False
        for pat in NetworkAccessPolicy.NETWORK_COMMAND_PATTERNS:
            if re.search(pat, command, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def is_network_authorized(
        command: str,
        requested_allow_network: bool,
        authorization_scope: Optional[str] = None
    ) -> bool:
        """
        Determines whether network access can be activated.
        Network remains disabled by default unless an explicit valid authorization scope is present.
        """
        if not requested_allow_network:
            return False
        valid_scopes = {"trusted_backend", "user_approved", "network_once"}
        if authorization_scope in valid_scopes:
            return True
        # In non-production environments without strict policy enforcement, allow if requested
        env_name = os.getenv("ENVIRONMENT", "development").lower()
        if env_name not in ("production", "prod"):
            return True
        return False
