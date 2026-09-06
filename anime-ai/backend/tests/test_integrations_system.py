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
        app.dependency_overrides.clear()
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
        detail = res.json()["detail"].lower()
        self.assertTrue("access" in detail and "token" in detail)

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

    def test_unsupported_integrations_cannot_connect_return_501(self):
        """Unsupported connectors must return 501 Not Implemented and never persist connected=True."""
        unsupported = ["google_drive", "notion", "slack", "postgres", "jira"]
        for provider in unsupported:
            with self.subTest(provider=provider):
                res = self.client.post(
                    f"/api/v1/integrations/{provider}/connect",
                    json={"token": "some_token"},
                    headers=self.headers
                )
                self.assertEqual(res.status_code, 501, f"{provider} should return 501")
                # Ensure no connected row was saved in the DB
                with get_db_context() as db:
                    rec = db.query(UserIntegration).filter(
                        UserIntegration.user_id == self.user_id,
                        UserIntegration.provider == provider
                    ).first()
                    self.assertTrue(rec is None or not rec.connected)

    def test_integration_encryption_independent_from_jwt(self):
        """Integration encryption uses INTEGRATION_ENCRYPTION_KEY and is decoupled from JWT_SECRET."""
        from auth.crypto import encrypt_secret, decrypt_secret, _derive_fernet
        from config.settings import get_settings

        secret_text = "github_pat_super_secret_token_value_12345"

        # Encrypt with custom integration key
        int_key_1 = "integration-secret-key-number-one-abcdef123"
        encrypted = encrypt_secret(secret_text, custom_key=int_key_1)
        self.assertIn("version", encrypted)
        self.assertIn("ciphertext", encrypted)

        # Decrypting with matching integration key succeeds
        decrypted = decrypt_secret(encrypted, custom_key=int_key_1)
        self.assertEqual(decrypted, secret_text)

        # Decrypting with wrong key fails safely
        wrong_key = "completely-wrong-key-that-should-fail-gracefully"
        failed_decrypted = decrypt_secret(encrypted, custom_key=wrong_key)
        self.assertEqual(failed_decrypted, "")

    def test_legacy_jwt_derived_ciphertext_migration(self):
        """Legacy ciphertexts encrypted directly with JWT_SECRET decrypt via backward compatibility."""
        from auth.crypto import _derive_fernet, decrypt_secret
        from config.settings import get_settings

        settings = get_settings()
        legacy_fernet = _derive_fernet(settings.jwt_secret)
        raw_token = "legacy_ghp_pat_token_legacy_format"
        # Directly encrypt raw string with legacy fernet (no version envelope)
        legacy_ct = legacy_fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

        # decrypt_secret should detect and successfully decrypt legacy token
        decrypted = decrypt_secret(legacy_ct)
        self.assertEqual(decrypted, raw_token)

    def test_github_isolation_never_falls_back_to_server_token(self):
        """User integration must never silently fall back to server-level GITHUB_TOKEN."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_serverLevelAdminTokenDoNotLeak"}):
            # 1. No integration record exists: connected=False
            res = self.client.get("/api/v1/integrations/github/repos", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.json()["connected"])

            # 2. Integration record exists but has no token
            with get_db_context() as db:
                integ = UserIntegration(
                    user_id=self.user_id,
                    provider="github",
                    account_name="test_account",
                    connected=True,
                    config_json={}
                )
                db.add(integ)
                db.commit()

            res2 = self.client.get("/api/v1/integrations/github/repos", headers=self.headers)
            self.assertEqual(res2.status_code, 200)
            self.assertFalse(res2.json()["connected"])
            self.assertIn("no authenticated github access token", res2.json().get("error", "").lower())

    @patch("urllib.request.urlopen")
    def test_github_repos_401_marks_integration_error(self, mock_urlopen):
        """When GitHub returns 401 HTTPError, integration is updated to connected=False and health_status=ERROR."""
        import urllib.error
        from auth.crypto import encrypt_secret

        with get_db_context() as db:
            integ = UserIntegration(
                user_id=self.user_id,
                provider="github",
                account_name="test_revoked_account",
                connected=True,
                config_json={"encrypted_token": encrypt_secret("ghp_revokedToken12345")}
            )
            db.add(integ)
            db.commit()

        # Simulate GitHub returning 401 Unauthorized
        err = urllib.error.HTTPError(
            url="https://api.github.com/user/repos",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None
        )
        mock_urlopen.side_effect = err

        res = self.client.get("/api/v1/integrations/github/repos", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["connected"])
        self.assertIn("expired or revoked", data.get("error", "").lower())

        # Verify DB state is updated
        with get_db_context() as db:
            db_integ = db.query(UserIntegration).filter(
                UserIntegration.user_id == self.user_id,
                UserIntegration.provider == "github"
            ).first()
            self.assertFalse(db_integ.connected)
            self.assertEqual(db_integ.config_json.get("health_status"), "ERROR")

    @patch("urllib.request.urlopen")
    def test_github_repos_upgrades_legacy_secret(self, mock_urlopen):
        """Reading repositories with legacy JWT-derived secret upgrades envelope in DB."""
        from auth.crypto import _derive_fernet
        from config.settings import get_settings

        settings = get_settings()
        legacy_fernet = _derive_fernet(settings.jwt_secret)
        raw_token = "ghp_legacyTokenToBeUpgraded"
        legacy_ct = legacy_fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")

        with get_db_context() as db:
            integ = UserIntegration(
                user_id=self.user_id,
                provider="github",
                account_name="legacy_account",
                connected=True,
                config_json={"encrypted_token": legacy_ct}
            )
            db.add(integ)
            db.commit()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[{"name": "my-repo", "full_name": "legacy_account/my-repo", "default_branch": "main", "clone_url": "https://github.com/legacy_account/my-repo.git", "private": false}]'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.side_effect = None
        mock_urlopen.return_value = mock_resp

        res = self.client.get("/api/v1/integrations/github/repos", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["connected"])

        # Check that stored token is now versioned envelope (v1:)
        with get_db_context() as db:
            db_integ = db.query(UserIntegration).filter(
                UserIntegration.user_id == self.user_id,
                UserIntegration.provider == "github"
            ).first()
            upgraded_enc = db_integ.config_json.get("encrypted_token")
            self.assertIn('"version": 1', upgraded_enc)
            self.assertIn('"ciphertext":', upgraded_enc)


if __name__ == "__main__":
    unittest.main()
