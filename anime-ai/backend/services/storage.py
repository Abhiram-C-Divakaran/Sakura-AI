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


class StoragePermissionError(StorageSecurityError):
    """Raised when storage access is denied due to permissions."""
    pass


class StorageAuthenticationError(StorageSecurityError):
    """Raised when storage credentials or authentication fail."""
    pass


class StorageTimeoutError(Exception):
    """Raised when storage backend connection or read times out."""
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


def resolve_legacy_local_path(storage_path: str, allowed_root: Optional[str] = None) -> str:
    """
    Safely resolves legacy storage paths with strict traversal containment.
    Verifies path exists within allowed_root (defaults to SAKURA_STORAGE_ROOT or ./uploaded_documents).
    Rejects null bytes, symlink escapes, drive escapes, and parent traversals.
    """
    if not storage_path or not isinstance(storage_path, str):
        raise StorageSecurityError("Invalid legacy storage path.")

    if "\0" in storage_path:
        raise StorageSecurityError(f"Null byte detected in legacy storage path: '{storage_path}'")

    root = allowed_root or os.getenv("SAKURA_STORAGE_ROOT", "./uploaded_documents")
    canonical_root = os.path.realpath(os.path.abspath(root))
    canonical_target = os.path.realpath(os.path.abspath(storage_path))

    try:
        common = os.path.commonpath([canonical_root, canonical_target])
    except ValueError:
        raise StorageSecurityError(f"Path traversal detected: '{storage_path}' escapes storage drive boundary.")

    if common != canonical_root or (canonical_target != canonical_root and not canonical_target.startswith(canonical_root + os.sep)):
        raise StorageSecurityError(
            f"Storage path traversal detected: legacy path '{storage_path}' escapes allowed root '{canonical_root}'"
        )

    return canonical_target


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
    def read_prefix(self, storage_key: str, max_bytes: int) -> bytes:
        """Reads up to max_bytes from the beginning of the object."""
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

    def read_prefix(self, storage_key: str, max_bytes: int) -> bytes:
        file_path = self._resolve_key_path(storage_key)
        if not os.path.exists(file_path):
            raise StorageObjectNotFoundError(f"Storage object '{storage_key}' not found at {file_path}")
        with open(file_path, "rb") as f:
            return f.read(max(0, max_bytes))

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
            stream = io.BytesIO(data)
            size = len(data)
        elif hasattr(data, "read"):
            stream = data
            # Determine size incrementally if possible
            if hasattr(data, "seek") and hasattr(data, "tell"):
                curr = data.tell()
                data.seek(0, io.SEEK_END)
                size = data.tell() - curr
                data.seek(curr)
            else:
                size = None
        else:
            raise ValueError(f"Unsupported data type for S3 storage put: {type(data)}")

        # Stream directly without buffering full object in RAM
        client.upload_fileobj(
            Fileobj=stream,
            Bucket=self.bucket_name,
            Key=norm_key,
            ExtraArgs=extra_args
        )

        if size is None:
            size = self.get_size(norm_key)

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
            err_str = str(e)
            if "NoSuchKey" in err_str or "404" in err_str:
                raise StorageObjectNotFoundError(f"S3 error retrieving '{norm_key}': {e}")
            if "AccessDenied" in err_str or "403" in err_str:
                raise StoragePermissionError(f"Access denied to S3 object '{norm_key}': {e}")
            if "Timeout" in err_str or "ConnectTimeoutError" in err_str:
                raise StorageTimeoutError(f"S3 timeout reading '{norm_key}': {e}")
            raise StorageObjectNotFoundError(f"S3 error retrieving '{norm_key}': {e}")

    def read_prefix(self, storage_key: str, max_bytes: int) -> bytes:
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            range_header = f"bytes=0-{max(0, max_bytes - 1)}"
            resp = client.get_object(Bucket=self.bucket_name, Key=norm_key, Range=range_header)
            return resp["Body"].read()
        except Exception as e:
            err_str = str(e)
            if "NoSuchKey" in err_str or "404" in err_str:
                raise StorageObjectNotFoundError(f"Object '{norm_key}' not found in S3: {e}")
            if "AccessDenied" in err_str or "403" in err_str:
                raise StoragePermissionError(f"Access denied to S3 object '{norm_key}': {e}")
            if "Timeout" in err_str or "ConnectTimeoutError" in err_str:
                raise StorageTimeoutError(f"S3 timeout reading '{norm_key}': {e}")
            raise

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
        """Streams stored object in bounded chunks to avoid buffering large files in RAM."""
        from starlette.responses import StreamingResponse
        client = self._get_client()
        norm_key = storage_key.replace("\\", "/").lstrip("/")
        try:
            s3_obj = client.get_object(Bucket=self.bucket_name, Key=norm_key)
            body = s3_obj["Body"]

            def chunk_generator():
                for chunk in body.iter_chunks(chunk_size=64 * 1024):
                    yield chunk

            return StreamingResponse(
                chunk_generator(),
                media_type=mime_type or s3_obj.get("ContentType", "application/octet-stream"),
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )
        except Exception as e:
            raise StorageObjectNotFoundError(f"Object '{norm_key}' download error: {e}")

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


def check_storage_readiness(is_production: Optional[bool] = None) -> Dict[str, Any]:
    """
    Validates storage backend readiness for /readiness probe without leaking credentials.
    In production:
    - S3: verifies authentication & head_bucket probe within bounded timeout.
    - Local: verifies root directory exists, is writable, and passes durable non-ephemeral policy.
    """
    if is_production is None:
        env = os.getenv("ENVIRONMENT", "development").lower()
        is_production = env in ("production", "prod")

    backend_type = (os.getenv("SAKURA_STORAGE_BACKEND") or "local").strip().lower()
    if backend_type == "s3":
        bucket = os.getenv("SAKURA_STORAGE_BUCKET") or "sakura-library"
        endpoint = os.getenv("SAKURA_STORAGE_ENDPOINT")
        access_key = os.getenv("SAKURA_STORAGE_ACCESS_KEY")
        secret_key = os.getenv("SAKURA_STORAGE_SECRET_KEY")

        configured = bool(bucket and (access_key or not is_production))
        storage = S3CompatibleStorage(bucket_name=bucket, endpoint_url=endpoint)
        try:
            client = storage._get_client()
            client.head_bucket(Bucket=bucket)
            return {
                "backend": "s3",
                "configured": True,
                "healthy": True,
                "status": "OPERATIONAL",
                "bucket": bucket,
                "reason": None
            }
        except Exception as e:
            raw_err = str(e)
            if access_key and access_key in raw_err:
                raw_err = raw_err.replace(access_key, "[REDACTED]")
            if secret_key and secret_key in raw_err:
                raw_err = raw_err.replace(secret_key, "[REDACTED]")
            return {
                "backend": "s3",
                "configured": configured,
                "healthy": not is_production if not configured else False,
                "status": "DEGRADED" if not is_production else "UNAVAILABLE",
                "bucket": bucket,
                "reason": f"S3 probe failed: {raw_err}"
            }
    else:
        root_dir = os.path.realpath(os.path.abspath(os.getenv("SAKURA_STORAGE_ROOT", "./uploaded_documents")))
        root_exists = os.path.exists(root_dir)
        writable = os.access(root_dir, os.W_OK) if root_exists else False
        if not root_exists:
            try:
                os.makedirs(root_dir, exist_ok=True)
                writable = os.access(root_dir, os.W_OK)
                root_exists = True
            except Exception:
                writable = False

        # Production policy: in production, local storage must use a dedicated durable mount point (not ./uploaded_documents)
        is_ephemeral = root_dir.endswith("uploaded_documents") or not os.path.isabs(os.getenv("SAKURA_STORAGE_ROOT", "./uploaded_documents"))
        if is_production and is_ephemeral:
            return {
                "backend": "local",
                "configured": True,
                "healthy": False,
                "status": "UNAVAILABLE",
                "root_dir": root_dir,
                "reason": "Production local storage requires durable non-ephemeral root directory (/data/library)."
            }

        healthy = root_exists and writable
        return {
            "backend": "local",
            "configured": True,
            "healthy": healthy,
            "status": "OPERATIONAL" if healthy else "UNAVAILABLE",
            "root_dir": root_dir,
            "reason": None if healthy else "Storage root directory is not writable"
        }
