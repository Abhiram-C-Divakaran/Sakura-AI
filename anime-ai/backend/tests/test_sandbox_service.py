import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("SAKURA_WORKSPACE_ROOT", os.path.join(tempfile.gettempdir(), "sakura_workspaces"))

from fastapi.testclient import TestClient

from coding.sandbox_service import app
from coding.sandbox import SandboxManager, SandboxUnavailableError, RemoteHttpSandboxRuntime


class TestSandboxService(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_token = "secret_sandbox_service_token_12345"

    def test_sandbox_service_health(self):
        """Health endpoint must return status and runtime fields."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("docker_available", data)
        self.assertIn("runtime", data)

    def test_sandbox_service_auth_missing_token_rejected(self):
        """Requests without token must be rejected with HTTP 401 when token is configured."""
        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.test_token}):
            response = self.client.post("/execute", json={
                "command": "echo hello",
                "workspace_path": "/tmp/test"
            })
            self.assertEqual(response.status_code, 401)
            self.assertIn("Missing required sandbox authentication token", response.json().get("detail", ""))

    def test_sandbox_service_auth_invalid_token_rejected(self):
        """Requests with wrong token must be rejected with HTTP 401."""
        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.test_token}):
            response = self.client.post(
                "/execute",
                json={"command": "echo hello", "workspace_path": "/tmp/test"},
                headers={"X-Sandbox-Token": "wrong_token"}
            )
            self.assertEqual(response.status_code, 401)
            self.assertIn("Invalid sandbox authentication token", response.json().get("detail", ""))

    def test_sandbox_service_bearer_auth_accepted(self):
        """Bearer token in Authorization header must be accepted."""
        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.test_token}):
            with patch("coding.sandbox_service.check_docker_operational", return_value=False):
                response = self.client.post(
                    "/execute",
                    json={"command": "echo test", "workspace_path": "/tmp/test"},
                    headers={"Authorization": f"Bearer {self.test_token}"}
                )
                self.assertEqual(response.status_code, 200)
                # Not 401 Unauthorized

    def test_sandbox_service_blocked_command(self):
        """Destructive shell commands must be intercepted and rejected before container execution."""
        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.test_token}):
            response = self.client.post(
                "/execute",
                json={"command": "rm -rf / --no-preserve-root", "workspace_path": "/tmp/test"},
                headers={"X-Sandbox-Token": self.test_token}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertTrue(data.get("blocked", False))
            self.assertIn("Security Error", data["stderr"])

    def test_sandbox_service_path_traversal_blocked(self):
        """Path traversal outside allowed workspace path must be blocked."""
        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.test_token}):
            response = self.client.post(
                "/execute",
                json={
                    "command": "cat flag.txt",
                    "workspace_path": "/tmp/workspace",
                    "cwd_relative": "../../etc"
                },
                headers={"X-Sandbox-Token": self.test_token}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertTrue(data.get("blocked", False))
            self.assertIn("Working directory error", data["stderr"])

    def test_production_sandbox_fails_closed_when_executor_unavailable(self):
        """In production, SandboxManager must raise SandboxUnavailableError if executor is unreachable."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            with patch.object(SandboxManager, "is_service_available", return_value=False):
                with patch.object(SandboxManager, "is_docker_available", return_value=False):
                    with self.assertRaises(SandboxUnavailableError):
                        SandboxManager.get_runtime("/tmp/test_workspace")

    def test_production_sandbox_does_not_permit_local_restricted(self):
        """Host subprocess runtime cannot be forced in production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            with self.assertRaises(SandboxUnavailableError):
                SandboxManager.get_runtime("/tmp/test_workspace", force_runtime="local_restricted")

    def test_production_sandbox_returns_remote_runtime_when_healthy(self):
        """When the executor service is operational in production, RemoteHttpSandboxRuntime is selected."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            with patch.object(SandboxManager, "is_service_available", return_value=True):
                runtime = SandboxManager.get_runtime("/tmp/test_workspace")
                self.assertIsInstance(runtime, RemoteHttpSandboxRuntime)


if __name__ == "__main__":
    unittest.main()
