import os
import sys
import uuid
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from database.db import Base, engine, get_db_context
from database.models import User, Document
from services.storage import (
    get_storage_backend,
    LocalFilesystemStorage,
    build_document_storage_key,
    check_storage_readiness
)
from services.documents import (
    create_document,
    get_document_content,
    delete_document
)


class TestStoragePersistenceIntegration(unittest.TestCase):
    """Integration test proving storage durability and process lifecycle persistence."""

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=f"storage_user_{self.user_id.hex[:6]}",
                hashed_password="fakehashedpassword"
            )
            db.add(user)
            db.commit()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_backend = os.environ.get("SAKURA_STORAGE_BACKEND")
        self.orig_root = os.environ.get("SAKURA_STORAGE_ROOT")
        os.environ["SAKURA_STORAGE_BACKEND"] = "local"
        os.environ["SAKURA_STORAGE_ROOT"] = self.temp_dir.name

    def tearDown(self):
        if self.orig_backend:
            os.environ["SAKURA_STORAGE_BACKEND"] = self.orig_backend
        else:
            os.environ.pop("SAKURA_STORAGE_BACKEND", None)
        if self.orig_root:
            os.environ["SAKURA_STORAGE_ROOT"] = self.orig_root
        else:
            os.environ.pop("SAKURA_STORAGE_ROOT", None)
        self.temp_dir.cleanup()

    def test_storage_readiness_check(self):
        """Validates storage readiness structure and health."""
        readiness = check_storage_readiness(is_production=False)
        self.assertEqual(readiness["backend"], "local")
        self.assertTrue(readiness["configured"])
        self.assertTrue(readiness["healthy"])
        self.assertIn(readiness["status"], ["AVAILABLE", "OPERATIONAL"])

    def test_full_storage_lifecycle_and_process_restart(self):
        """
        1. Upload object
        2. Persist DB row
        3. Destroy/recreate storage client (simulate process restart)
        4. Object still exists
        5. Worker can read same object
        6. Download works
        7. Size is identical
        """
        content_text = "Hello, Sakura AI persistent storage! " * 1024  # ~37KB
        content_bytes = content_text.encode("utf-8")
        filename = "architecture_doc.md"

        # 1 & 2: Upload object and persist DB row
        with get_db_context() as db:
            doc = create_document(
                filename=filename,
                content=content_text,
                user_id=self.user_id,
                db=db
            )
            doc_id = doc.id
            storage_key = doc.storage_key
            storage_size = doc.storage_size
            self.assertEqual(storage_size, len(content_bytes))

        # 3. Simulate process restart by instantiating a completely fresh storage backend
        new_storage_backend = LocalFilesystemStorage(root_dir=self.temp_dir.name)

        # 4. Verify object still exists in the newly instantiated backend
        self.assertTrue(new_storage_backend.exists(storage_key))
        self.assertEqual(new_storage_backend.get_size(storage_key), len(content_bytes))

        # 5. Worker reads same object using storage backend
        read_bytes = new_storage_backend.get_bytes(storage_key)
        self.assertEqual(read_bytes, content_bytes)

        # 6. Service layer download / content retrieval works
        with get_db_context() as db:
            result = get_document_content(doc_id=doc_id, user_id=self.user_id, db=db)
            self.assertEqual(result["content"], content_text)
            self.assertEqual(result["filename"], filename)
            self.assertEqual(result["mime_type"], "text/markdown")

        # 7. Clean deletion purges both DB and physical storage
        with get_db_context() as db:
            delete_document(doc_id=doc_id, user_id=self.user_id, db=db)

        self.assertFalse(new_storage_backend.exists(storage_key))


if __name__ == "__main__":
    unittest.main()
