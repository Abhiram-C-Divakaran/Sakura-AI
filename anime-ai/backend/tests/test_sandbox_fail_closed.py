import os
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from coding.sandbox_service import app as sandbox_app
from coding.security import WorkspaceSecurity, SecurityException


class TestSandboxFailClosed(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(sandbox_app)
        self.valid_token = "test-sandbox-token-12345"
        self.headers = {"X-Sandbox-Token": self.valid_token}

    def test_unresolved_volume_fails_closed_in_production(self):
        """When volume cannot be inspected on host in production, executor must fail closed."""
        ws_id = str(uuid.uuid4())
        # Create temp workspace dir
        ws_dir = os.path.join(os.getcwd(), ws_id)
        os.makedirs(ws_dir, exist_ok=True)

        try:
            with patch.dict(os.environ, {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_SERVICE_TOKEN": self.valid_token,
                "SAKURA_WORKSPACES_VOLUME": "sakura_workspaces",
                "SAKURA_WORKSPACE_ROOT": os.getcwd()
            }):
                with patch("coding.sandbox_service.WORKSPACE_ROOT", os.getcwd()):
                    with patch("coding.sandbox_service.check_docker_operational", return_value=True):
                        with patch("coding.sandbox_service.get_volume_host_mountpoint", return_value=None):
                            res = self.client.post("/execute", headers=self.headers, json={
                                "command": "echo hello",
                                "workspace_id": ws_id
                            })
                        self.assertEqual(res.status_code, 200)
                        data = res.json()
                        self.assertFalse(data["success"])
                        self.assertTrue(data["isolation_unavailable"])
                        self.assertIn("Volume resolution failure", data["stderr"])
        finally:
            import shutil
            shutil.rmtree(ws_dir, ignore_errors=True)

    def test_strict_child_environment_allowlist_and_path_protection(self):
        """Tests that dangerous variables are stripped and PATH cannot be redefined in production."""
        # 1. In production, client passing PATH is ignored
        env_prod = WorkspaceSecurity.build_safe_child_environment(
            requested_env={"PATH": "/malicious/bin", "FOO": "bar"},
            is_production=True
        )
        self.assertNotIn("/malicious/bin", env_prod["PATH"])
        self.assertEqual(env_prod["FOO"], "bar")

        # 2. Blocked variables and prefixes are always stripped
        dangerous_env = {
            "LD_PRELOAD": "/evil/hack.so",
            "LD_LIBRARY_PATH": "/evil/lib",
            "BASH_ENV": "/evil/bash",
            "PYTHONSTARTUP": "/evil/py",
            "AWS_SECRET_ACCESS_KEY": "AKIAEXPLOIT",
            "OPENAI_API_KEY": "sk-secret-leak",
            "ANTHROPIC_API_KEY": "sk-ant-leak",
            "DATABASE_URL": "postgres://leak",
            "REDIS_URL": "redis://leak",
            "SAKURA_SANDBOX_SERVICE_TOKEN": "token-leak",
            "SAFE_VAR": "allowed_value",
            "NODE_ENV": "production"
        }
        sanitized = WorkspaceSecurity.build_safe_child_environment(dangerous_env, is_production=True)

        self.assertNotIn("LD_PRELOAD", sanitized)
        self.assertNotIn("LD_LIBRARY_PATH", sanitized)
        self.assertNotIn("BASH_ENV", sanitized)
        self.assertNotIn("PYTHONSTARTUP", sanitized)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", sanitized)
        self.assertNotIn("OPENAI_API_KEY", sanitized)
        self.assertNotIn("ANTHROPIC_API_KEY", sanitized)
        self.assertNotIn("DATABASE_URL", sanitized)
        self.assertNotIn("REDIS_URL", sanitized)
        self.assertNotIn("SAKURA_SANDBOX_SERVICE_TOKEN", sanitized)
        self.assertEqual(sanitized["SAFE_VAR"], "allowed_value")
        self.assertEqual(sanitized["CI"], "true")


if __name__ == "__main__":
    unittest.main()
