import os
import sys
import uuid
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"

from coding.sandbox_service import app, MAX_OUTPUT_BYTES
from coding.sandbox import SandboxManager, SandboxUnavailableError, DockerSandboxRuntime, RemoteHttpSandboxRuntime


class TestSandboxOutputLimitsAndCleanup(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = "sandbox_test_token_abcdef123456"

    def test_production_fails_closed_even_if_local_docker_exists(self):
        """In production, remote sandbox unavailable must FAIL CLOSED even if local Docker is present."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            # Simulate local docker is present and operational, but remote executor is down
            with patch.object(SandboxManager, "is_service_available", return_value=False):
                with patch.object(SandboxManager, "is_docker_available", return_value=True):
                    with self.assertRaises(SandboxUnavailableError):
                        SandboxManager.get_runtime("/workspaces/test_ws", workspace_id="ws-123")

    def test_unique_container_naming_and_cleanup_on_timeout(self):
        """Every execution must assign a unique sakura-exec-<uuid> name and clean it up on timeout."""
        called_container_names = []
        rm_container_names = []

        async def fake_create_subprocess(*cmd, **kwargs):
            # cmd[0] is list of docker command args
            cmd_args = cmd[0] if isinstance(cmd[0], list) else list(cmd)
            # Find --name argument
            if "--name" in cmd_args:
                idx = cmd_args.index("--name")
                cname = cmd_args[idx + 1]
                called_container_names.append(cname)

            if "rm" in cmd_args:
                cname = cmd_args[-1]
                rm_container_names.append(cname)
                # Mock fast rm
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.wait.return_value = 0
                return mock_proc

            # Simulate timeout on the execution container
            mock_proc = AsyncMock()
            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.read = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_proc.stderr = AsyncMock()
            mock_proc.stderr.read = AsyncMock(return_value=b"")
            mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        def fake_subprocess_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rm" in cmd:
                rm_container_names.append(cmd[-1])
            m = MagicMock()
            m.returncode = 0
            return m

        async def fake_wait_for(coro, timeout=None):
            coro.close()
            raise asyncio.TimeoutError()

        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.token}):
            with patch("coding.sandbox_service.check_docker_operational", return_value=True):
                with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    with patch("subprocess.run", side_effect=fake_subprocess_run):
                        with patch("asyncio.wait_for", side_effect=fake_wait_for):
                            resp = self.client.post(
                                "/execute",
                                json={"command": "python -c 'while True: pass'", "workspace_path": "/tmp", "timeout": 1},
                                headers={"X-Sandbox-Token": self.token}
                            )
                            self.assertEqual(resp.status_code, 200)
                            data = resp.json()
                            self.assertFalse(data["success"])
                            self.assertIn("Execution timed out", data["stderr"])

                            # Verify container name format
                            self.assertTrue(len(called_container_names) >= 1)
                            cname = called_container_names[0]
                            self.assertTrue(cname.startswith("sakura-exec-"))
                            # Verify rm -f was invoked for this container
                            self.assertIn(cname, rm_container_names)

    def test_bounded_streaming_output_truncation(self):
        """Executor must incrementally consume process output and enforce MAX_OUTPUT_BYTES limit."""
        # Verify MAX_OUTPUT_BYTES is 512KB
        self.assertEqual(MAX_OUTPUT_BYTES, 512 * 1024)

        # Simulate a process generating 2MB of output (4x the limit)
        chunk_size = 64 * 1024
        total_chunks = 32  # 32 * 64KB = 2048KB = 2MB
        chunks_sent = [0]

        async def fake_create_subprocess(*cmd, **kwargs):
            cmd_args = cmd[0] if isinstance(cmd[0], list) else list(cmd)
            if "rm" in cmd_args:
                mock_rm = AsyncMock()
                mock_rm.communicate.return_value = (b"", b"")
                mock_rm.wait.return_value = 0
                return mock_rm

            mock_proc = AsyncMock()
            mock_proc.returncode = 0

            async def fake_stdout_read(n):
                if chunks_sent[0] < total_chunks:
                    chunks_sent[0] += 1
                    return b"A" * chunk_size
                return b""

            mock_proc.stdout = AsyncMock()
            mock_proc.stdout.read = fake_stdout_read
            mock_proc.stderr = AsyncMock()
            mock_proc.stderr.read = AsyncMock(return_value=b"")
            mock_proc.wait = AsyncMock(return_value=0)
            mock_proc.kill = MagicMock()
            return mock_proc

        with patch.dict(os.environ, {"SAKURA_SANDBOX_SERVICE_TOKEN": self.token}):
            with patch("coding.sandbox_service.check_docker_operational", return_value=True):
                with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    resp = self.client.post(
                        "/execute",
                        json={"command": "cat /dev/urandom", "workspace_path": "/tmp"},
                        headers={"X-Sandbox-Token": self.token}
                    )
                    self.assertEqual(resp.status_code, 200)
                    data = resp.json()
                    self.assertTrue(data.get("output_truncated", False), "Response must flag output_truncated=True")
                    self.assertLessEqual(len(data["stdout"]), MAX_OUTPUT_BYTES + 1000)
                    self.assertIn("[OUTPUT TRUNCATED: Exceeded maximum allowed buffer limit", data["stdout"])


if __name__ == "__main__":
    unittest.main()
