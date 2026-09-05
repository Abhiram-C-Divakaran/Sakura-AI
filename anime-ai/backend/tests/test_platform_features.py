import unittest
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import User, Conversation, Message

class TestPlatformFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        # Register and log in test user
        cls.client.post("/api/v1/auth/register", json={"username": "platform_user", "password": "password12345"})
        res = cls.client.post("/api/v1/auth/token", data={"username": "platform_user", "password": "password12345"})
        cls.token = res.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_01_projects_lifecycle(self):
        """Test creating, attaching repositories, starting chats, and deleting projects."""
        # 1. Create project
        create_res = self.client.post(
            "/api/v1/projects",
            headers=self.headers,
            json={
                "name": "E-Commerce API",
                "description": "Backend microservices for payments and cart",
                "instructions": "Use TypeScript and follow domain-driven design."
            }
        )
        self.assertEqual(create_res.status_code, 200)
        proj = create_res.json()
        proj_id = proj["id"]
        self.assertEqual(proj["name"], "E-Commerce API")

        # 2. List projects
        list_res = self.client.get("/api/v1/projects", headers=self.headers)
        self.assertEqual(list_res.status_code, 200)
        self.assertTrue(any(p["id"] == proj_id for p in list_res.json()))

        # 3. Attach repository
        attach_res = self.client.post(
            f"/api/v1/projects/{proj_id}/repositories",
            headers=self.headers,
            json={
                "repository_url": "https://github.com/org/payments-service",
                "name": "payments-service"
            }
        )
        self.assertEqual(attach_res.status_code, 200)

        # 4. Start chat within project
        chat_res = self.client.post(
            f"/api/v1/projects/{proj_id}/conversations",
            headers=self.headers,
            json={"title": "Cart Service Architecture Discussion"}
        )
        self.assertEqual(chat_res.status_code, 200)
        self.assertIn("id", chat_res.json())

        # 5. Delete project
        del_res = self.client.delete(f"/api/v1/projects/{proj_id}", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)

    def test_02_scheduled_tasks_lifecycle(self):
        """Test scheduling, toggling, executing, and deleting background recurring tasks."""
        # 1. Create task
        create_res = self.client.post(
            "/api/v1/scheduled",
            headers=self.headers,
            json={
                "title": "Daily CI Audit",
                "prompt": "Inspect test coverage reports and flag regressions.",
                "schedule": "0 9 * * *",
                "timezone": "UTC",
                "enabled": True
            }
        )
        self.assertEqual(create_res.status_code, 200)
        task = create_res.json()
        task_id = task["id"]
        self.assertTrue(task["enabled"])

        # 2. Toggle enable/disable
        toggle_res = self.client.patch(
            f"/api/v1/scheduled/{task_id}",
            headers=self.headers,
            json={"enabled": False}
        )
        self.assertEqual(toggle_res.status_code, 200)
        self.assertFalse(toggle_res.json()["enabled"])

        # 3. Trigger manual execution
        run_res = self.client.post(f"/api/v1/scheduled/{task_id}/run", headers=self.headers)
        self.assertIn(run_res.status_code, [200, 202])
        self.assertIn(run_res.json()["status"], ["triggered", "QUEUED"])

        # 4. Delete task
        del_res = self.client.delete(f"/api/v1/scheduled/{task_id}", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)

    def test_03_message_feedback_and_sharing(self):
        """Test message feedback submission, conversation sharing, and public retrieval."""
        # 1. Create a conversation and message
        conv_res = self.client.post("/api/v1/conversations?character_id=sakura", headers=self.headers)
        self.assertEqual(conv_res.status_code, 200)
        conv_id = conv_res.json()["id"]

        with get_db_context() as db:
            msg = Message(
                conversation_id=uuid.UUID(conv_id),
                role="assistant",
                content="Here is the refactored database connection pool implementation."
            )
            db.add(msg)
            db.commit()
            msg_id = str(msg.id)

        # 2. Submit positive feedback
        fb_res = self.client.post(
            f"/api/v1/messages/{msg_id}/feedback",
            headers=self.headers,
            json={"rating": "positive", "comment": "Excellent refactor"}
        )
        self.assertEqual(fb_res.status_code, 200)
        self.assertEqual(fb_res.json()["rating"], "positive")

        # 3. Share conversation
        share_res = self.client.post(f"/api/v1/conversations/{conv_id}/share", headers=self.headers)
        self.assertEqual(share_res.status_code, 200)
        share_data = share_res.json()
        token = share_data["share_token"]
        self.assertTrue(bool(token))

        # 4. Public access to shared conversation (no auth header needed)
        public_res = self.client.get(f"/api/v1/share/{token}")
        self.assertEqual(public_res.status_code, 200)
        public_data = public_res.json()
        self.assertEqual(len(public_data["messages"]), 1)
        self.assertIn("refactored database", public_data["messages"][0]["content"])

        # 5. Revoke shared link
        revoke_res = self.client.delete(f"/api/v1/share/{token}", headers=self.headers)
        self.assertEqual(revoke_res.status_code, 200)

        # 6. Accessing revoked token must return 404
        revoked_get = self.client.get(f"/api/v1/share/{token}")
        self.assertEqual(revoked_get.status_code, 404)

    def test_04_conversation_search(self):
        """Search must find conversations matching title or message content."""
        search_res = self.client.get("/api/v1/conversations/search?q=refactored", headers=self.headers)
        self.assertEqual(search_res.status_code, 200)
        results = search_res.json()
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["match_type"], "message")
        self.assertIn("refactored", results[0]["snippet"].lower())

if __name__ == "__main__":
    unittest.main()
