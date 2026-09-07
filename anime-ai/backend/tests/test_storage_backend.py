import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from io import BytesIO

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage import (
    StorageBackend,
    LocalFilesystemStorage,
    S3CompatibleStorage,
    StoragePathTraversalError,
    StorageNotFoundError,
    build_document_storage_key,
    build_image_storage_key
)


class TestStorageBackend(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sakura_storage_test_")
        self.local_storage = LocalFilesystemStorage(base_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_local_storage_put_get_exists_delete(self):
        key = "users/test-user/documents/doc-1/test.txt"
        data = b"Hello, Sakura durable storage!"

        # Put
        res = self.local_storage.put(key, data, content_type="text/plain")
        self.assertEqual(res["key"], key)
        self.assertEqual(res["size"], len(data))

        # Exists
        self.assertTrue(self.local_storage.exists(key))

        # Get bytes
        retrieved = self.local_storage.get_bytes(key)
        self.assertEqual(retrieved, data)

        # Get size
        self.assertEqual(self.local_storage.get_size(key), len(data))

        # Open stream
        with self.local_storage.open(key) as stream:
            self.assertEqual(stream.read(), data)

        # Delete
        self.assertTrue(self.local_storage.delete(key))
        self.assertFalse(self.local_storage.exists(key))

    def test_local_storage_path_traversal_rejection(self):
        malicious_keys = [
            "../etc/passwd",
            "users/../../../etc/shadow",
            "/absolute/root/file.txt",
            "C:\\Windows\\System32\\calc.exe",
            "users/test/../../escaped.txt",
            "users/test/\0bad.txt"
        ]
        for bad_key in malicious_keys:
            with self.assertRaises(StoragePathTraversalError):
                self.local_storage.put(bad_key, b"exploit")

            with self.assertRaises(StoragePathTraversalError):
                self.local_storage.get_bytes(bad_key)

            with self.assertRaises(StoragePathTraversalError):
                self.local_storage.exists(bad_key)

    def test_storage_key_builders(self):
        user_id = "00000000-0000-0000-0000-000000000001"
        doc_id = "00000000-0000-0000-0000-000000000002"
        img_id = "00000000-0000-0000-0000-000000000003"

        doc_key = build_document_storage_key(user_id, doc_id, "notes.pdf")
        self.assertEqual(doc_key, f"users/{user_id}/documents/{doc_id}/notes.pdf")

        img_key = build_image_storage_key(user_id, img_id)
        self.assertEqual(img_key, f"users/{user_id}/images/{img_id}.png")

    def test_s3_storage_operations_mocked(self):
        mock_boto3 = MagicMock()
        mock_s3_client = MagicMock()
        mock_boto3.client.return_value = mock_s3_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            s3_storage = S3CompatibleStorage(
                bucket="test-bucket",
                endpoint_url="https://s3.example.com",
                region_name="us-east-1",
                access_key="fake-access",
                secret_key="fake-secret"
            )

            # Test put
            key = "users/test-user/images/img-1.png"
            data = b"\x89PNG\r\n\x1a\nFakeImageData"
            res = s3_storage.put(key, data, content_type="image/png")
            self.assertEqual(res["key"], key)
            mock_s3_client.put_object.assert_called_once()

            # Test exists
            mock_s3_client.head_object.return_value = {"ContentLength": len(data)}
            self.assertTrue(s3_storage.exists(key))

            # Test get_bytes
            mock_body = MagicMock()
            mock_body.read.return_value = data
            mock_s3_client.get_object.return_value = {"Body": mock_body, "ContentLength": len(data)}
            retrieved = s3_storage.get_bytes(key)
            self.assertEqual(retrieved, data)

            # Test delete
            self.assertTrue(s3_storage.delete(key))
            mock_s3_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key=key)


if __name__ == "__main__":
    unittest.main()
