import unittest
from unittest.mock import patch
import os
import sys
import uuid
import asyncio

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import Base, engine, get_db_context
from database.models import User, BackgroundTask
from tasks.task_manager import TaskManager, execute_web_research
from services.web_search import perform_web_search


class TestDurableTasks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Base.metadata.create_all(bind=engine)
        self.user1_id = uuid.uuid4()
        self.user2_id = uuid.uuid4()
        with get_db_context() as db:
            u1 = User(id=self.user1_id, username=f"task_u1_{uuid.uuid4().hex[:8]}", hashed_password="pw")
            u2 = User(id=self.user2_id, username=f"task_u2_{uuid.uuid4().hex[:8]}", hashed_password="pw")
            db.add_all([u1, u2])
            db.commit()

    def test_durable_task_persistence(self):
        """Created task must persist in database with initial Queued status and progress 0."""
        task = TaskManager.create_task(
            user_id=self.user1_id,
            task_type="code_analysis",
            title="Review Authentication Logic",
            payload={"code": "def login(): pass", "task": "explain"}
        )
        self.assertIsNotNone(task.id)
        self.assertEqual(task.status, "Queued")
        self.assertEqual(task.progress, 0)
        self.assertEqual(task.user_id, self.user1_id)

        # Verify query from database
        fetched = TaskManager.get_task(task.id, self.user1_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Review Authentication Logic")

    def test_user_task_isolation_idor(self):
        """User B cannot fetch, cancel, or delete User A's background task."""
        task = TaskManager.create_task(
            user_id=self.user1_id,
            task_type="dataset_analysis",
            title="User 1 Secret Dataset",
            payload={"dataset_text": "a,b,c\n1,2,3"}
        )

        # User 2 cannot access
        self.assertIsNone(TaskManager.get_task(task.id, self.user2_id))
        self.assertFalse(TaskManager.delete_task(task.id, self.user2_id))

        user2_tasks = TaskManager.list_tasks(self.user2_id)
        self.assertEqual(len(user2_tasks), 0)

    async def test_task_cancellation_and_retry(self):
        """Cancelling a task marks status Cancelled; retry increments retry_count and resets state."""
        task = TaskManager.create_task(
            user_id=self.user1_id,
            task_type="code_analysis",
            title="Long Running Analysis",
            payload={"code": "x = 1", "task": "explain"}
        )

        cancelled = await TaskManager.cancel_task(task.id, self.user1_id)
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, "Cancelled")
        self.assertIsNotNone(cancelled.completed_at)

        retried = await TaskManager.retry_task(task.id, self.user1_id)
        self.assertIsNotNone(retried)
        self.assertEqual(retried.status, "Queued")
        self.assertEqual(retried.retry_count, 1)
        self.assertIsNone(retried.completed_at)

    async def test_web_research_truthful_failure_when_empty_or_unavailable(self):
        """Web research must fail truthfully without fabricating research results if query is empty."""
        with patch.dict(os.environ, {"SAKURA_EMBEDDED_WORKER": "true"}):
            task = TaskManager.create_task(
                user_id=self.user1_id,
                task_type="web_research",
                title="Empty Query Research",
                payload={"query": "   "}
            )
            task_id_str = str(task.id)
            from tasks.task_manager import ACTIVE_ASYNCIO_TASKS
            if task_id_str in ACTIVE_ASYNCIO_TASKS:
                await ACTIVE_ASYNCIO_TASKS[task_id_str]

        fetched = TaskManager.get_task(task.id, self.user1_id)
        self.assertEqual(fetched.status, "Failed")
        self.assertIn("Empty query", fetched.error)
        self.assertIsNone(fetched.result)


if __name__ == "__main__":
    unittest.main()
