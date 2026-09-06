import os
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["INTEGRATION_ENCRYPTION_KEY"] = "test-integration-encryption-key-32chars!"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-testing-only-32b!"

from main import app
from auth.manager import AuthManager
from database.models import User
from database.db import get_db_context


class TestCapabilitiesTruthfulness(unittest.TestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            user = db.query(User).filter(User.id == self.user_id).first()
            if not user:
                user = User(
                    id=self.user_id,
                    username=f"cap_user_{uuid.uuid4().hex[:6]}",
                    hashed_password="pw"
                )
                db.add(user)
                db.commit()

        user_obj = None
        with get_db_context() as db:
            user_obj = db.query(User).filter(User.id == self.user_id).first()

        app.dependency_overrides[AuthManager.get_current_user] = lambda: user_obj
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_image_generation_capability_truthful(self):
        """Image generation capability must reflect actual runtime (Pollinations/Flux/Turbo), not DALL-E 3."""
        resp = self.client.get("/api/v1/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        image_cap = data.get("image_generation", {})
        self.assertEqual(image_cap.get("status"), "AVAILABLE")
        self.assertEqual(image_cap.get("provider"), "pollinations")
        self.assertIn("flux", image_cap.get("models", []))
        self.assertIn("turbo", image_cap.get("models", []))
        self.assertTrue(image_cap.get("text_to_image"))
        self.assertFalse(image_cap.get("editing_available", True))
        self.assertFalse(image_cap.get("upscale_available", True))
        self.assertFalse(image_cap.get("image_conditioned_edit", True))
        self.assertFalse(image_cap.get("true_upscale", True))

    def test_rag_capability_truthful(self):
        """RAG capability must reflect whether dense embeddings are configured."""
        resp = self.client.get("/api/v1/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        subsystems = data.get("subsystems", {})
        rag_cap = subsystems.get("rag_engine", {})
        self.assertIn(rag_cap.get("status"), ["AVAILABLE", "DEGRADED"])
        self.assertTrue(rag_cap.get("lexical_bm25"))

    def test_readiness_endpoint(self):
        """Readiness endpoint must truthfully check DB, schema, and security secrets."""
        resp = self.client.get("/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("database", data)
        self.assertEqual(data["database"], "CONNECTED")
        self.assertTrue(data.get("schema_migrated"))
        self.assertIn("secrets_configured", data)


if __name__ == "__main__":
    unittest.main()
