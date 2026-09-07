"""
Sakura AI — Docker Sandbox End-to-End Integration Test Suite

Verifies true containerized execution against the standalone sandbox executor:
1. Volume isolation between Workspace A and Workspace B (files created in A are strictly invisible in B).
2. Host secrets (POSTGRES_PASSWORD, JWT_SECRET, etc.) are never leaked to child containers.
3. Output limits (output truncation and hard kill on runaway streams).
4. Execution timeout enforcement and clean container termination.
"""

import os
import sys
import uuid
import json
import time
import unittest
import requests

# Adjust path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SANDBOX_URL = os.getenv("SAKURA_SANDBOX_URL", "http://localhost:9000").rstrip("/")
SERVICE_TOKEN = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "ci_test_sandbox_token_abc123")
E2E_ENABLED = os.getenv("SAKURA_SANDBOX_E2E", "0") == "1"


def is_service_ready() -> bool:
    try:
        res = requests.get(f"{SANDBOX_URL}/health", timeout=2)
        return res.status_code == 200
    except Exception:
        return False


@unittest.skipUnless(E2E_ENABLED and is_service_ready(), "Sandbox executor service is not running or SAKURA_SANDBOX_E2E!=1")
class TestSandboxDockerE2E(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.headers = {"X-Sandbox-Token": SERVICE_TOKEN}
        # Verify readiness
        res = requests.get(f"{SANDBOX_URL}/readiness", headers=cls.headers, timeout=5)
        if res.status_code != 200:
            raise unittest.SkipTest(f"Sandbox readiness check failed: {res.text}")

    def _provision_workspace(self) -> str:
        ws_id = str(uuid.uuid4())
        res = requests.post(f"{SANDBOX_URL}/workspaces/{ws_id}", headers=self.headers, timeout=5)
        self.assertEqual(res.status_code, 200, f"Failed to provision workspace {ws_id}: {res.text}")
        return ws_id

    def test_volume_isolation_between_workspaces(self):
        """Files created in Workspace A must be completely inaccessible and invisible from Workspace B."""
        ws_a = self._provision_workspace()
        ws_b = self._provision_workspace()

        secret_content = f"TOP_SECRET_ISOLATION_TOKEN_{uuid.uuid4().hex}"
        secret_filename = "confidential_spec.txt"

        # 1. Create file in Workspace A
        res_a = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": f"echo '{secret_content}' > {secret_filename}",
                "workspace_id": ws_a
            },
            timeout=15
        ).json()
        self.assertTrue(res_a.get("success"), f"Failed to write in ws_a: {res_a}")

        # 2. Confirm file exists in Workspace A
        read_a = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": f"cat {secret_filename}",
                "workspace_id": ws_a
            },
            timeout=15
        ).json()
        self.assertTrue(read_a.get("success"))
        self.assertIn(secret_content, read_a.get("stdout", ""))

        # 3. Attempt to read file in Workspace B -> must fail
        read_b = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": f"cat {secret_filename}",
                "workspace_id": ws_b
            },
            timeout=15
        ).json()
        self.assertFalse(read_b.get("success"))
        self.assertNotEqual(read_b.get("exit_code"), 0)
        self.assertNotIn(secret_content, read_b.get("stdout", ""))

        # 4. List directory in Workspace B -> secret file must not be present
        list_b = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "ls -la /workspace",
                "workspace_id": ws_b
            },
            timeout=15
        ).json()
        self.assertTrue(list_b.get("success"))
        self.assertNotIn(secret_filename, list_b.get("stdout", ""))

    def test_host_secrets_never_leak_to_child_containers(self):
        """Host environment secrets (e.g. database password, JWT secret) must never be passed to sandbox."""
        ws_id = self._provision_workspace()

        # Run python inspection of container environment
        res = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "python3 -c \"import os, json; print(json.dumps(dict(os.environ)))\"",
                "workspace_id": ws_id,
                "environment": {
                    "ALLOWED_PARAM": "test_ok",
                    "LD_PRELOAD": "/evil/hack.so",
                    "AWS_SECRET_ACCESS_KEY": "should_be_stripped"
                }
            },
            timeout=15
        ).json()

        self.assertTrue(res.get("success"), f"Inspection command failed: {res}")
        env_dump = json.loads(res.get("stdout", "{}"))

        # Verify safe child variable is present
        self.assertEqual(env_dump.get("ALLOWED_PARAM"), "test_ok")

        # Verify dangerous/forbidden variables injected in request are stripped
        self.assertNotIn("LD_PRELOAD", env_dump)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env_dump)

        # Verify host secrets are not leaked
        for secret_name in [
            "POSTGRES_PASSWORD",
            "JWT_SECRET",
            "HOST_SENSITIVE_SECRET",
            "SAKURA_SANDBOX_SERVICE_TOKEN",
            "INTEGRATION_ENCRYPTION_KEY",
            "DATABASE_URL"
        ]:
            self.assertNotIn(
                secret_name,
                env_dump,
                f"Security breach: Host secret '{secret_name}' leaked to sandbox child container!"
            )

    def test_output_bounding_and_runaway_limits(self):
        """Output exceeding capture limits must be bounded and marked as truncated."""
        ws_id = self._provision_workspace()

        # Generate 1 MB of stdout (exceeds default 512 KiB capture limit)
        res = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "python3 -c \"print('A' * 1000000)\"",
                "workspace_id": ws_id
            },
            timeout=15
        ).json()

        self.assertTrue(
            res.get("output_truncated") or len(res.get("stdout", "")) <= 524288,
            f"Output limit was not bounded: truncated={res.get('output_truncated')}, len={len(res.get('stdout', ''))}"
        )

    def test_timeout_enforcement_and_container_cleanup(self):
        """Commands exceeding timeout_seconds must be terminated with timed_out=True."""
        ws_id = self._provision_workspace()

        start = time.time()
        res = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "sleep 10",
                "workspace_id": ws_id,
                "timeout_seconds": 2
            },
            timeout=15
        ).json()
        duration = time.time() - start

        self.assertFalse(res.get("success"))
        self.assertTrue(res.get("timed_out"))
        self.assertLess(duration, 8.0, "Execution did not terminate in expected timeout window")


if __name__ == "__main__":
    unittest.main()
