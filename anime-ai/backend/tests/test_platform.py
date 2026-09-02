import unittest
import os
import sys

# Force SQLite configuration for test environment before imports
os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"

# Adjust import path to include backend root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import User, Conversation, Message, UserMemory, Document

class TestAnimeAIPlatform(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Prepare in-memory SQLite tables for isolated API pipeline test."""
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        """Tear down SQLite test database."""
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        if os.path.exists("./test_anime_ai.db"):
            os.remove("./test_anime_ai.db")

    def test_01_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["system"], "Neo-Tokyo AI Core")

    def test_02_register_and_login_operator(self):
        # Register operator
        reg_payload = {"username": "test_operator", "password": "securepassword123"}
        response = self.client.post("/api/v1/auth/register", json=reg_payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())

        # Login to retrieve token
        login_payload = {"username": "test_operator", "password": "securepassword123"}
        login_response = self.client.post("/api/v1/auth/token", data=login_payload)
        self.assertEqual(login_response.status_code, 200)
        token_data = login_response.json()
        self.assertIn("access_token", token_data)
        self.assertEqual(token_data["token_type"], "bearer")

        # Save active token
        self.__class__.token = token_data["access_token"]

    def test_03_create_conversation_channel(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.client.post("/api/v1/conversations?character_id=sakura", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["character_id"], "sakura")
        self.assertIn("id", data)
        self.__class__.conversation_id = data["id"]

    def test_04_list_operator_conversations(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.client.get("/api/v1/conversations", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) > 0)
        self.assertEqual(data[0]["id"], self.conversation_id)

    def test_05_chat_stream_inference(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"conversation_id": self.conversation_id, "message": "Verify login system diagnostics."}
        response = self.client.post("/api/v1/chat/stream", json=payload, headers=headers)
        
        # Verify streaming SSE content type response header
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        
        # Extract SSE stream content tokens
        sse_text = response.text
        self.assertIn("data: ", sse_text)
        self.assertIn("token", sse_text)

    def test_06_load_dialogue_history(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.client.get(f"/api/v1/conversations/{self.conversation_id}/messages", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify conversation logs contain at least the user's prompt and agent's stream reply
        self.assertTrue(len(data) >= 2)
        self.assertEqual(data[0]["role"], "user")
        self.assertEqual(data[1]["role"], "assistant")

    def test_07_inject_custom_memory(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        
        with get_db_context() as db:
            # Query the user registered
            user = db.query(User).filter(User.username == "test_operator").first()
            self.assertIsNotNone(user)
            
            # Manually seed a user memory block
            mem = UserMemory(
                user_id=user.id,
                memory_type="preference",
                content="Operator prefers retro VHS scans.",
                confidence=0.95
            )
            db.add(mem)
            db.commit()
            mem_id = str(mem.id)

        # Retrieve memory bank list via API
        response = self.client.get("/api/v1/memory", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(m["id"] == mem_id for m in data))

        # Delete memory block
        del_response = self.client.delete(f"/api/v1/memory/{mem_id}", headers=headers)
        self.assertEqual(del_response.status_code, 200)
        self.assertEqual(del_response.json()["status"], "deleted")

if __name__ == "__main__":
    unittest.main()
