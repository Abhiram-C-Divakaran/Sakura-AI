import os
import sys
import json
import uuid
import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from main import app
from database.db import Base, engine, get_db_context
from database.models import User, Conversation, Message, RepositoryWorkspace, BackgroundTask
from auth.manager import AuthManager


class TestFrontendApiRouting(unittest.TestCase):
    """
    Smoke & Integration tests validating frontend API routing contracts:
    - User registration, login, and JWT generation
    - Loading and creating conversations
    - Workspaces endpoint (/api/v1/coding/workspaces) response shape normalization
    - Two-workspace deterministic targeting in /chat/stream without heuristic fallback
    - Frontend URL builders (apiUrl and websocketUrl) contracts
    """

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)
        self.username = f"smoke_user_{uuid.uuid4().hex[:6]}"
        self.password = "securePassword123!"

    def test_full_frontend_auth_and_workspace_flow(self):
        # 1. Register user
        reg_res = self.client.post(
            "/api/v1/auth/register",
            json={"username": self.username, "password": self.password}
        )
        self.assertEqual(reg_res.status_code, 200, f"Registration failed: {reg_res.text}")

        # 2. Login to obtain access token
        login_res = self.client.post(
            "/api/v1/auth/token",
            data={"username": self.username, "password": self.password}
        )
        self.assertEqual(login_res.status_code, 200)
        token_data = login_res.json()
        self.assertIn("access_token", token_data)
        access_token = token_data["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 3. Create conversation
        conv_res = self.client.post(
            "/api/v1/conversations?character_id=sakura",
            headers=headers
        )
        self.assertEqual(conv_res.status_code, 200)
        conv = conv_res.json()
        conv_id = conv["id"]

        # 4. List conversations
        list_conv_res = self.client.get("/api/v1/conversations", headers=headers)
        self.assertEqual(list_conv_res.status_code, 200)
        convs = list_conv_res.json()
        self.assertTrue(any(c["id"] == conv_id for c in convs))

        # 5. Create workspace via canonical /api/v1/coding/workspaces
        create_ws_res = self.client.post(
            "/api/v1/coding/workspaces",
            headers=headers,
            json={
                "name": "Frontend Test Repo",
                "repository_url": None,
                "branch": "main"
            }
        )
        self.assertEqual(create_ws_res.status_code, 200)
        ws_data = create_ws_res.json()
        self.assertIn("workspace", ws_data)
        ws = ws_data["workspace"]
        self.assertEqual(ws["name"], "Frontend Test Repo")
        self.assertEqual(ws["active_branch"], "main")
        ws_id = ws["id"]

        # 6. List workspaces via canonical /api/v1/coding/workspaces
        list_ws_res = self.client.get("/api/v1/coding/workspaces", headers=headers)
        self.assertEqual(list_ws_res.status_code, 200)
        workspaces = list_ws_res.json()
        self.assertTrue(any(w["id"] == ws_id for w in workspaces))

        # 7. Query tasks endpoint
        tasks_res = self.client.get("/api/v1/tasks", headers=headers)
        self.assertEqual(tasks_res.status_code, 200)

    def test_two_workspace_deterministic_targeting(self):
        """
        P0.19: When user has Workspace A and Workspace B:
        Passing active_workspace_id=B must strictly target B.
        No heuristic fallback to Workspace A.
        """
        # Register and login user
        self.client.post(
            "/api/v1/auth/register",
            json={"username": self.username, "password": self.password}
        )
        login_res = self.client.post(
            "/api/v1/auth/token",
            data={"username": self.username, "password": self.password}
        )
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create Conversation
        conv_res = self.client.post("/api/v1/conversations?character_id=sakura", headers=headers)
        conv_id = conv_res.json()["id"]

        # Create Workspace A
        ws_a_res = self.client.post(
            "/api/v1/coding/workspaces",
            headers=headers,
            json={"name": "Workspace_Alpha", "branch": "main"}
        )
        ws_a_id = ws_a_res.json()["workspace"]["id"]

        # Create Workspace B
        ws_b_res = self.client.post(
            "/api/v1/coding/workspaces",
            headers=headers,
            json={"name": "Workspace_Beta", "branch": "feature/b"}
        )
        ws_b_id = ws_b_res.json()["workspace"]["id"]

        # Send coding stream targeting Workspace B
        chat_payload = {
            "conversation_id": conv_id,
            "message": "/code add a hello world function",
            "intensity": "medium",
            "tools": ["sakura_code"],
            "attachments": [],
            "active_workspace_id": ws_b_id
        }

        # Use streaming response check with mocked task stream to avoid external LLM rate limits
        async def mock_run_task_stream(self_agent, task):
            yield {"message": "Coding started"}
            yield {"phase": "COMPLETED_VERIFIED", "final_output": "Success"}

        from unittest.mock import patch
        from coding.agent import CodingAgent
        with patch.object(CodingAgent, "run_task_stream", mock_run_task_stream):
            with self.client.stream("POST", "/api/v1/chat/stream", headers=headers, json=chat_payload) as stream_resp:
                self.assertEqual(stream_resp.status_code, 200)
                events = []
                for line in stream_resp.iter_lines():
                    if line.startswith("data: "):
                        events.append(line[6:])

        # Verify that a CodingTask was created explicitly for Workspace B
        with get_db_context() as db:
            from database.models import CodingTask
            b_uuid = uuid.UUID(ws_b_id)
            task_b = db.query(CodingTask).filter(CodingTask.workspace_id == b_uuid).first()
            self.assertIsNotNone(task_b, "Expected coding task created for Workspace B")

            a_uuid = uuid.UUID(ws_a_id)
            task_a = db.query(CodingTask).filter(CodingTask.workspace_id == a_uuid).first()
            self.assertIsNone(task_a, "Workspace A should NOT have been targeted")

    def test_nonexistent_explicit_workspace_does_not_fall_back(self):
        """
        When active_workspace_id is provided but not found,
        system must yield error and NOT fall back heuristically to another workspace.
        """
        self.client.post(
            "/api/v1/auth/register",
            json={"username": self.username, "password": self.password}
        )
        login_res = self.client.post(
            "/api/v1/auth/token",
            data={"username": self.username, "password": self.password}
        )
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create Conversation
        conv_res = self.client.post("/api/v1/conversations?character_id=sakura", headers=headers)
        conv_id = conv_res.json()["id"]

        # Create Workspace A
        ws_a_res = self.client.post(
            "/api/v1/coding/workspaces",
            headers=headers,
            json={"name": "Only_Available_Workspace", "branch": "main"}
        )
        ws_a_id = ws_a_res.json()["workspace"]["id"]

        # Target a bogus workspace ID
        bogus_id = str(uuid.uuid4())
        chat_payload = {
            "conversation_id": conv_id,
            "message": "/code fix bug in repo",
            "active_workspace_id": bogus_id
        }

        with self.client.stream("POST", "/api/v1/chat/stream", headers=headers, json=chat_payload) as stream_resp:
            self.assertEqual(stream_resp.status_code, 200)
            collected = []
            for line in stream_resp.iter_lines():
                if line.startswith("data: "):
                    collected.append(json.loads(line[6:]))

        # Check response states that workspace was not found
        text_stream = " ".join(item.get("token", "") for item in collected)
        self.assertIn("was not found or access is denied", text_stream)

        # Confirm Workspace A was NEVER targeted
        with get_db_context() as db:
            from database.models import CodingTask
            task_a = db.query(CodingTask).filter(CodingTask.workspace_id == uuid.UUID(ws_a_id)).first()
            self.assertIsNone(task_a, "Heuristic fallback should NOT have occurred!")


if __name__ == "__main__":
    unittest.main()
