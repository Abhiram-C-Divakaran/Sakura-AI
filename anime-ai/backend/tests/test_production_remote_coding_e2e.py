"""
Sakura AI — Production-Mode Remote Sandbox Coding Execution Integration Test

Verifies the COMPLETE application Sakura Code workflow through the REAL
remote HTTP Docker sandbox executor (NEVER LocalRestrictedSandboxRuntime):
UNDERSTAND -> EXPLORE -> PLAN -> IMPLEMENT -> RUN -> TEST -> INSPECT FAILURE -> FIX -> RETEST -> REVIEW DIFF -> DELIVER

Verifies:
1. Real user registration & JWT auth via FastAPI API
2. Real coding workspace creation (/api/v1/coding/workspaces) on shared volume
3. Real durable coding job submission (/api/v1/coding/workspaces/{id}/tasks)
4. Real CodingJobWorker claims the job
5. Worker's CodingAgent -> CodingToolchain -> SandboxExecutor ACTUALLY instantiates RemoteHttpSandboxRuntime
6. Docker child container sees ONLY its assigned /workspace (parent /workspaces absent) and ZERO host secrets
7. Buggy file written -> failing test executed inside Docker child -> patch applied -> passing test re-run -> git diff reviewed
8. Backend observes the exact fixed file on shared /workspaces volume
9. Output & monotonic CodingTaskEvents are persisted and replayable via HTTP API
10. Cancellation & stale-worker lease fencing prevent stale writes
11. Production mode strictly refuses local sandbox fallback when remote executor URL is missing

Skips ONLY when SAKURA_SANDBOX_E2E != "1".
"""

import os
import sys
import uuid
import unittest
from typing import Dict, Any, List, Optional
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

E2E_ENABLED = os.getenv("SAKURA_SANDBOX_E2E", "0") == "1"


class _FullLoopCodingTestProvider:
    """
    Deterministic LLM adapter exercising the full CodingAgent engineering loop inside
    the real remote Docker sandbox:
      Turn 1: write_file (buggy calc.py) + write_file (test_calc.py)
      Turn 2: run_tests (proves failing test + verifies /workspaces absent & HOST_SENSITIVE_SECRET scrubbed)
      Turn 3: apply_patch (fixes calc.py)
      Turn 4: run_tests (retests inside Docker child -> exit 0)
      Turn 5: git_diff (reviews diff)
      Turn 6: stop with delivery summary
    """

    model = "sakura-prod-e2e-deterministic-v1"

    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs,
    ) -> Dict[str, Any]:
        tool_msgs = [m for m in (messages or []) if m.get("role") == "tool"]
        step = len(tool_msgs)

        if step == 0:
            return {
                "content": "Implementing calc.py and unit test.",
                "tool_calls": [
                    {
                        "id": "call_1_calc",
                        "name": "write_file",
                        "arguments": {
                            "path": "calc.py",
                            "content": "def add(a, b):\n    return a - b  # intentional bug\n",
                        },
                    },
                    {
                        "id": "call_1_test",
                        "name": "write_file",
                        "arguments": {
                            "path": "test_calc.py",
                            "content": (
                                "import os\n"
                                "from calc import add\n"
                                "assert not os.path.exists('/workspaces'), 'parent /workspaces leaked!'\n"
                                "assert not os.environ.get('HOST_SENSITIVE_SECRET'), 'host secret leaked!'\n"
                                "assert add(2, 3) == 5, f'Expected 5, got {add(2, 3)}'\n"
                                "print('CALC_TESTS_PASSED_IN_DOCKER_CHILD')\n"
                            ),
                        },
                    },
                ],
                "finish_reason": "tool_calls",
            }

        if step == 2:
            return {
                "content": "Running initial test suite in remote Docker sandbox.",
                "tool_calls": [
                    {
                        "id": "call_2_run_fail",
                        "name": "run_tests",
                        "arguments": {"command": "python3 test_calc.py"},
                    }
                ],
                "finish_reason": "tool_calls",
            }

        if step == 3:
            return {
                "content": "Inspecting failure and patching calc.py.",
                "tool_calls": [
                    {
                        "id": "call_3_patch",
                        "name": "apply_patch",
                        "arguments": {
                            "path": "calc.py",
                            "target_content": "return a - b  # intentional bug",
                            "replacement_content": "return a + b",
                        },
                    }
                ],
                "finish_reason": "tool_calls",
            }

        if step == 4:
            return {
                "content": "Re-running tests inside remote Docker sandbox after fix.",
                "tool_calls": [
                    {
                        "id": "call_4_run_pass",
                        "name": "run_tests",
                        "arguments": {"command": "python3 test_calc.py"},
                    }
                ],
                "finish_reason": "tool_calls",
            }

        if step == 5:
            return {
                "content": "Reviewing git diff before delivery.",
                "tool_calls": [
                    {
                        "id": "call_5_diff",
                        "name": "git_diff",
                        "arguments": {},
                    }
                ],
                "finish_reason": "tool_calls",
            }

        return {
            "content": "Fixed add() in calc.py and verified test_calc.py passes inside the isolated Docker child container.",
            "tool_calls": [],
            "finish_reason": "stop",
        }


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
        from database.db import engine
        from coding.job_worker import CodingJobWorker
        from coding.sandbox import RemoteHttpSandboxRuntime
        from coding.executor import SandboxExecutor
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
        cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
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

        # Spy on SandboxExecutor.runtime to PROVE CodingJobWorker's own CodingAgent actually uses RemoteHttpSandboxRuntime
        observed_runtimes = []
        orig_runtime_prop = SandboxExecutor.runtime.fget

        def _spy_runtime(self_exec):
            rt = orig_runtime_prop(self_exec)
            observed_runtimes.append(type(rt).__name__)
            return rt

        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                "SAKURA_SANDBOX_EXECUTOR_URL": sandbox_url,
                "SAKURA_SANDBOX_SERVICE_TOKEN": service_token,
                "SAKURA_WORKSPACE_ROOT": shared_root,
            },
            clear=False,
        ), patch.object(SandboxExecutor, "runtime", property(_spy_runtime)):
            # 2. Real workspace creation (provisions via remote executor on shared /workspaces volume)
            r_ws = client.post(
                "/api/v1/coding/workspaces",
                headers=headers,
                json={"name": "prod-remote-repo", "branch": "main", "clone_existing": False},
            )
            self.assertEqual(r_ws.status_code, 200, r_ws.text)
            ws_id = r_ws.json()["workspace"]["id"]
            ws_dir = os.path.join(shared_root, ws_id)
            self.assertTrue(os.path.isdir(ws_dir), f"Workspace dir missing on shared volume: {ws_dir}")

            # 3. Real durable coding job submission
            r_task = client.post(
                f"/api/v1/coding/workspaces/{ws_id}/tasks",
                headers=headers,
                json={
                    "title": "Fix add() in calc.py and verify in remote Docker sandbox",
                    "objective": "Implement calc.py, run failing test, fix bug, retest, and review diff",
                    "intensity": "high",
                },
            )
            self.assertIn(r_task.status_code, (200, 202), r_task.text)
            task_body = r_task.json()
            task_id = task_body.get("task_id") or task_body.get("taskId") or task_body.get("id")
            self.assertTrue(task_id)

            # 4 & 5. Real separate durable CodingJobWorker process (or in-process fallback if standalone)
            external_worker = os.getenv("SAKURA_EXTERNAL_CODING_WORKER", "0").strip() == "1"
            if external_worker:
                # Poll real PostgreSQL / API while the separate coding-worker container executes the full TDD loop
                import asyncio
                deadline = asyncio.get_running_loop().time() + 45.0
                final_status_body = None
                while asyncio.get_running_loop().time() < deadline:
                    r_poll = client.get(f"/api/v1/coding/tasks/{task_id}", headers=headers)
                    self.assertEqual(r_poll.status_code, 200, r_poll.text)
                    st = str(r_poll.json().get("status", "")).upper()
                    if st in ("COMPLETED_VERIFIED", "COMPLETED_UNVERIFIED", "FAILED", "CANCELLED"):
                        final_status_body = r_poll.json()
                        break
                    await asyncio.sleep(0.4)
                self.assertIsNotNone(final_status_body, "Separate coding-worker container did not complete task within 45s!")
                self.assertEqual(
                    str(final_status_body.get("status", "")).upper(),
                    "COMPLETED_VERIFIED",
                    f"Expected COMPLETED_VERIFIED from separate coding worker, got: {final_status_body}",
                )

                # Backend observes the exact fixed file created & patched by the separate worker on shared /workspaces volume
                check_path = os.path.join(ws_dir, "sakura_fullstack_check.py")
                self.assertTrue(os.path.isfile(check_path), f"Expected file {check_path} on shared volume!")
                with open(check_path, "r", encoding="utf-8") as f:
                    fixed_src = f.read()
                self.assertIn("return a + b", fixed_src)
                self.assertNotIn("intentional bug", fixed_src)
                expected_marker = "SAKURA_REMOTE_DOCKER_TESTS_PASSED"

                # Load persisted CodingJob row from DB for stale-worker fencing assertion below
                from database.db import get_db_context
                from database.models import CodingJob
                with get_db_context() as db_chk:
                    claimed = db_chk.query(CodingJob).filter(CodingJob.task_id == str(task_id)).first()
                    self.assertIsNotNone(claimed)
                    self.assertIsNotNone(claimed.worker_id)
                    self.assertNotEqual(claimed.worker_id, "")
                    claimed_id = claimed.id
            else:
                worker = CodingJobWorker(worker_id=f"prod_remote_worker_{uuid.uuid4().hex[:6]}")
                full_loop_provider = _FullLoopCodingTestProvider()
                worker.llm_router.providers["prod_e2e_loop"] = full_loop_provider
                worker.llm_router.get_ordered_providers = lambda intent="general_chat": [
                    ("prod_e2e_loop", full_loop_provider)
                ]

                claimed = worker.claim_next_job()
                self.assertIsNotNone(claimed, "CodingJobWorker failed to claim durable job!")
                self.assertEqual(str(claimed.task_id), str(task_id))
                claimed_id = claimed.id

                ok = await worker.execute_job(claimed)
                self.assertTrue(ok, "CodingJobWorker.execute_job returned False!")

                # Verify worker ACTUALLY executed through RemoteHttpSandboxRuntime (never LocalRestrictedSandboxRuntime!)
                self.assertIn("RemoteHttpSandboxRuntime", observed_runtimes)
                self.assertNotIn("LocalRestrictedSandboxRuntime", observed_runtimes)

                # 7 & 8. Backend observes the exact fixed file on shared volume
                calc_path = os.path.join(ws_dir, "calc.py")
                self.assertTrue(os.path.isfile(calc_path), f"Expected file {calc_path} on shared volume!")
                with open(calc_path, "r", encoding="utf-8") as f:
                    calc_src = f.read()
                self.assertIn("return a + b", calc_src)
                self.assertNotIn("intentional bug", calc_src)
                expected_marker = "CALC_TESTS_PASSED_IN_DOCKER_CHILD"

            # 9 & 10. Output & monotonic CodingTaskEvents persisted and replayable via HTTP API
            r_status = client.get(f"/api/v1/coding/tasks/{task_id}", headers=headers)
            self.assertEqual(r_status.status_code, 200, r_status.text)
            self.assertEqual(str(r_status.json().get("status", "")).upper(), "COMPLETED_VERIFIED")

            r_events = client.get(f"/api/v1/coding/tasks/{task_id}/events", headers=headers)
            self.assertEqual(r_events.status_code, 200, r_events.text)
            events = r_events.json()
            self.assertGreaterEqual(len(events), 8, f"Expected >=8 persisted CodingTaskEvents for full loop, got {len(events)}")
            seqs = [e["sequenceNumber"] for e in events]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(len(seqs), len(set(seqs)))
            all_stdout = "\n".join(str(e.get("stdoutPreview") or e.get("message") or "") for e in events)
            self.assertIn(expected_marker, all_stdout)

            # 11. Cancellation & stale-worker lease fencing
            r_task2 = client.post(
                f"/api/v1/coding/workspaces/{ws_id}/tasks",
                headers=headers,
                json={"title": "Cancel & fence probe", "objective": "Should be cancelled", "intensity": "low"},
            )
            self.assertIn(r_task2.status_code, (200, 202))
            task2_id = r_task2.json().get("task_id") or r_task2.json().get("taskId") or r_task2.json().get("id")

            r_cancel = client.post(f"/api/v1/coding/tasks/{task2_id}/cancel", headers=headers)
            self.assertEqual(r_cancel.status_code, 200, r_cancel.text)

            stale_worker = CodingJobWorker(worker_id="stale_prod_worker")
            finalized_stale = stale_worker._fenced_finalize(
                job_id=claimed_id,
                task_id=str(task_id),
                attempt_id=uuid.uuid4(),
                new_status="FAILED",
                error="Stale write must be rejected",
            )
            self.assertFalse(finalized_stale, "Stale worker MUST be fenced out!")


if __name__ == "__main__":
    unittest.main()
