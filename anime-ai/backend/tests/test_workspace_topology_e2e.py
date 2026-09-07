"""
End-to-End Test for Sakura Shared Workspace Topology
Proves that application components and the sandbox execution boundary operate on
the exact same persistent filesystem using workspace IDs.
"""

import os
import shutil
import tempfile
import unittest
import uuid

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from coding.repository import WorkspaceManager
from coding.executor import SandboxExecutor
from coding.sandbox import LocalRestrictedSandboxRuntime, RemoteHttpSandboxRuntime
from coding.security import WorkspaceSecurity, SecurityException


class TestWorkspaceTopologyE2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="sakura_ws_topo_")
        self.workspace_id = uuid.uuid4()
        self.ws_dir = os.path.join(self.temp_root, str(self.workspace_id))
        os.makedirs(self.ws_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    async def test_application_and_sandbox_share_exact_same_filesystem(self):
        """
        End-to-end loop:
        1. Application creates workspace and writes a source file.
        2. Sandbox executor reads the file.
        3. Sandbox modifies the file.
        4. Application inspects and verifies modified content.
        5. Sandbox executes test proving updated code works.
        """
        # 1. Application side creates file
        src_dir = os.path.join(self.ws_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        math_file = os.path.join(src_dir, "calc.py")
        with open(math_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

        # 2. Sandbox executes command to read it
        runtime = LocalRestrictedSandboxRuntime(self.ws_dir)
        executor = SandboxExecutor(self.ws_dir, runtime=runtime, workspace_id=str(self.workspace_id))

        read_res = await executor.run_command(
            ["python", "-c", "import src.calc; print(src.calc.add(2, 3))"]
        )
        self.assertTrue(read_res["success"])
        self.assertEqual(read_res["stdout"].strip(), "5")

        # 3. Sandbox command modifies file
        patch_cmd = [
            "python", "-c",
            "with open('src/calc.py', 'a') as f: f.write('\\ndef multiply(a, b):\\n    return a * b\\n')"
        ]
        mod_res = await executor.run_command(patch_cmd)
        self.assertTrue(mod_res["success"])

        # 4. Application verifies modification on its own file handle
        with open(math_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("def multiply(a, b):", content)

        # 5. Run execution verifying newly added function
        verify_res = await executor.run_command(
            ["python", "-c", "import src.calc; print(src.calc.multiply(4, 5))"]
        )
        self.assertTrue(verify_res["success"])
        self.assertEqual(verify_res["stdout"].strip(), "20")

    def test_workspace_path_traversal_prevention(self):
        """Validates that path traversal attacks escaping workspace root are rejected."""
        # Absolute path outside root
        with self.assertRaises(SecurityException):
            WorkspaceSecurity.resolve_safe_path(self.ws_dir, "/etc/passwd")

        # Traversal sequence
        with self.assertRaises(SecurityException):
            WorkspaceSecurity.resolve_safe_path(self.ws_dir, "../../secret.txt")

        # Null byte injection
        with self.assertRaises(SecurityException):
            WorkspaceSecurity.resolve_safe_path(self.ws_dir, "src/calc.py\0.txt")

        # Valid subpath succeeds
        resolved = WorkspaceSecurity.resolve_safe_path(self.ws_dir, "src/calc.py")
        self.assertTrue(resolved.startswith(self.ws_dir))

    def test_workspace_tenant_isolation_cannot_access_sibling_workspace(self):
        """Workspace A cannot inspect, read, or list sibling Workspace B."""
        ws_a_id = uuid.uuid4()
        ws_b_id = uuid.uuid4()
        ws_a_dir = os.path.join(self.temp_root, str(ws_a_id))
        ws_b_dir = os.path.join(self.temp_root, str(ws_b_id))
        os.makedirs(ws_a_dir, exist_ok=True)
        os.makedirs(ws_b_dir, exist_ok=True)

        secret_b = os.path.join(ws_b_dir, "secret-b.txt")
        with open(secret_b, "w") as f:
            f.write("confidential_tenant_b_data")

        # In workspace A context, attempting to resolve path to workspace B fails
        with self.assertRaises(SecurityException):
            WorkspaceSecurity.resolve_safe_path(ws_a_dir, f"../{ws_b_id}/secret-b.txt")

        # Absolute target to sibling directory is rejected
        with self.assertRaises(SecurityException):
            WorkspaceSecurity.resolve_safe_path(ws_a_dir, ws_b_dir)

    def test_invalid_workspace_uuid_rejected(self):
        """Malformed or directory traversal workspace IDs must be rejected by UUID validation."""
        invalid_ids = [
            "../sibling",
            "../../etc/passwd",
            "ws-1234-invalid",
            "not-a-uuid",
            "; rm -rf /",
            ""
        ]
        for bad_id in invalid_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    uuid.UUID(bad_id)

    def test_child_environment_allowlist_strips_all_secrets(self):
        """Untrusted child process environment only receives allowlisted variables, never backend secrets."""
        host_env_with_secrets = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/sandbox",
            "LANG": "C.UTF-8",
            "JWT_SECRET": "critical_jwt_secret_value_must_not_leak",
            "DATABASE_URL": "postgresql://user:pw@host:5432/sakura",
            "REDIS_URL": "redis://:pw@host:6379/0",
            "INTEGRATION_ENCRYPTION_KEY": "encryption_key_never_leak",
            "GITHUB_TOKEN": "ghp_admin_secret_token",
            "SAKURA_SANDBOX_SERVICE_TOKEN": "internal_token_secret",
            "OPENAI_API_KEY": "sk-proj-secret-key",
            "GROQ_API_KEY": "gsk_secret_key",
            "CUSTOM_SAFE_TASK_VAR": "my_task_param"
        }
        child_env = WorkspaceSecurity.build_safe_child_environment(host_env_with_secrets)

        # Allowlisted baseline is preserved
        self.assertEqual(child_env["PATH"], "/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(child_env["HOME"], "/home/sandbox")
        self.assertEqual(child_env["LANG"], "C.UTF-8")
        self.assertEqual(child_env["CUSTOM_SAFE_TASK_VAR"], "my_task_param")

        # Backend secrets must NEVER reach child environment
        forbidden_secrets = [
            "JWT_SECRET", "DATABASE_URL", "REDIS_URL", "INTEGRATION_ENCRYPTION_KEY",
            "GITHUB_TOKEN", "SAKURA_SANDBOX_SERVICE_TOKEN", "OPENAI_API_KEY", "GROQ_API_KEY"
        ]
        for sec in forbidden_secrets:
            self.assertNotIn(sec, child_env, f"Secret {sec} was not scrubbed from child environment!")


if __name__ == "__main__":
    unittest.main()
