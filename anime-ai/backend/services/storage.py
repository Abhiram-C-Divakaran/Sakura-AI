"""
Sakura AI — Canonical Durable Storage Subsystem

Provides unified object storage abstraction supporting:
1. LocalFilesystemStorage (local development, offline testing, strict realpath containment)
2. S3CompatibleStorage (production object storage: AWS S3, Cloudflare R2, MinIO)

Storage Key Conventions:
- Documents: users/<user_id>/documents/<document_id>/<filename>
- Generated images: users/<user_id>/images/<image_id>.png

Guarantees:
- Strict user isolation: user operations are checked against users/<user_id>/ prefix
- Local path traversal containment: resolved realpath must be within base storage directory
- Truthful file size, streaming response generation, presigned URLs where supported
"""

import os
import io
import uuid
import shutil
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Union, BinaryIO
from fastapi.responses import FileResponse, Response

logger = logging.getLogger("sakura.storage")


class StorageSecurityError(Exception):
    """Raised when storage path or key violates security constraints."""
    pass


class StorageObjectNotFoundError(Exception):
    """Raised when requested object does not exist in storage backend."""
    pass


# Exception aliases for compatibility
StoragePathTraversalError = StorageSecurityError
StorageNotFoundError = StorageObjectNotFoundError


def build_document_storage_key(user_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> str:
    """Generates canonical storage key for a user document."""
    clean_name = os.path.basename(filename or "document.bin").replace("\\", "_").replace("/", "_")
    return f"users/{user_id}/documents/{document_id}/{clean_name}"


def build_image_storage_key(user_id: uuid.UUID, image_id: uuid.UUID, ext: str = "png") -> str:
    """Generates canonical storage key for a generated image."""
    clean_ext = ext.lstrip(".").lower() or "png"
    return f"users/{user_id}/images/{image_id}.{clean_ext}"


def assert_user_storage_key(user_id: uuid.UUID, storage_key: str) -> None:
    """Enforces strict multi-tenant user isolation on storage keys."""
    expected_prefix = f"users/{user_id}/"
    norm_key = storage_key.replace("\\", "/").lstrip("/")
    if not norm_key.startswith(expected_prefix):
        raise StorageSecurityError(
            f"Storage key '{storage_key}' violates isolation boundary for user '{user_id}'."
        )


class StorageBackend(ABC):
    """Abstract base class defining the durable storage contract."""

    backend_type: str = "abstract"

    @abstractmethod
    def put(
        self,
        storage_key: str,
        data: Union[bytes, BinaryIO],
        content_type: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Persists object data to storage under the given key."""
        pass

    @abstractmethod
    def open(self, storage_key: str) -> BinaryIO:
        """Returns a readable binary stream for the stored object."""
        pass

    @abstractmethod
    def get_bytes(self, storage_key: str) -> bytes:
        """Returns the full binary contents of the stored object."""
        pass

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Checks if the object exists in storage."""
        pass

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Deletes the object from storage. Returns True if deleted or did not exist."""
        pass

    @abstractmethod
    def get_size(self, storage_key: str) -> int:
        """Returns the exact byte size of the stored object."""
        pass

    @abstractmethod
    def get_metadata(self, storage_key: str) -> Dict[str, Any]:
        """Returns object metadata including size, content type, modified timestamp."""
        pass

    @abstractmethod
    def generate_download_response(
        self,
        storage_key: str,
        filename: str,
        mime_type: Optional[str] = None
    ) -> Response:
        """Generates a FastAPI/Starlette Response for downloading the object."""
        pass

    @abstractmethod
    def generate_signed_url(self, storage_key: str, expires_in: int = 3600) -> Optional[str]:
        """Generates a presigned download URL if supported by the backend, else None."""
        pass


class LocalFilesystemStorage(StorageBackend):
    """
    Local filesystem storage adapter.
    Enforces canonical realpath containment to prevent path traversal.
    Maintains backward compatibility with legacy flat directory paths.
    """

    backend_type = "local"

    def __init__(self, root_dir: Optional[str] = None, base_dir: Optional[str] = None):
        target_dir = root_dir or base_dir or os.getenv("SAKURA_STORAGE_ROOT", "./uploaded_documents")
        self.root_dir = os.path.realpath(os.path.abspath(target_dir))
        os.makedirs(self.root_dir, exist_ok=True)

    def _resolve_key_path(self, storage_key: str) -> str:
        """Resolves storage_key to an absolute path within root_dir, guarding against traversal."""
        if not storage_key or not isinstance(storage_key, str):
            raise StorageSecurityError("Invalid storage key")

        if "\0" in storage_key:
            raise StorageSecurityError(f"Null byte detected in storage key: '{storage_key}'")

        if storage_key.startswith("/") or storage_key.startswith("\\") or ":" in storage_key:
            raise StorageSecurityError(f"Absolute path or drive reference not allowed in storage key: '{storage_key}'")

        parts = storage_key.replace("\\", "/").split("/")
        if any(p == ".." for p in parts):
            raise StorageSecurityError(f"Directory traversal component '..' detected in storage key: '{storage_key}'")

        clean_key = storage_key.replace("\\", "/").lstrip("/")
        target_path = os.path.realpath(os.path.abspath(os.path.join(self.root_dir, clean_key)))
        try:
            common = os.path.commonpath([self.root_dir, target_path])
        except ValueError:
            raise StorageSecurityError(f"Path traversal detected: '{storage_key}' on different drive.")

        if common != self.root_dir or (target_path != self.root_dir and not target_path.startswith(self.root_dir + os.sep)):
            raise StorageSecurityError(f"Storage path traversal detected: '{storage_key}' escapes storage root.")

        return target_path

    def put(
        self,
        storage_key: str,
        data: Union[bytes, BinaryIO],
        content_type: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        if user_id:
            assert_user_storage_key(user_id, storage_key)

        file_path = self._resolve_key_path(storage_key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if isinstance(data, (bytes, bytearray)):
            with open(file_path, "wb") as f:
                f.write(data)
            size = len(data)
        elif hasattr(data, "read"):
            with open(file_path, "wb") as f:
                shutil.copyfileobj(data, f)
            size = os.path.getsize(file_path)
        else:
            raise ValueError(f"Unsupported data type for storage put: {type(data)}")

        return {
            "storage_backend": self.backend_type,
            "storage_key": storage_key,
            "key": storage_key,
            "storage_size": size,
            "size": size,
            "storage_path": file_path,
            "content_type": content_type or "application/octet-stream"
        }

    def open(self, storage_key: str) -> BinaryIO:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found at {file_path}")
        return open(file_path, "rb")

    def get_bytes(self, storage_key: str) -> bytes:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found at {file_path}")
        with open(file_path, "rb") as f:
            return f.read()

    def exists(self, storage_key: str) -> bool:
        file_path = self._resolve_key_path(storage_key)
        return os.path.exists(file_path)

    def delete(self, storage_key: str) -> bool:
        try:
            file_path = self._resolve_key_path(storage_key)
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception as e:
            logger.warning(f"Error deleting storage object '{storage_key}': {e}")
            return False

    def get_size(self, storage_key: str) -> int:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found at {file_path}")
        return os.path.getsize(file_path)

    def get_metadata(self, storage_key: str) -> Dict[str, Any]:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found at {file_path}")
        stat = os.stat(file_path)
        return {
            "storage_backend": self.backend_type,
            "storage_key": storage_key,
            "storage_size": stat.st_size,
            "modified_time": stat.st_mtime,
            "storage_path": file_path
        }

    def generate_download_response(
        self,
        storage_key: str,
        filename: str,
        mime_type: Optional[str] = None
    ) -> Response:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found")
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=mime_type or "application/octet-stream"
        )

    def generate_signed_url(self, storage_key: str, expires_in: int = 3600) -> Optional[str]:
        return None


class S3CompatibleStorage(StorageBackend):
    """
    S3-compatible object storage adapter.
    Supports AWS S3, Cloudflare R2, MinIO, and self-hosted object stores.
    """

    backend_type = "s3"

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None
    ):
        self.bucket_name = bucket or bucket_name or os.getenv("SAKURA_STORAGE_BUCKET", "sakura-library")
        self.endpoint_url = endpoint_url or os.getenv("SAKURA_STORAGE_ENDPOINT")
        self.region_name = region_name or os.getenv("SAKURA_STORAGE_REGION", "us-east-1")
        self.access_key = access_key or os.getenv("SAKURA_STORAGE_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("SAKURA_STORAGE_SECRET_KEY")

        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise RuntimeError("boto3 must be installed to use S3CompatibleStorage.")

            cfg = Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"} if self.endpoint_url else {}
            )
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region_name,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=cfg
            )
        return self._client

    def ensure_bucket_exists(self) -> None:
        """Creates bucket if it does not exist (primarily useful in MinIO for tests/dev)."""
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self.bucket_name)
        except Exception:
            try:
                if self.region_name and self.region_name != "us-east-1":
                    client.create_bucket(
                        Bucket=self.bucket_name,
                        CreateBucketConfiguration={"LocationConstraint": self.region_name}
                    )
                else:
                    client.create_bucket(Bucket=self.bucket_name)
            except Exception as e:
                logger.warning(f"Could not automatically create bucket '{self.bucket_name}': {e}")

    def put(
        self,
        storage_key: str,
        data: Union[bytes, BinaryIO],
        content_type: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        if user_id:
            assert_user_storage_key(user_id, storage_key)

        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        extra_args: Dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        if isinstance(data, (bytes, bytearray)):
            body = data
            size = len(data)
        elif hasattr(data, "read"):
            body = data.read()
            size = len(body)
        else:
            raise ValueError(f"Unsupported data type for S3 storage put: {type(data)}")

        client.put_object(
            Bucket=self.bucket_name,
            Key=norm_key,
            Body=body,
            **extra_args
        )

        return {
            "storage_backend": self.backend_type,
            "storage_key": norm_key,
            "key": norm_key,
            "storage_size": size,
            "size": size,
            "content_type": content_type or "application/octet-stream"
        }

    def open(self, storage_key: str) -> BinaryIO:
        data = self.get_bytes(storage_key)
        return io.BytesIO(data)

    def get_bytes(self, storage_key: str) -> bytes:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            resp = client.get_object(Bucket=self.bucket_name, Key=norm_key)
            return resp["Body"].read()
        except Exception as e:
            raise StorageObjectNotFoundError(f"S3 error retrieving '{norm_key}': {e}")

    def exists(self, storage_key: str) -> bool:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            client.head_object(Bucket=self.bucket_name, Key=norm_key)
            return True
        except Exception:
            return False

    def delete(self, storage_key: str) -> bool:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            client.delete_object(Bucket=self.bucket_name, Key=norm_key)
            return True
        except Exception as e:
            logger.warning(f"Error deleting object '{norm_key}' from S3: {e}")
            return False

    def get_size(self, storage_key: str) -> int:
        meta = self.get_metadata(storage_key)
        return meta.get("storage_size", 0)

    def get_metadata(self, storage_key: str) -> Dict[str, Any]:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            head = client.head_object(Bucket=self.bucket_name, Key=norm_key)
            return {
                "storage_backend": self.backend_type,
                "storage_key": norm_key,
                "storage_size": head.get("ContentLength", 0),
                "content_type": head.get("ContentType", "application/octet-stream"),
                "last_modified": head.get("LastModified")
            }
        except Exception as e:
            raise StorageObjectNotFoundError(f"Object '{norm_key}' metadata not found: {e}")

    def generate_download_response(
        self,
        storage_key: str,
        filename: str,
        mime_type: Optional[str] = None
    ) -> Response:
        data = self.get_bytes(storage_key)
        return Response(
            content=data,
            media_type=mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    def generate_signed_url(self, storage_key: str, expires_in: int = 3600) -> Optional[str]:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": norm_key},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.warning(f"Could not generate presigned URL for '{norm_key}': {e}")
            return None


def get_storage_backend(backend_type: Optional[str] = None) -> StorageBackend:
    """
    Factory function returning the configured StorageBackend instance.
    Checks SAKURA_STORAGE_BACKEND ('s3' or 'local'). Defaults to 'local'.
    """
    chosen = (backend_type or os.getenv("SAKURA_STORAGE_BACKEND", "local")).strip().lower()
    if chosen == "s3":
        return S3CompatibleStorage()
    return LocalFilesystemStorage()
