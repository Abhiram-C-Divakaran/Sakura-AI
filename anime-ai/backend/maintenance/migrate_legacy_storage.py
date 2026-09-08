"""
Sakura AI — Legacy Storage Migration Utility
Usage: python -m maintenance.migrate_legacy_storage [--dry-run] [--remove-source] [--batch-size 100]

Migrates legacy flat-file documents and generated images to canonical storage keys
in the configured StorageBackend with checksum, size verification, and idempotency.
"""

import os
import sys
import uuid
import hashlib
import logging
import argparse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from database.db import get_db_context
from database.models import Document, GeneratedImage
from services.storage import (
    get_storage_backend,
    build_document_storage_key,
    build_image_storage_key,
    resolve_legacy_local_path,
    StorageSecurityError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sakura.maintenance.storage")


def compute_file_sha256(file_path: str) -> str:
    """Computes SHA-256 hash of a local file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 hash of binary data."""
    return hashlib.sha256(data).hexdigest()


def migrate_storage(
    dry_run: bool = False,
    remove_source: bool = False,
    batch_size: int = 100
) -> Dict[str, Any]:
    """
    Executes idempotent, resumable migration of legacy storage records to active StorageBackend.
    """
    storage = get_storage_backend()
    logger.info(f"Starting legacy storage migration to backend: '{storage.backend_type}' (dry_run={dry_run})...")

    summary = {
        "storage_backend": storage.backend_type,
        "dry_run": dry_run,
        "remove_source": remove_source,
        "total_scanned": 0,
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": []
    }

    with get_db_context() as db:
        # 1. Migrate Documents
        docs = db.query(Document).filter(
            (Document.storage_key.is_(None)) |
            (Document.storage_backend != storage.backend_type)
        ).limit(batch_size).all()

        summary["total_scanned"] += len(docs)

        for doc in docs:
            doc_id = str(doc.id)
            canonical_key = build_document_storage_key(doc.user_id, doc.id, doc.filename)

            # Check if source file exists on disk
            source_path = doc.storage_path
            if not source_path or not os.path.exists(source_path):
                # Try resolving relative to legacy storage root
                legacy_root = os.getenv("SAKURA_STORAGE_ROOT", "./uploaded_documents")
                candidate = os.path.join(legacy_root, os.path.basename(source_path or doc.filename))
                if os.path.exists(candidate):
                    source_path = candidate
                else:
                    logger.warning(f"Document {doc_id}: Source file not found at '{doc.storage_path}'.")
                    summary["failed"] += 1
                    summary["errors"].append({
                        "id": doc_id,
                        "type": "document",
                        "error": f"Source file missing from disk: '{doc.storage_path}'"
                    })
                    continue

            try:
                safe_source = resolve_legacy_local_path(source_path)
            except StorageSecurityError as e:
                logger.error(f"Document {doc_id}: Path security violation on '{source_path}': {e}")
                summary["failed"] += 1
                summary["errors"].append({"id": doc_id, "type": "document", "error": str(e)})
                continue

            source_size = os.path.getsize(safe_source)
            source_hash = compute_file_sha256(safe_source)

            # Check destination in storage backend
            dest_exists = storage.exists(canonical_key)
            if dest_exists and storage.get_size(canonical_key) == source_size:
                logger.info(f"Document {doc_id}: Already present in destination storage '{canonical_key}'.")
            elif not dry_run:
                try:
                    with open(safe_source, "rb") as f:
                        storage.put(
                            storage_key=canonical_key,
                            data=f,
                            content_type=doc.mime_type,
                            user_id=doc.user_id
                        )
                    dest_size = storage.get_size(canonical_key)
                    if dest_size != source_size:
                        raise ValueError(f"Size mismatch after upload: expected {source_size}, got {dest_size}")
                except Exception as ex:
                    logger.error(f"Document {doc_id}: Failed to upload to storage: {ex}")
                    summary["failed"] += 1
                    summary["errors"].append({"id": doc_id, "type": "document", "error": str(ex)})
                    continue

            if not dry_run:
                # Checksum verification before modifying DB or deleting source
                dest_bytes = storage.get_bytes(canonical_key)
                dest_hash = compute_bytes_sha256(dest_bytes)
                if dest_hash != source_hash:
                    logger.error(f"Document {doc_id}: SHA-256 mismatch between source ({source_hash}) and destination ({dest_hash}). Skipping deletion.")
                    summary["failed"] += 1
                    summary["errors"].append({
                        "id": doc_id,
                        "type": "document",
                        "error": f"Checksum mismatch: source={source_hash}, dest={dest_hash}"
                    })
                    continue

                doc.storage_key = canonical_key
                doc.storage_backend = storage.backend_type
                doc.storage_size = source_size
                db.commit()

                if remove_source and os.path.exists(safe_source):
                    try:
                        os.remove(safe_source)
                        logger.info(f"Document {doc_id}: Verified SHA256 matches ({dest_hash[:8]}). Removed legacy source file '{safe_source}'.")
                    except Exception as rm_err:
                        logger.warning(f"Document {doc_id}: Could not remove legacy source file: {rm_err}")

            summary["migrated"] += 1

        # 2. Migrate GeneratedImages
        images = db.query(GeneratedImage).filter(
            (GeneratedImage.storage_key.is_(None)) |
            (GeneratedImage.storage_backend != storage.backend_type)
        ).limit(batch_size).all()

        summary["total_scanned"] += len(images)

        for img in images:
            img_id = str(img.id)
            canonical_key = build_image_storage_key(img.user_id, img.id, "png")
            source_path = img.storage_path

            if not source_path or not os.path.exists(source_path):
                summary["skipped"] += 1
                continue

            try:
                safe_source = resolve_legacy_local_path(source_path)
            except StorageSecurityError as e:
                summary["failed"] += 1
                summary["errors"].append({"id": img_id, "type": "image", "error": str(e)})
                continue

            source_size = os.path.getsize(safe_source)
            source_hash = compute_file_sha256(safe_source)

            if not storage.exists(canonical_key) and not dry_run:
                try:
                    with open(safe_source, "rb") as f:
                        storage.put(
                            storage_key=canonical_key,
                            data=f,
                            content_type="image/png",
                            user_id=img.user_id
                        )
                except Exception as ex:
                    summary["failed"] += 1
                    summary["errors"].append({"id": img_id, "type": "image", "error": str(ex)})
                    continue

            if not dry_run:
                dest_bytes = storage.get_bytes(canonical_key)
                dest_hash = compute_bytes_sha256(dest_bytes)
                if dest_hash != source_hash:
                    logger.error(f"Image {img_id}: SHA-256 mismatch between source and destination. Skipping deletion.")
                    summary["failed"] += 1
                    summary["errors"].append({"id": img_id, "type": "image", "error": "Checksum mismatch"})
                    continue

                img.storage_key = canonical_key
                img.storage_backend = storage.backend_type
                img.storage_size = source_size
                db.commit()

                if remove_source and os.path.exists(safe_source):
                    try:
                        os.remove(safe_source)
                    except Exception:
                        pass

            summary["migrated"] += 1

    logger.info(f"Migration completed. Summary: {summary}")
    return summary


def main():
    import json
    parser = argparse.ArgumentParser(description="Sakura AI Legacy Storage Migration")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without modifying files or DB")
    parser.add_argument("--remove-source", action="store_true", help="Remove legacy local files after verified migration")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of records to migrate per batch")
    parser.add_argument("--report", type=str, default=None, help="File path to save JSON migration report")
    args = parser.parse_args()

    res = migrate_storage(
        dry_run=args.dry_run,
        remove_source=args.remove_source,
        batch_size=args.batch_size
    )

    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2)
            logger.info(f"Migration report written to {args.report}")
        except Exception as e:
            logger.error(f"Failed to write report to {args.report}: {e}")

    if res["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
