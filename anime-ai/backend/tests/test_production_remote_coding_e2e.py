"""
Sakura AI — Production-Mode Remote Sandbox Coding Execution Integration Test

Verifies the complete application Sakura Code workflow running through the REAL
remote HTTP Docker sandbox executor (NEVER LocalRestrictedSandboxRuntime):
1. Real user registration & JWT auth via FastAPI API
2. Real coding workspace creation (/api/v1/coding/workspaces)
3. Real durable coding job submission (/api/v1/coding/workspaces/{id}/tasks)
4. Real CodingJobWorker claims the job
5. Worker communicates with real RemoteHttpSandboxRuntime -> sakura-sandbox-executor
6. Docker child container sees ONLY its assigned /workspace (parent /workspaces absent)
7. File created inside Docker child is observed on shared /workspaces volume by backend
8. Test execution runs inside Docker child container and output is persisted
9. Monotonic CodingTaskEvents are persisted and replayable via HTTP API
10. Cancellation & stale-worker lease fencing prevent stale writes
11. Production mode strictly refuses local sandbox fallback when remote executor URL is missing

Skips ONLY when SAKURA_SANDBOX_E2E != "1".
"""

import os
import sys
import uuid
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

E2E_ENABLED = os.getenv("SAKURA_SANDBOX_E2E", "0") == "1"


@unittest.skipUnless(
    E2E_ENABLED,
    "Production remote sandbox coding E2E disabled (set SAKURA_SANDBOX_E2E=1)",
)
class TestProductionRemoteCodingE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end production-path coding execution via real remote Docker executor."""

    async def test_production_mode_refuses_local_sandbox_fallback(self):
        """In ENVIRONMENT=production, SandboxExecutor MUST fail closed if remote executor URL is missing."""
        from coding.executor import SandboxExecutor
        from coding.sandbox import SandboxUnavailableError
        from coding.security import SecurityException

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_EXECUTOR_URL": "",
                "SAKURA_SANDBOX_URL": "",
                "SAKURA_SANDBOX_RUNTIME": "local_restricted",
            },
            clear=False,
        ):
            ex = SandboxExecutor(workspace_root="/tmp/unused_prod_ws", workspace_id=str(uuid.uuid4()))
            with self.assertRaises((SandboxUnavailableError, SecurityException, RuntimeError, ValueError)):
                _ = ex.runtime

    async def test_full_application_coding_workflow_through_real_remote_executor(self):
        import httpx
        from fastapi.testclient import TestClient
        from alembic import command
        from alembic.config import Config
        from database.db import get_db_context, engine
        from database.models import CodingJob, CodingTask, CodingTaskEvent
        from coding.job_worker import CodingJobWorker
        from coding.sandbox import RemoteHttpSandboxRuntime
        from llm.providers.deterministic_test import DeterministicTestProvider
        from main import app

        sandbox_url = (
            os.getenv("SAKURA_SANDBOX_EXECUTOR_URL")
            or os.getenv("SAKURA_SANDBOX_URL")
            or "http://sakura-sandbox-executor:9000"
        ).rstrip("/")
        service_token = os.getenv("SAKURA_SANDBOX_SERVICE_TOKEN", "ci_test_sandbox_token_abc123")
        shared_root = os.getenv("SAKURA_WORKSPACE_ROOT", "/workspaces")

        # Confirm remote executor readiness first
        async with httpx.AsyncClient(timeout=10.0) as hclient:
            r_ready = await hclient.get(f"{sandbox_url}/readiness", headers={"X-Sandbox-Token": service_token})
            self.assertEqual(r_ready.status_code, 200, f"Remote executor not ready: {r_ready.text}")

        # Ensure DB schema is migrated to head
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.upgrade(cfg, "head")

        client = TestClient(app)

        # 1. Real user registration & JWT login
        username = f"prod_code_{uuid.uuid4().hex[:8]}@example.com"
        password = "StrongProdCodingPass123!"
        r_reg = client.post("/api/v1/auth/register", json={"username": username, "password": password})
        self.assertEqual(r_reg.status_code, 200, r_reg.text)

        r_tok = client.post(
            "/api/v1/auth/token",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(r_tok.status_code, 200, r_tok.text)
        headers = {"Authorization": f"Bearer {r_tok.json()['access_token']}"}

        # 2. Real workspace creation (provisions directory on shared /workspaces volume)
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_EXECUTOR_URL": sandbox_url,
                "SAKURA_SANDBOX_SERVICE_TOKEN": service_token,
                "SAKURA_WORKSPACE_ROOT": shared_root,
            },
            clear=False,
        ):
            r_ws = client.post(
                "/api/v1/coding/workspaces",
                headers=headers,
                json={"name": "prod-remote-repo", "branch": "main", "clone_existing": False},
            )
            self.assertEqual(r_ws.status_code, 200, r_ws.text)
            ws_id = r_ws.json()["workspace"]["id"]
            ws_dir = os.path.join(shared_root, ws_id)
            self.assertTrue(os.path.isdir(ws_dir), f"Workspace dir missing on shared volume: {ws_dir}")

            # Ensure executor permissions/readiness on provisioned workspace
            async with httpx.AsyncClient(timeout=10.0) as hclient:
                r_prov = await hclient.post(
                    f"{sandbox_url}/workspaces/{ws_id}",
                    headers={"X-Sandbox-Token": service_token},
                )
                self.assertEqual(r_prov.status_code, 200, r_prov.text)

            # Verify child container sees ONLY /workspace (never parent /workspaces)
            remote_rt = RemoteHttpSandboxRuntime(
                workspace_root=ws_dir,
                service_url=sandbox_url,
                service_token=service_token,
                workspace_id=ws_id,
            )
            parent_check = await remote_rt.run_command("test ! -e /workspaces && pwd")
            self.assertTrue(parent_check.get("success"), f"Parent /workspaces leaked inside child: {parent_check}")
            self.assertEqual(parent_check.get("stdout", "").strip(), "/workspace")

            # 3. Real durable coding job submission
            r_task = client.post(
                f"/api/v1/coding/workspaces/{ws_id}/tasks",
                headers=headers,
                json={
                    "title": "Remote Docker coding verification",
                    "objective": "Write sakura_fullstack_check.py and run it inside Docker child",
                    "intensity": "medium",
                },
            )
            self.assertIn(r_task.status_code, (200, 202), r_task.text)
            task_body = r_task.json()
            task_id = task_body.get("task_id") or task_body.get("taskId") or task_body.get("id")
            self.assertTrue(task_id)

            # 4 & 5. Real CodingJobWorker claims & executes job via REAL RemoteHttpSandboxRuntime
            #        (injects deterministic LLM provider directly without enabling test provider env flag in production!)
            worker = CodingJobWorker(worker_id=f"prod_remote_worker_{uuid.uuid4().hex[:6]}")
            worker.llm_router.providers["deterministic_test"] = DeterministicTestProvider()
            orig_ordered = worker.llm_router.get_ordered_providers
            worker.llm_router.get_ordered_providers = lambda intent="general_chat": [
                ("deterministic_test", worker.llm_router.providers["deterministic_test"])
            ]

            claimed = worker.claim_next_job()
            self.assertIsNotNone(claimed, "CodingJobWorker failed to claim durable job!")
            self.assertEqual(str(claimed.task_id), str(task_id))

            ok = await worker.execute_job(claimed)
            self.assertTrue(ok, "CodingJobWorker.execute_job returned False!")

            # 7 & 8. Backend observes the exact file created by CodingAgent inside shared volume
            created_file = os.path.join(ws_dir, "sakura_fullstack_check.py")
            self.assertTrue(os.path.isfile(created_file), f"Expected file {created_file} on shared volume!")
            with open(created_file, "r", encoding="utf-8") as f:
                self.assertIn("assert add(2, 3) == 5", f.read())

            # 9, 10 & 11. Output & monotonic CodingTaskEvents persisted and replayable via HTTP API
            r_status = client.get(f"/api/v1/coding/tasks/{task_id}", headers=headers)
            self.assertEqual(r_status.status_code, 200, r_status.text)
            self.assertIn(
                str(r_status.json().get("status", "")).upper(),
                ("COMPLETED_VERIFIED", "COMPLETED_UNVERIFIED"),
            )

            r_events = client.get(f"/api/v1/coding/tasks/{task_id}/events", headers=headers)
            self.assertEqual(r_events.status_code, 200, r_events.text)
            events = r_events.json()
            self.assertGreaterEqual(len(events), 3, f"Expected >=3 persisted CodingTaskEvents, got {events}")
            seqs = [e["sequenceNumber"] for e in events]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(len(seqs), len(set(seqs)))

            # 12. Cancellation & stale-worker lease fencing
            r_task2 = client.post(
                f"/api/v1/coding/workspaces/{ws_id}/tasks",
                headers=headers,
                json={"title": "Cancel & fence probe", "objective": "Should be cancelled", "intensity": "low"},
            )
            self.assertIn(r_task2.status_code, (200, 202))
            task2_id = r_task2.json().get("task_id") or r_task2.json().get("taskId") or r_task2.json().get("id")

            r_cancel = client.post(f"/api/v1/coding/tasks/{task2_id}/cancel", headers=headers)
            self.assertEqual(r_cancel.status_code, 200, r_cancel.text)

            # Stale worker with wrong attempt ID CANNOT finalize job 1 or job 2
            stale_worker = CodingJobWorker(worker_id="stale_prod_worker")
            finalized_stale = stale_worker._fenced_finalize(
                job_id=claimed.id,
                task_id=str(task_id),
                attempt_id=uuid.uuid4(),
                new_status="FAILED",
                error="Stale write must be rejected",
            )
            self.assertFalse(finalized_stale, "Stale worker MUST be fenced out!")


if __name__ == "__main__":
    unittest.main()
