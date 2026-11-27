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
            "PYTHONUNBUFFERED": "1",
            "CUSTOM_SAFE_TASK_VAR": "my_task_param"
        }
        child_env = WorkspaceSecurity.build_safe_child_environment(host_env_with_secrets)

        # Allowlisted baseline is preserved
        self.assertEqual(child_env["HOME"], "/home/sandbox")
        self.assertEqual(child_env["LANG"], "C.UTF-8")
        self.assertEqual(child_env["PYTHONUNBUFFERED"], "1")
        self.assertNotIn("CUSTOM_SAFE_TASK_VAR", child_env)

        # Backend secrets must NEVER reach child environment
        forbidden_secrets = [
            "JWT_SECRET", "DATABASE_URL", "REDIS_URL", "INTEGRATION_ENCRYPTION_KEY",
            "GITHUB_TOKEN", "SAKURA_SANDBOX_SERVICE_TOKEN", "OPENAI_API_KEY", "GROQ_API_KEY"
        ]
        for sec in forbidden_secrets:
            self.assertNotIn(sec, child_env, f"Secret {sec} was not scrubbed from child environment!")


@unittest.skipUnless(
    os.getenv("SAKURA_SANDBOX_E2E", "0") == "1",
    "Remote Docker shared-volume topology E2E disabled (set SAKURA_SANDBOX_E2E=1)"
)
class TestRealRemoteWorkspaceTopologyE2E(unittest.IsolatedAsyncioTestCase):
    """
    Proves real shared-volume topology using RemoteHttpSandboxRuntime + Docker child containers:
    Backend/application writes file -> Remote executor reads it -> Docker child modifies it
    -> Backend/application reads the modification, plus cross-workspace isolation.
    Never substitutes LocalRestrictedSandboxRuntime.
    """

    async def test_shared_volume_roundtrip_and_isolation_via_remote_executor(self):
        import httpx

        sandbox_url = os.getenv("SAKURA_SANDBOX_URL", "http://localhost:9000").rstrip("/")
        service_token = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "ci_test_sandbox_token_abc123")
        shared_root = os.getenv("SAKURA_SHARED_WORKSPACE_ROOT") or os.getenv("SAKURA_WORKSPACE_ROOT")
        self.assertTrue(
            shared_root and os.path.isdir(shared_root),
            f"SAKURA_WORKSPACE_ROOT ({shared_root}) must point to the actual shared volume mount for E2E topology test."
        )

        ws_a_id = str(uuid.uuid4())
        ws_b_id = str(uuid.uuid4())
        headers = {"X-Sandbox-Token": service_token}

        async with httpx.AsyncClient(timeout=10.0) as client:
            r_ready = await client.get(f"{sandbox_url}/readiness", headers=headers)
            self.assertEqual(r_ready.status_code, 200, f"Remote executor readiness failed: {r_ready.text}")
            self.assertEqual((await client.post(f"{sandbox_url}/workspaces/{ws_a_id}", headers=headers)).status_code, 200)
            self.assertEqual((await client.post(f"{sandbox_url}/workspaces/{ws_b_id}", headers=headers)).status_code, 200)

        ws_a_dir = os.path.join(shared_root, ws_a_id)
        ws_b_dir = os.path.join(shared_root, ws_b_id)
        os.makedirs(ws_a_dir, exist_ok=True)
        os.makedirs(ws_b_dir, exist_ok=True)

        # 1. Backend/application writes file into shared volume for Workspace A
        app_file = os.path.join(ws_a_dir, "topology_probe.txt")
        with open(app_file, "w", encoding="utf-8") as f:
            f.write("WRITTEN_BY_BACKEND\n")

        # Verify workspace ownership & non-world-writable permission contract on POSIX
        if os.name != "nt":
            import stat
            st_ws = os.stat(ws_a_dir)
            self.assertEqual(st_ws.st_uid, 1001, f"Expected workspace UID 1001, got {st_ws.st_uid}")
            self.assertEqual(st_ws.st_gid, 1001, f"Expected workspace GID 1001, got {st_ws.st_gid}")
            self.assertEqual(
                stat.S_IMODE(st_ws.st_mode) & stat.S_IWOTH,
                0,
                f"Workspace directory must NOT be world-writable (mode={oct(stat.S_IMODE(st_ws.st_mode))})",
            )

        remote_a = RemoteHttpSandboxRuntime(
            workspace_root=ws_a_dir,
            service_url=sandbox_url,
            service_token=service_token,
            workspace_id=ws_a_id,
        )
        remote_b = RemoteHttpSandboxRuntime(
            workspace_root=ws_b_dir,
            service_url=sandbox_url,
            service_token=service_token,
            workspace_id=ws_b_id,
        )

        # 2. Remote executor reads the file inside Docker child container
        read_res = await remote_a.run_command("cat /workspace/topology_probe.txt")
        self.assertTrue(read_res.get("success"), f"Remote read failed: {read_res}")
        self.assertIn("WRITTEN_BY_BACKEND", read_res.get("stdout", ""))

        # 3. Docker child modifies the file
        mod_res = await remote_a.run_command("echo 'MODIFIED_BY_DOCKER_CHILD' >> /workspace/topology_probe.txt")
        self.assertTrue(mod_res.get("success"), f"Remote modify failed: {mod_res}")

        # 4. Backend/application reads the modification from the shared volume
        with open(app_file, "r", encoding="utf-8") as f:
            final_text = f.read()
        self.assertIn("WRITTEN_BY_BACKEND", final_text)
        self.assertIn("MODIFIED_BY_DOCKER_CHILD", final_text)

        # 5. Docker child creates a new file and backend reads it
        create_res = await remote_a.run_command("echo 'NEW_FILE_FROM_CHILD' > /workspace/child_created.txt")
        self.assertTrue(create_res.get("success"), f"Child file creation failed: {create_res}")
        child_file_host = os.path.join(ws_a_dir, "child_created.txt")
        self.assertTrue(os.path.exists(child_file_host), "Child-created file not visible on shared volume")
        with open(child_file_host, "r", encoding="utf-8") as f:
            self.assertIn("NEW_FILE_FROM_CHILD", f.read())

        # 6. Git operations work inside the workspace child container
        git_res = await remote_a.run_command(
            "git init && git config user.name 'Sakura CI' && git config user.email 'ci@sakura.local' "
            "&& git add topology_probe.txt child_created.txt && git commit -m 'init' && git status --short"
        )
        self.assertTrue(git_res.get("success"), f"Git operations failed inside workspace: {git_res}")

        # 7. Cross-workspace isolation: Workspace B child container cannot read Workspace A's file
        iso_res = await remote_b.run_command("cat /workspace/topology_probe.txt")
        self.assertFalse(iso_res.get("success"))
        self.assertNotIn("WRITTEN_BY_BACKEND", iso_res.get("stdout", ""))

        # 8. Child container cannot access the parent /workspaces directory or sibling workspaces
        parent_res = await remote_a.run_command(f"ls /workspaces 2>&1 || true; cat /workspaces/{ws_b_id}/topology_probe.txt 2>&1 || true")
        self.assertNotIn(ws_b_id, parent_res.get("stdout", ""))
        self.assertNotIn("WRITTEN_BY_BACKEND", parent_res.get("stdout", ""))


if __name__ == "__main__":
    unittest.main()
