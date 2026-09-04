import unittest
import os
import sys
import uuid
import io

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import User, Document

class TestLibraryMultiuser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        # Create user A
        cls.client.post("/api/v1/auth/register", json={"username": "user_alpha", "password": "password12345"})
        res_a = cls.client.post("/api/v1/auth/token", data={"username": "user_alpha", "password": "password12345"})
        cls.token_a = res_a.json()["access_token"]

        # Create user B
        cls.client.post("/api/v1/auth/register", json={"username": "user_bravo", "password": "password12345"})
        res_b = cls.client.post("/api/v1/auth/token", data={"username": "user_bravo", "password": "password12345"})
        cls.token_b = res_b.json()["access_token"]

    def test_multiuser_document_isolation(self):
        """User A uploads a document. User B must NOT be allowed to access it."""
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # User A uploads a document
        file_content = b"Confidential system architecture document for User Alpha."
        files = {"file": ("architecture_doc.txt", io.BytesIO(file_content), "text/plain")}
        upload_res = self.client.post("/api/v1/library/upload", headers=headers_a, files=files)
        self.assertEqual(upload_res.status_code, 200)
        doc_data = upload_res.json()["file"]
        doc_id = doc_data["id"]

        # User A can download their own document
        dl_res_a = self.client.get(f"/api/v1/library/files/{doc_id}/download", headers=headers_a)
        self.assertEqual(dl_res_a.status_code, 200)
        self.assertEqual(dl_res_a.content, file_content)

        # User B attempts to download User A's document -> must return 404 (file not found or access denied)
        dl_res_b = self.client.get(f"/api/v1/library/files/{doc_id}/download", headers=headers_b)
        self.assertEqual(dl_res_b.status_code, 404)
        self.assertIn("denied", dl_res_b.json()["detail"].lower())

        # Unauthenticated request -> must return 401
        dl_res_anon = self.client.get(f"/api/v1/library/files/{doc_id}/download")
        self.assertEqual(dl_res_anon.status_code, 401)

        # User B attempts to access thumbnail -> must return 404 (access denied)
        thumb_res_b = self.client.get(f"/api/v1/library/files/{doc_id}/thumbnail", headers=headers_b)
        self.assertEqual(thumb_res_b.status_code, 404)

    def test_filename_sanitization_against_traversal(self):
        """Uploading a file with malicious traversal characters must be sanitized safely."""
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        malicious_filename = "../../../etc/shadow.txt"
        files = {"file": (malicious_filename, io.BytesIO(b"shadow data"), "text/plain")}
        upload_res = self.client.post("/api/v1/library/upload", headers=headers_a, files=files)
        self.assertEqual(upload_res.status_code, 200)
        doc_data = upload_res.json()["file"]
        # Ensure stored filename stripped path traversal slashes
        self.assertNotIn("../", doc_data["filename"])
        self.assertNotIn("..\\", doc_data["filename"])

if __name__ == "__main__":
    unittest.main()
