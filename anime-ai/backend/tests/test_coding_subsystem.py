import unittest
import unittest.mock
import os
import sys
import tempfile
import shutil
import asyncio

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coding.security import resolve_safe_path, is_command_safe, sanitize_environment, SecurityViolationError
from coding.executor import SandboxExecutor
from coding.sandbox import (
    SandboxManager,
    LocalRestrictedSandboxRuntime,
    DockerSandboxRuntime,
    SandboxUnavailableError
)
from coding.patching import validate_python_syntax, safe_write_file, apply_block_patch
from coding.repository import WorkspaceManager

class TestCodingSubsystem(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_test_ws_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_traversal_prevention(self):
        """Path validator must reject any attempt to break out of workspace root."""
        # Safe relative path works
        safe = resolve_safe_path(self.temp_dir, "src/main.py")
        self.assertTrue(os.path.abspath(safe).startswith(os.path.abspath(self.temp_dir)))

        # Relative traversal escaping workspace root must fail
        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "../../windows/system32/cmd.exe")

        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "../outside.txt")

        # Absolute POSIX paths must fail
        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "/etc/passwd")

        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "/var/log/syslog")

        # Windows absolute paths must fail
        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "C:\\Windows\\System32\\cmd.exe")

        # UNC paths must fail
        with self.assertRaises(SecurityViolationError):
            resolve_safe_path(self.temp_dir, "\\\\server\\share\\evil.py")

    def test_blocked_commands(self):
        """Dangerous shell commands must be rejected by security checker."""
        self.assertTrue(is_command_safe("pytest tests/"))
        self.assertTrue(is_command_safe("python main.py --help"))
        self.assertTrue(is_command_safe("git status"))

        self.assertFalse(is_command_safe("rm -rf /"))
        self.assertFalse(is_command_safe("mkfs.ext4 /dev/sda1"))
        self.assertFalse(is_command_safe(":(){ :|:& };:"))
        self.assertFalse(is_command_safe("dd if=/dev/zero of=/dev/sda"))

    def test_subprocess_executor_execution(self):
        """Sandbox executor runs command in isolated subprocess and captures output using explicit local runtime."""
        local_runtime = LocalRestrictedSandboxRuntime(workspace_root=self.temp_dir, default_timeout_seconds=5)
        executor = SandboxExecutor(workspace_root=self.temp_dir, runtime=local_runtime)
        res = executor.execute([sys.executable, "-c", "print('SAKURA_CODE_OK')"])
        self.assertTrue(res["success"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("SAKURA_CODE_OK", res["stdout"])

    def test_subprocess_timeout(self):
        """Commands exceeding timeout must be terminated cleanly."""
        local_runtime = LocalRestrictedSandboxRuntime(workspace_root=self.temp_dir, default_timeout_seconds=1)
        executor = SandboxExecutor(workspace_root=self.temp_dir, runtime=local_runtime, timeout_seconds=1)
        res = executor.execute([sys.executable, "-c", "import time; time.sleep(5)"])
        self.assertFalse(res["success"])
        self.assertTrue(res.get("timed_out", False))
        self.assertIn("timed out", res["stderr"].lower())

    def test_docker_runtime_execution_if_available(self):
        """If Docker daemon is available, executes container-valid command without host dependencies."""
        if not SandboxManager.is_docker_available():
            self.skipTest("Docker daemon is not available on this host.")

        docker_runtime = DockerSandboxRuntime(workspace_root=self.temp_dir, default_timeout_seconds=30)
        executor = SandboxExecutor(workspace_root=self.temp_dir, runtime=docker_runtime)
        # Use in-container valid python command
        res = executor.execute(["python", "-c", "print('SAKURA_CODE_OK')"])
        self.assertTrue(res["success"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("SAKURA_CODE_OK", res["stdout"])

    def test_production_sandbox_fail_closed(self):
        """In production environment, un-isolated host execution must be refused with SandboxUnavailableError."""
        orig_env = os.environ.get("ENVIRONMENT")
        try:
            os.environ["ENVIRONMENT"] = "production"
            with unittest.mock.patch.object(SandboxManager, "is_docker_available", return_value=False):
                with self.assertRaises(SandboxUnavailableError):
                    SandboxManager.get_runtime(self.temp_dir)
        finally:
            if orig_env is not None:
                os.environ["ENVIRONMENT"] = orig_env
            else:
                os.environ.pop("ENVIRONMENT", None)

    def test_sandbox_executor_runtime_injection(self):
        """SandboxExecutor must respect an explicitly injected runtime."""
        local_rt = LocalRestrictedSandboxRuntime(workspace_root=self.temp_dir)
        executor = SandboxExecutor(workspace_root=self.temp_dir, runtime=local_rt)
        self.assertIs(executor.runtime, local_rt)

    def test_ast_syntax_validation(self):
        """AST validator accepts clean code and flags syntax errors."""
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        self.assertTrue(validate_python_syntax(valid_code))

        invalid_code = "def broken(a, b:\n    return a + b\n"
        self.assertFalse(validate_python_syntax(invalid_code))

    def test_safe_patching_flow(self):
        """Safe file writer writes and block patcher updates content cleanly."""
        target = os.path.join(self.temp_dir, "calc.py")
        initial_content = "def calculate():\n    return 42\n"
        res = safe_write_file(self.temp_dir, "calc.py", initial_content)
        self.assertTrue(res["success"])

        # Patch return value
        patch_res = apply_block_patch(
            self.temp_dir,
            "calc.py",
            target_block="return 42",
            replacement_block="return 100"
        )
        self.assertTrue(patch_res["success"])

        with open(target, "r") as f:
            new_content = f.read()
        self.assertIn("return 100", new_content)

    def test_workspace_manager(self):
        """WorkspaceManager creates and deletes isolated workspaces."""
        wm = WorkspaceManager(workspaces_root=self.temp_dir)
        ws_id, path = asyncio.run(wm.create_workspace("test_repo_ws"))
        self.assertTrue(os.path.exists(path))
        self.assertTrue(wm.delete_workspace(ws_id))
        self.assertFalse(os.path.exists(path))

if __name__ == "__main__":
    unittest.main()
