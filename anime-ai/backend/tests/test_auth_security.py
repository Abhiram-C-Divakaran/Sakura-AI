import unittest
import os
import sys

# Force SQLite configuration for test environment before imports
os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from auth.manager import AuthManager
from database.db import Base, engine

class TestAuthSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    def test_password_strength_validation(self):
        """Test password complexity enforcement (min 8 chars)."""
        with self.assertRaises(Exception) as ctx:
            AuthManager.validate_password_strength("short")
        self.assertIn("at least 8 characters", str(ctx.exception))

        # Must not raise exception on valid password
        AuthManager.validate_password_strength("validpassword123")

    def test_register_rejects_weak_password(self):
        """API must reject registration with weak passwords."""
        res = self.client.post("/api/v1/auth/register", json={"username": "weakuser", "password": "123"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 8 characters", res.json()["detail"])

    def test_password_hashing_and_verification(self):
        """Verify bcrypt hashing generates non-reversible salt and checks accurately."""
        pw = "SuperSecurePassword999!"
        hashed = AuthManager.hash_password(pw)
        self.assertNotEqual(pw, hashed)
        self.assertTrue(AuthManager.verify_password(pw, hashed))
        self.assertFalse(AuthManager.verify_password("WrongPassword", hashed))

    def test_jwt_token_flow(self):
        """Verify JWT token encoding and decoding."""
        token = AuthManager.create_access_token({"sub": "security_test_user"})
        decoded = AuthManager.verify_token(token)
        self.assertEqual(decoded, "security_test_user")

        # Invalid token rejection
        invalid = AuthManager.verify_token("invalid.token.signature")
        self.assertIsNone(invalid)

    def test_production_guard_on_default_secret(self):
        """Verify system enforces production guard when insecure secret is configured in production."""
        with self.assertRaises(RuntimeError) as ctx:
            AuthManager.validate_production_secret(
                env="production", 
                secret="supersecret_vintage_anime_key_replace_in_production"
            )
        self.assertIn("Production startup failed", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
