import unittest
import os
import sys
import uuid
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import User, UserIntegration
from auth.manager import AuthManager
from auth.crypto import decrypt_secret


class TestIntegrationsSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.user_id = uuid.uuid4()
        cls.username = f"int_user_{uuid.uuid4().hex[:8]}"
        with get_db_context() as db:
            u = User(id=cls.user_id, username=cls.username, hashed_password="pw")
            db.add(u)
            db.commit()
        cls.token = AuthManager.create_access_token({"sub": cls.username})
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def setUp(self):
        with get_db_context() as db:
            db.query(UserIntegration).filter(UserIntegration.user_id == self.user_id).delete()
            db.commit()

    def test_integrations_status_canonical_schema(self):
        """All integrations must match the canonical schema with valid state and capabilities."""
        res = self.client.get("/api/v1/integrations", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 6)

        gh = next((i for i in items if i["id"] == "github"), None)
        self.assertIsNotNone(gh)
        for expected_key in [
            "id", "name", "category", "description", "state", "connected",
            "account_name", "connected_at", "updated_at", "capabilities"
        ]:
            self.assertIn(expected_key, gh)

        # By default without credentials, state is NOT_CONFIGURED or DISCONNECTED, never CONNECTED
        self.assertIn(gh["state"], ["NOT_CONFIGURED", "DISCONNECTED"])
        self.assertFalse(gh["connected"])
        self.assertIsNone(gh["account_name"])
        self.assertIn("repo:read", gh["capabilities"])

    def test_github_connect_rejects_missing_token(self):
        """Connecting GitHub without credentials must be rejected with 400."""
        res = self.client.post(
            "/api/v1/integrations/github/connect",
            json={"account_name": "fake_account"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("access_token", res.json()["detail"].lower())

    @patch("urllib.request.urlopen")
    def test_github_connect_successful_with_encryption_at_rest(self, mock_urlopen):
        """Valid token connects GitHub, resolves login, encrypts token at rest, and never leaks token."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"login": "octocat", "id": 583231}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        raw_token = "ghp_realValidToken1234567890"
        res = self.client.post(
            "/api/v1/integrations/github/connect",
            json={"access_token": raw_token},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["id"], "github")
        self.assertEqual(data["state"], "CONNECTED")
        self.assertTrue(data["connected"])
        self.assertEqual(data["account_name"], "octocat")
        # Token must NOT be in the response
        self.assertNotIn("access_token", data)
        self.assertNotIn("encrypted_token", data)

        # Verify token is encrypted at rest in database
        with get_db_context() as db:
            rec = db.query(UserIntegration).filter(
                UserIntegration.user_id == self.user_id,
                UserIntegration.provider == "github"
            ).first()
            self.assertIsNotNone(rec)
            self.assertTrue(rec.connected)
            self.assertNotIn(raw_token, str(rec.config_json))
            enc = rec.config_json.get("encrypted_token")
            self.assertIsNotNone(enc)
            self.assertEqual(decrypt_secret(enc), raw_token)

    def test_disconnect_integration(self):
        """Disconnecting integration revokes connection and clears credentials."""
        res = self.client.post("/api/v1/integrations/github/disconnect", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["connected"])
        self.assertIn(data["state"], ["NOT_CONFIGURED", "DISCONNECTED"])


if __name__ == "__main__":
    unittest.main()
