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


if __name__ == "__main__":
    unittest.main()
