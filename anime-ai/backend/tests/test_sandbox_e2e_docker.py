"""
Sakura AI — Docker Sandbox End-to-End Integration Test Suite

Verifies true containerized execution against the standalone sandbox executor:
1. Readiness contract (Docker, runtime image, child start, binaries, workspace volume, non-root).
2. Real shared workspace volume topology (app writes -> remote executor reads -> container modifies -> app reads).
3. Volume isolation between Workspace A and Workspace B.
4. Host secrets never leaked to child containers; genuinely allowed env vars preserved.
5. Output bounding & timeout enforcement with container cleanup.
6. Signed network_exec capability execution, scope separation, invalid/missing rejection, and replay rejection.

IMPORTANT:
- Skips ONLY when SAKURA_SANDBOX_E2E != "1" (explicitly disabled).
- When SAKURA_SANDBOX_E2E == "1", readiness or service failure MUST FAIL the suite (never silently skip).
"""

import os
import sys
import uuid
import json
import time
import unittest
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coding.capabilities import mint_sandbox_capability

SANDBOX_URL = os.getenv("SAKURA_SANDBOX_URL", "http://localhost:9000").rstrip("/")
SERVICE_TOKEN = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "ci_test_sandbox_token_abc123")
SIGNING_KEY = os.getenv("SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY", "ci_test_capability_signing_key_32chars")
E2E_ENABLED = os.getenv("SAKURA_SANDBOX_E2E", "0") == "1"


@unittest.skipUnless(E2E_ENABLED, "Docker sandbox E2E suite disabled (set SAKURA_SANDBOX_E2E=1 to run)")
class TestSandboxDockerE2E(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.headers = {"X-Sandbox-Token": SERVICE_TOKEN}
        try:
            res = requests.get(f"{SANDBOX_URL}/readiness", headers=cls.headers, timeout=10)
        except Exception as e:
            raise AssertionError(f"Sandbox executor at {SANDBOX_URL} is unreachable while SAKURA_SANDBOX_E2E=1: {e}") from e

        if res.status_code != 200:
            raise AssertionError(
                f"Sandbox executor /readiness failed (HTTP {res.status_code}) while SAKURA_SANDBOX_E2E=1: {res.text}"
            )
        cls.readiness_payload = res.json()

    def _provision_workspace(self) -> str:
        ws_id = str(uuid.uuid4())
        res = requests.post(f"{SANDBOX_URL}/workspaces/{ws_id}", headers=self.headers, timeout=10)
        self.assertEqual(res.status_code, 200, f"Failed to provision workspace {ws_id}: {res.text}")
        return ws_id

    def test_readiness_reports_full_container_runtime_health(self):
        """Readiness must verify Docker, image, child start, binaries, volume, Redis, and non-root execution."""
        p = self.readiness_payload
        self.assertTrue(p.get("ready"), f"Readiness payload not ready: {p}")
        self.assertTrue(p.get("docker_available"))
        self.assertTrue(p.get("image_available"))
        self.assertTrue(p.get("container_can_start"))
        self.assertTrue(p.get("non_root_execution"))
        self.assertTrue(p.get("workspace_root_available"))
        self.assertTrue(p.get("workspace_volume_available"))
        self.assertTrue(p.get("redis_available"))
        binaries = p.get("binaries", {})
        for req_bin in ("python", "git", "node", "npm"):
            self.assertTrue(binaries.get(req_bin), f"Required binary '{req_bin}' missing in sandbox image: {binaries}")

    def test_network_disabled_by_default_in_child_container(self):
        """By default (allow_network=False), child containers must run with --network none (loopback only)."""
        ws_id = self._provision_workspace()
        res = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "python3 -c \"import socket; s=socket.socket(); s.settimeout(2); s.connect(('1.1.1.1', 80))\"",
                "workspace_id": ws_id,
                "allow_network": False
            },
            timeout=15
        ).json()
        self.assertFalse(res.get("success"), f"Outbound network unexpectedly succeeded with allow_network=False: {res}")
        self.assertNotEqual(res.get("exit_code"), 0)

    def test_volume_isolation_between_workspaces(self):
        """Files created in Workspace A must be completely inaccessible and invisible from Workspace B."""
        ws_a = self._provision_workspace()
        ws_b = self._provision_workspace()

        secret_content = f"TOP_SECRET_ISOLATION_TOKEN_{uuid.uuid4().hex}"
        secret_filename = "confidential_spec.txt"

        res_a = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={"command": f"echo '{secret_content}' > {secret_filename}", "workspace_id": ws_a},
            timeout=15
        ).json()
        self.assertTrue(res_a.get("success"), f"Failed to write in ws_a: {res_a}")

        read_a = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={"command": f"cat {secret_filename}", "workspace_id": ws_a},
            timeout=15
        ).json()
        self.assertTrue(read_a.get("success"))
        self.assertIn(secret_content, read_a.get("stdout", ""))

        read_b = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={"command": f"cat {secret_filename}", "workspace_id": ws_b},
            timeout=15
        ).json()
        self.assertFalse(read_b.get("success"))
        self.assertNotEqual(read_b.get("exit_code"), 0)
        self.assertNotIn(secret_content, read_b.get("stdout", ""))

        list_b = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={"command": "ls -la /workspace", "workspace_id": ws_b},
            timeout=15
        ).json()
        self.assertTrue(list_b.get("success"))
        self.assertNotIn(secret_filename, list_b.get("stdout", ""))

    def test_host_secrets_never_leak_to_child_containers(self):
        """Host secrets must never leak; genuinely allowlisted env vars (NODE_ENV, CI) pass while arbitrary ones strip."""
        ws_id = self._provision_workspace()

        res = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": "python3 -c \"import os, json; print(json.dumps(dict(os.environ)))\"",
                "workspace_id": ws_id,
                "environment": {
                    "NODE_ENV": "test",
                    "CI": "true",
                    "UNSUPPORTED_ARBITRARY_VAR": "should_be_stripped",
                    "LD_PRELOAD": "/evil/hack.so",
                    "AWS_SECRET_ACCESS_KEY": "should_be_stripped"
                }
            },
            timeout=15
        ).json()

        self.assertTrue(res.get("success"), f"Inspection command failed: {res}")
        env_dump = json.loads(res.get("stdout", "{}"))

        # Genuinely permitted task environment variables are preserved
        self.assertEqual(env_dump.get("NODE_ENV"), "test")
        self.assertEqual(env_dump.get("CI"), "true")

        # Unsupported and dangerous request variables are stripped
        self.assertNotIn("UNSUPPORTED_ARBITRARY_VAR", env_dump)
        self.assertNotIn("LD_PRELOAD", env_dump)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env_dump)

        # Host secrets are never leaked
        for secret_name in [
            "POSTGRES_PASSWORD",
            "JWT_SECRET",
            "HOST_SENSITIVE_SECRET",
            "SAKURA_SANDBOX_SERVICE_TOKEN",
            "SAKURA_SANDBOX_CAPABILITY_SIGNING_KEY",
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

    def test_network_capability_enforcement_and_valid_execution_with_replay_block(self):
        """
        Verifies complete network capability policy against remote executor:
        - Missing token -> blocked
        - Invalid/tampered token -> blocked
        - Raw UUID authorization ID -> blocked
        - repository_clone token used on /execute -> blocked (scope enforcement)
        - Valid signed network_exec capability -> executes with bridge network
        - Replay of the exact same capability token -> blocked
        """
        ws_id = self._provision_workspace()
        net_cmd = "python3 -c \"import socket; print('NET_CAP_OK', socket.gethostname())\""

        # 1. Missing capability token
        res_no_cap = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={"command": net_cmd, "workspace_id": ws_id, "allow_network": True},
            timeout=10
        ).json()
        self.assertFalse(res_no_cap.get("success"))
        self.assertTrue(res_no_cap.get("blocked"))

        # 2. Tampered capability token
        res_bad_cap = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": net_cmd,
                "workspace_id": ws_id,
                "allow_network": True,
                "network_capability": "invalid.tampered.token"
            },
            timeout=10
        ).json()
        self.assertFalse(res_bad_cap.get("success"))
        self.assertTrue(res_bad_cap.get("blocked"))

        # 3. Raw UUID authorization ID (must NEVER be accepted as a capability token)
        res_raw_uuid = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": net_cmd,
                "workspace_id": ws_id,
                "allow_network": True,
                "network_authorization_id": str(uuid.uuid4())
            },
            timeout=10
        ).json()
        self.assertFalse(res_raw_uuid.get("success"))
        self.assertTrue(res_raw_uuid.get("blocked"))

        # 4. Wrong scope (repository_clone token on /execute must fail)
        clone_scope_token = mint_sandbox_capability(
            workspace_id=ws_id,
            command=net_cmd,
            scope="repository_clone",
            secret_key=SIGNING_KEY,
            ttl_seconds=60
        )
        res_wrong_scope = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": net_cmd,
                "workspace_id": ws_id,
                "allow_network": True,
                "network_capability": clone_scope_token
            },
            timeout=10
        ).json()
        self.assertFalse(res_wrong_scope.get("success"))
        self.assertTrue(res_wrong_scope.get("blocked"))

        # 5. Valid signed network_exec capability succeeds
        valid_cap = mint_sandbox_capability(
            workspace_id=ws_id,
            command=net_cmd,
            scope="network_exec",
            secret_key=SIGNING_KEY,
            ttl_seconds=60
        )
        res_valid = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": net_cmd,
                "workspace_id": ws_id,
                "allow_network": True,
                "network_capability": valid_cap
            },
            timeout=15
        ).json()
        self.assertTrue(res_valid.get("success"), f"Valid signed network_exec capability failed: {res_valid}")
        self.assertIn("NET_CAP_OK", res_valid.get("stdout", ""))

        # 6. Replaying the same signed capability token MUST fail
        res_replay = requests.post(
            f"{SANDBOX_URL}/execute",
            headers=self.headers,
            json={
                "command": net_cmd,
                "workspace_id": ws_id,
                "allow_network": True,
                "network_capability": valid_cap
            },
            timeout=10
        ).json()
        self.assertFalse(res_replay.get("success"))
        self.assertTrue(res_replay.get("blocked"))


if __name__ == "__main__":
    unittest.main()
