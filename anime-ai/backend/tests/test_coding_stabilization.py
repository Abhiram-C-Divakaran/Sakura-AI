"""
Regression tests for Phase 2 (Unified Coding Execution, Lease Fencing, CodingTask Persistence,
Cancellation, Monotonic Event Sequences, Redaction) and Phase 3 (Coding Task Authorization & IDOR).
"""

import os
import sys
import uuid
import shutil
import asyncio
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch, AsyncMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import (
    User,
    Conversation,
    RepositoryWorkspace,
    CodingTask,
    CodingJob,
    CodingTaskEvent,
    TaskOutcome,
    utc_now,
)
from auth.manager import AuthManager
from coding.job_worker import (
    CodingJobWorker,
    create_and_enqueue_coding_job,
    append_coding_task_event,
    MAX_CODING_JOB_RETRIES,
)


class _StubProvider:
    """Deterministic stub provider for testing CodingAgent & CodingJobWorker lifecycles."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0

    async def tool_turn(self, messages, tools, temperature=0.2, max_tokens=2000):
        idx = self.calls
        self.calls += 1
        item = self._turns[min(idx, len(self._turns) - 1)]
        if callable(item):
            res = item(idx)
            if asyncio.iscoroutine(res):
                return await res
            return res
        return item


class _StubRouter:
    def __init__(self, provider):
        self.provider = provider

    def get_provider(self, intent="repository_coding"):
        return "stub", self.provider


class TestCodingStabilization(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_coding_stab_")

        with get_db_context() as db:
            self.user_a_id = uuid.uuid4()
            self.user_b_id = uuid.uuid4()
            self.user_a = User(
                id=self.user_a_id,
                username=f"coder_a_{self.user_a_id.hex[:6]}",
                hashed_password=AuthManager.hash_password("Password123!"),
            )
            self.user_b = User(
                id=self.user_b_id,
                username=f"coder_b_{self.user_b_id.hex[:6]}",
                hashed_password=AuthManager.hash_password("Password123!"),
            )
            db.add_all([self.user_a, self.user_b])

            self.ws_a1_id = uuid.uuid4()
            self.ws_a2_id = uuid.uuid4()
            self.ws_b1_id = uuid.uuid4()
            for ws_id in (self.ws_a1_id, self.ws_a2_id, self.ws_b1_id):
                os.makedirs(os.path.join(self.temp_dir, str(ws_id)), exist_ok=True)

            db.add_all([
                RepositoryWorkspace(
                    id=self.ws_a1_id,
                    user_id=self.user_a_id,
                    name="ws-a1",
                    workspace_path=os.path.join(self.temp_dir, str(self.ws_a1_id)),
                    status="READY",
                ),
                RepositoryWorkspace(
                    id=self.ws_a2_id,
                    user_id=self.user_a_id,
                    name="ws-a2",
                    workspace_path=os.path.join(self.temp_dir, str(self.ws_a2_id)),
                    status="READY",
                ),
                RepositoryWorkspace(
                    id=self.ws_b1_id,
                    user_id=self.user_b_id,
                    name="ws-b1",
                    workspace_path=os.path.join(self.temp_dir, str(self.ws_b1_id)),
                    status="READY",
                ),
            ])

            self.conv_a_id = uuid.uuid4()
            db.add(Conversation(id=self.conv_a_id, user_id=self.user_a_id, character_id="sakura", title="Test"))
            db.commit()

            self.token_a = AuthManager.create_access_token({"sub": self.user_a.username})
            self.token_b = AuthManager.create_access_token({"sub": self.user_b.username})

        self.headers_a = {"Authorization": f"Bearer {self.token_a}"}
        self.headers_b = {"Authorization": f"Bearer {self.token_b}"}

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_coding_api_enqueues_durably_without_inline_worker_and_is_idempotent(self):
        """POST /coding/workspaces/{id}/tasks must NOT call execute_job inline and must honor Idempotency-Key."""
        with patch.object(CodingJobWorker, "execute_job", new_callable=AsyncMock) as mock_exec:
            r1 = self.client.post(
                f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks",
                headers={**self.headers_a, "Idempotency-Key": "idem-key-001"},
                json={"title": "Fix bug", "objective": "Explain architecture", "stream": False},
            )
            self.assertEqual(r1.status_code, 200, r1.text)
            body1 = r1.json()
            self.assertEqual(body1["status"], "QUEUED")
            self.assertFalse(body1["idempotentReplay"])
            mock_exec.assert_not_called()

            # Retry with same Idempotency-Key returns the exact same job without duplicate creation
            r2 = self.client.post(
                f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks",
                headers={**self.headers_a, "Idempotency-Key": "idem-key-001"},
                json={"title": "Fix bug", "objective": "Explain architecture", "stream": False},
            )
            self.assertEqual(r2.status_code, 200)
            body2 = r2.json()
            self.assertEqual(body2["jobId"], body1["jobId"])
            self.assertEqual(body2["taskId"], body1["taskId"])
            self.assertTrue(body2["idempotentReplay"])
            mock_exec.assert_not_called()

        with get_db_context() as db:
            self.assertEqual(db.query(CodingJob).count(), 1)
            self.assertEqual(db.query(CodingTask).count(), 1)

    def test_chat_stream_enqueues_durable_job_never_executes_agent_directly(self):
        """POST /api/v1/chat/stream coding request must persist CodingTask+CodingJob and never run CodingAgent inline."""
        with patch("coding.agent.CodingAgent.run_task_stream") as mock_direct_stream:
            # Make stream exit quickly by marking job terminal right after creation via a short patch
            def _fast_enqueue(*args, **kwargs):
                task, job, created = create_and_enqueue_coding_job(*args, **kwargs)
                with get_db_context() as db_ctx:
                    j = db_ctx.query(CodingJob).filter(CodingJob.id == job.id).first()
                    j.status = "COMPLETED_VERIFIED"
                    db_ctx.commit()
                append_coding_task_event(
                    task_id=str(task.id),
                    job_id=job.id,
                    phase="COMPLETED_VERIFIED",
                    event_type="status",
                    message="Worker finished cleanly.",
                )
                return task, job, created

            with patch("coding.job_worker.create_and_enqueue_coding_job", side_effect=_fast_enqueue):
                resp = self.client.post(
                    "/api/v1/chat/stream",
                    headers=self.headers_a,
                    json={
                        "conversation_id": str(self.conv_a_id),
                        "message": "/code explain repository layout",
                        "active_workspace_id": str(self.ws_a1_id),
                    },
                )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Queued durable coding task", resp.text)
            self.assertIn("Worker finished cleanly.", resp.text)
            mock_direct_stream.assert_not_called()

    async def test_execute_job_refuses_unclaimed_or_expired_or_wrong_worker(self):
        """Worker must refuse execute_job unless RUNNING, worker_id matches, attempt matches, and lease is valid."""
        worker_a = CodingJobWorker(worker_id="worker_A")
        with get_db_context() as db:
            user = db.query(User).filter(User.id == self.user_a_id).first()
            ws = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == self.ws_a1_id).first()
            _task, job, _ = create_and_enqueue_coding_job(db, user, ws, "Unclaimed", "Explain code")
            job_id = job.id

        # 1. Unclaimed QUEUED job -> refused
        with get_db_context() as db:
            q_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            db.expunge(q_job)
        self.assertFalse(await worker_a.execute_job(q_job))

        # 2. Claimed by Worker B -> Worker A refuses
        worker_b = CodingJobWorker(worker_id="worker_B")
        claimed_by_b = worker_b.claim_next_job()
        self.assertIsNotNone(claimed_by_b)
        self.assertFalse(await worker_a.execute_job(claimed_by_b))

        # 3. Expired lease -> Worker B refuses
        with get_db_context() as db:
            j = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            j.lease_expires_at = utc_now() - timedelta(seconds=30)
            db.commit()
        self.assertFalse(await worker_b.execute_job(claimed_by_b))

    async def test_coding_task_persistence_and_stale_worker_fencing_and_monotonic_seq(self):
        """
        Proves:
        1. CodingTask status, files_modified, verification_summary, completed_at are persisted.
        2. Stale Worker A cannot overwrite Worker B's attempt or append events.
        3. Retry events continue monotonically with zero duplicate sequence numbers.
        4. Sensitive tokens in tool args and logs are redacted.
        """
        with get_db_context() as db:
            user = db.query(User).filter(User.id == self.user_a_id).first()
            ws = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == self.ws_a1_id).first()
            task, job, _ = create_and_enqueue_coding_job(db, user, ws, "Explain", "Explain the workspace")
            task_id = task.id
            job_id = job.id

        # Worker A claims attempt 1 and records 2 events (seq 1, 2)
        worker_a = CodingJobWorker(worker_id="worker_A", heartbeat_interval=0.1)
        job_attempt_1 = worker_a.claim_next_job()
        self.assertIsNotNone(job_attempt_1)
        e1 = worker_a.record_event(
            task_id=str(task_id),
            job_id=job_id,
            phase="EXPLORING",
            event_type="tool_start",
            args_summary='{"api_key": "sk-secret123456789012345", "cmd": "Bearer mysecretjwt"}',
            expected_attempt_id=job_attempt_1.execution_attempt_id,
        )
        self.assertEqual(e1.sequence_number, 1)
        self.assertNotIn("sk-secret123456789012345", e1.arguments_summary)
        self.assertNotIn("mysecretjwt", e1.arguments_summary)

        # Simulate Worker A lease expiration and atomic recovery + Worker B claim (attempt 2)
        with get_db_context() as db:
            j = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            j.lease_expires_at = utc_now() - timedelta(seconds=5)
            db.commit()

        worker_b = CodingJobWorker(worker_id="worker_B", heartbeat_interval=0.1)
        recovered = worker_b.recover_stale_jobs()
        self.assertEqual(recovered, 1)

        job_attempt_2 = worker_b.claim_next_job()
        self.assertIsNotNone(job_attempt_2)
        self.assertNotEqual(job_attempt_1.execution_attempt_id, job_attempt_2.execution_attempt_id)

        # Stale Worker A tries to finalize or emit event -> MUST BE REJECTED
        self.assertFalse(
            worker_a._fenced_finalize(
                job_id=job_id,
                task_id=str(task_id),
                attempt_id=job_attempt_1.execution_attempt_id,
                new_status="FAILED",
                error="stale overwrite",
            )
        )
        self.assertIsNone(
            worker_a.record_event(
                task_id=str(task_id),
                job_id=job_id,
                phase="FAILED",
                event_type="status",
                message="stale event",
                expected_attempt_id=job_attempt_1.execution_attempt_id,
            )
        )

        # Worker B executes attempt 2 with deterministic stub provider -> completes cleanly
        worker_b.llm_router = _StubRouter(_StubProvider([{"content": "Workspace inspection complete.", "tool_calls": []}]))
        ran_ok = await worker_b.execute_job(job_attempt_2)
        self.assertTrue(ran_ok)

        with get_db_context() as db:
            final_job = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            final_task = db.query(CodingTask).filter(CodingTask.id == task_id).first()
            events = db.query(CodingTaskEvent).filter(CodingTaskEvent.task_id == str(task_id)).order_by(CodingTaskEvent.sequence_number.asc()).all()

            self.assertEqual(final_job.status, "COMPLETED_VERIFIED")
            self.assertEqual(final_job.worker_id, "worker_B")
            self.assertEqual(final_task.status, "COMPLETED_VERIFIED")
            self.assertIsNotNone(final_task.completed_at)
            self.assertTrue(final_task.verification_summary.get("verification_passed"))

            seqs = [e.sequence_number for e in events]
            self.assertEqual(seqs, list(range(1, len(seqs) + 1)), f"Event sequences not strictly monotonic: {seqs}")
            self.assertGreaterEqual(len(seqs), 3)

    async def test_cancellation_stops_active_execution_and_prevents_subsequent_tools(self):
        """Cancellation must interrupt active execution, stop subsequent tools, and preserve CANCELLED terminal state."""
        with get_db_context() as db:
            user = db.query(User).filter(User.id == self.user_a_id).first()
            ws = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == self.ws_a1_id).first()
            task, job, _ = create_and_enqueue_coding_job(db, user, ws, "Cancel test", "Explain files")
            task_id = task.id
            job_id = job.id

        worker = CodingJobWorker(worker_id="worker_cancel", heartbeat_interval=0.05)
        claimed = worker.claim_next_job()

        tool_calls_seen = []

        async def _slow_turn(idx):
            tool_calls_seen.append(idx)
            if idx == 0:
                # Request cancellation via API while agent is running
                r = self.client.post(f"/api/v1/coding/tasks/{task_id}/cancel", headers=self.headers_a)
                self.assertEqual(r.status_code, 200)
                await asyncio.sleep(0.3)
            return {"content": "Should not finish", "tool_calls": [{"id": "tc1", "name": "repository_tree", "arguments": {}}]}

        worker.llm_router = _StubRouter(_StubProvider([_slow_turn]))
        result = await worker.execute_job(claimed)
        self.assertFalse(result)
        self.assertEqual(tool_calls_seen, [0])

        with get_db_context() as db:
            j = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            t = db.query(CodingTask).filter(CodingTask.id == task_id).first()
            self.assertEqual(j.status, "CANCELLED")
            self.assertEqual(t.status, "CANCELLED")
            self.assertIsNotNone(t.completed_at)

    def test_cross_user_and_cross_workspace_authorization_and_uuid_validation(self):
        """Phase 3: User B must receive 404 on all User A coding task/workspace endpoints; bad UUIDs return 400."""
        with get_db_context() as db:
            user_a = db.query(User).filter(User.id == self.user_a_id).first()
            ws_a1 = db.query(RepositoryWorkspace).filter(RepositoryWorkspace.id == self.ws_a1_id).first()
            task, job, _ = create_and_enqueue_coding_job(db, user_a, ws_a1, "Secret task", "Fix auth")
            task_id = str(task.id)
            job_id = job.id

        append_coding_task_event(
            task_id=task_id,
            job_id=job_id,
            phase="EXPLORING",
            event_type="status",
            message="CONFIDENTIAL_USER_A_LOG",
        )

        # User B attempts all endpoints -> MUST get 404 without leaking existence
        for method, path in [
            ("GET", f"/api/v1/coding/tasks/{task_id}"),
            ("GET", f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks/{task_id}"),
            ("GET", f"/api/v1/coding/tasks/{task_id}/events"),
            ("GET", f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks/{task_id}/events"),
            ("GET", f"/api/v1/coding/tasks/{task_id}/events/stream"),
            ("GET", f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks/{task_id}/events/stream"),
            ("POST", f"/api/v1/coding/tasks/{task_id}/cancel"),
            ("POST", f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks/{task_id}/cancel"),
            ("DELETE", f"/api/v1/coding/workspaces/{self.ws_a1_id}"),
        ]:
            res = self.client.request(method, path, headers=self.headers_b)
            self.assertEqual(res.status_code, 404, f"User B got {res.status_code} on {method} {path}: {res.text}")
            self.assertNotIn("CONFIDENTIAL_USER_A_LOG", res.text)

        # User A querying task from ws_a1 under ws_a2 -> MUST get 404 (task does not belong to ws_a2)
        wrong_ws = self.client.get(
            f"/api/v1/coding/workspaces/{self.ws_a2_id}/tasks/{task_id}/events",
            headers=self.headers_a,
        )
        self.assertEqual(wrong_ws.status_code, 404)

        # User A querying own task under correct workspace -> 200 with event
        ok_res = self.client.get(
            f"/api/v1/coding/workspaces/{self.ws_a1_id}/tasks/{task_id}/events",
            headers=self.headers_a,
        )
        self.assertEqual(ok_res.status_code, 200)
        self.assertEqual(len(ok_res.json()), 1)

        # Malformed UUID inputs -> HTTP 400 (never 500)
        for bad_path in [
            "/api/v1/coding/tasks/not-a-uuid",
            "/api/v1/coding/tasks/not-a-uuid/events",
            "/api/v1/coding/tasks/not-a-uuid/events/stream",
            f"/api/v1/coding/workspaces/not-a-uuid/tasks/{task_id}",
        ]:
            bad_res = self.client.get(bad_path, headers=self.headers_a)
            self.assertEqual(bad_res.status_code, 400, f"Expected 400 on {bad_path}, got {bad_res.status_code}")


if __name__ == "__main__":
    unittest.main()
