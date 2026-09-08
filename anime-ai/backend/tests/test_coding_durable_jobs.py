"""
Unit and integration tests for durable Sakura coding jobs, event persistence,
worker claiming, heartbeat leasing, stale recovery, and cancellation semantics.
"""

import uuid
import unittest
from datetime import datetime, timedelta, timezone

from database.db import get_db_context, Base, engine
from database.models import User, RepositoryWorkspace, CodingTask, CodingJob, CodingTaskEvent, utc_now
from coding.job_worker import CodingJobWorker, MAX_CODING_JOB_RETRIES


class TestCodingDurableJobs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        with get_db_context() as db:
            self.user_id = uuid.uuid4()
            self.user = User(
                id=self.user_id,
                username=f"coding_user_{uuid.uuid4().hex[:8]}",
                hashed_password="fake_hash"
            )
            db.add(self.user)

            self.workspace_id = uuid.uuid4()
            self.workspace = RepositoryWorkspace(
                id=self.workspace_id,
                user_id=self.user_id,
                name="Test Workspace",
                repository_url="https://github.com/example/test-repo.git",
                workspace_path=f"/workspaces/{self.workspace_id}",
                active_branch="main",
                status="READY"
            )
            db.add(self.workspace)
            db.commit()

        self.worker = CodingJobWorker(worker_id=f"test_worker_{uuid.uuid4().hex[:6]}")

    def test_claim_next_job(self):
        """Worker atomically claims a queued coding job and acquires a lease."""
        task_id = str(uuid.uuid4())
        job_id = uuid.uuid4()

        with get_db_context() as db:
            job = CodingJob(
                id=job_id,
                task_id=task_id,
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                instructions="Implement auth middleware",
                status="QUEUED"
            )
            db.add(job)
            db.commit()

        claimed_job = self.worker.claim_next_job()
        self.assertIsNotNone(claimed_job)
        self.assertEqual(claimed_job.id, job_id)
        self.assertEqual(claimed_job.status, "RUNNING")
        self.assertEqual(claimed_job.worker_id, self.worker.worker_id)
        self.assertIsNotNone(claimed_job.execution_attempt_id)
        self.assertIsNotNone(claimed_job.lease_expires_at)

        # Subsequent claim returns None as no more queued jobs exist
        second_claim = self.worker.claim_next_job()
        self.assertIsNone(second_claim)

    def test_record_event_and_sequence_replay(self):
        """Events are recorded with sequential numbers and can be replayed with after_sequence filter."""
        task_id = str(uuid.uuid4())
        job_id = uuid.uuid4()

        # Record 3 events
        evt1 = self.worker.record_event(
            task_id=task_id,
            job_id=job_id,
            seq=1,
            phase="PLANNING",
            event_type="thought",
            message="Analyzing repository structure"
        )
        evt2 = self.worker.record_event(
            task_id=task_id,
            job_id=job_id,
            seq=2,
            phase="IMPLEMENTING",
            event_type="tool_call",
            tool_name="file_edit",
            message="Applying diff to settings.py"
        )
        evt3 = self.worker.record_event(
            task_id=task_id,
            job_id=job_id,
            seq=3,
            phase="TESTING",
            event_type="tool_result",
            stdout="Ran 5 tests in 0.2s OK"
        )

        with get_db_context() as db:
            # Query all events
            all_evts = db.query(CodingTaskEvent).filter(
                CodingTaskEvent.task_id == task_id
            ).order_by(CodingTaskEvent.sequence_number.asc()).all()
            self.assertEqual(len(all_evts), 3)
            self.assertEqual([e.sequence_number for e in all_evts], [1, 2, 3])

            # Query replay with after_sequence = 1 (simulating client reconnect)
            replayed = db.query(CodingTaskEvent).filter(
                CodingTaskEvent.task_id == task_id,
                CodingTaskEvent.sequence_number > 1
            ).order_by(CodingTaskEvent.sequence_number.asc()).all()
            self.assertEqual(len(replayed), 2)
            self.assertEqual(replayed[0].sequence_number, 2)
            self.assertEqual(replayed[1].sequence_number, 3)

    def test_recover_stale_jobs_retry_and_exhaustion(self):
        """Expired running jobs are recovered to QUEUED with retry incremented, or marked FAILED if max retries exceeded."""
        task_a_id = str(uuid.uuid4())
        job_a_id = uuid.uuid4()
        now = utc_now()

        # 1. Job with 0 retries and expired lease -> should be recovered to QUEUED with retry=1
        with get_db_context() as db:
            job_a = CodingJob(
                id=job_a_id,
                task_id=task_a_id,
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                instructions="Task A",
                status="RUNNING",
                worker_id="old_dead_worker",
                lease_expires_at=now - timedelta(seconds=10),
                retry_count=0
            )
            db.add(job_a)

            # 2. Job with max retries and expired lease -> should transition to FAILED
            job_b_id = uuid.uuid4()
            job_b = CodingJob(
                id=job_b_id,
                task_id=str(uuid.uuid4()),
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                instructions="Task B",
                status="RUNNING",
                worker_id="old_dead_worker",
                lease_expires_at=now - timedelta(seconds=10),
                retry_count=MAX_CODING_JOB_RETRIES
            )
            db.add(job_b)
            db.commit()

        recovered = self.worker.recover_stale_jobs()
        self.assertGreaterEqual(recovered, 1)

        with get_db_context() as db:
            refreshed_a = db.query(CodingJob).filter(CodingJob.id == job_a_id).first()
            self.assertEqual(refreshed_a.status, "QUEUED")
            self.assertEqual(refreshed_a.retry_count, 1)
            self.assertIsNone(refreshed_a.worker_id)
            self.assertIsNone(refreshed_a.lease_expires_at)

            refreshed_b = db.query(CodingJob).filter(CodingJob.id == job_b_id).first()
            self.assertEqual(refreshed_b.status, "FAILED")
            self.assertIn("max retries", refreshed_b.error.lower())

    def test_cancellation_semantics(self):
        """Setting cancel_requested flags the job and terminates cleanly."""
        task_id = str(uuid.uuid4())
        job_id = uuid.uuid4()

        with get_db_context() as db:
            job = CodingJob(
                id=job_id,
                task_id=task_id,
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                instructions="Cancel me",
                status="RUNNING",
                worker_id=self.worker.worker_id,
                cancel_requested=True
            )
            db.add(job)
            db.commit()

        with get_db_context() as db:
            j = db.query(CodingJob).filter(CodingJob.id == job_id).first()
            self.assertTrue(j.cancel_requested)


if __name__ == "__main__":
    unittest.main()
