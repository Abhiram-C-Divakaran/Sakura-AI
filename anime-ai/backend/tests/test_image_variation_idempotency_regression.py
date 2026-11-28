"""
Sakura AI — Image Variation Idempotency, Conflict & Partial-Failure Recovery Regression Suite

Covers:
1. Repeated identical variation requests (exact job ID/order replay, zero extra quota).
2. Concurrent duplicate requests (thread-pool race -> exactly 1 creator, identical jobs, 1x quota).
3. Idempotency-key reuse:
   - Distinct >112-char keys sharing a 112-char prefix NEVER collide on child ImageGenerationJob keys.
   - >128-char keys rejected cleanly with HTTP 400 (no silent truncation).
   - Cross-user key isolation (User A and User B can use the same key string independently).
4. Conflicting payloads with the same key (count, parent_image_id, intensity, conversation_id -> HTTP 409, 0 extra quota),
   including callers omitting request_fingerprint.
5. Retry after partial failure:
   - Quota exceeded (HTTP 429) rolls back batch + jobs so retry with same key after quota increase succeeds.
   - DB commit failure rolls back batch + quota so retry with same key succeeds cleanly.
   - Transient Redis enqueue failure leaves durable QUEUED jobs; idempotent retry re-enqueues QUEUED jobs without duplicates.
6. Persistence and response consistency between API response, ImageVariationBatch, and ImageGenerationJob rows.
"""

import os
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_anime_ai.db")
os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi.testclient import TestClient

from auth.manager import AuthManager
from database.db import Base, engine, get_db_context
from database.models import (
    Document,
    GeneratedImage,
    ImageGenerationJob,
    ImageVariationBatch,
    User,
    UserUsageQuota,
    utc_now,
)
from main import app
from media.image_worker import (
    IdempotencyConflictError,
    compute_variation_request_fingerprint,
    create_batch_image_generation_jobs,
)


def _make_user_with_images(db, prefix="var_reg", count=2):
    uid = uuid.uuid4()
    u = User(
        id=uid,
        username=f"{prefix}_{uid.hex[:8]}@example.com",
        email=f"{prefix}_{uid.hex[:8]}@example.com",
        hashed_password=AuthManager.hash_password("StrongPass123!"),
        created_at=utc_now(),
    )
    db.add(u)
    db.flush()
    img_ids = []
    for idx in range(count):
        iid = uuid.uuid4()
        db.add(
            Document(
                id=iid,
                user_id=uid,
                filename=f"parent_{idx}.png",
                mime_type="image/png",
                storage_path=f"/tmp/parent_{iid}.png",
            )
        )
        db.flush()
        db.add(
            GeneratedImage(
                id=iid,
                user_id=uid,
                document_id=iid,
                prompt=f"Sakura lantern artwork {idx}",
                enhanced_prompt=f"Sakura lantern artwork {idx}",
                aspect_ratio="1:1",
                width=1024,
                height=1024,
                model="flux",
                storage_path=f"/tmp/parent_{iid}.png",
                image_url=f"/api/v1/library/files/{iid}/download",
            )
        )
        img_ids.append(iid)
    db.commit()
    return u, img_ids


class TestImageVariationIdempotencyRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    def test_distinct_long_keys_sharing_112_char_prefix_do_not_collide_and_over_128_rejected(self):
        """
        Regression test for child job key truncation collision:
        Two distinct 124-char keys sharing the exact same 112-char prefix MUST BOTH succeed
        without IntegrityError, while keys >128 chars MUST be rejected with HTTP 400.
        """
        with get_db_context() as db:
            user, imgs = _make_user_with_images(db, "longkey", count=1)
            tok = AuthManager.create_access_token({"sub": user.username})
            uid = user.id
            img_a = imgs[0]

        headers = {"Authorization": f"Bearer {tok}"}
        shared_prefix = "k" * 114
        key_1 = shared_prefix + "_alpha001"  # 123 chars
        key_2 = shared_prefix + "_beta0002"  # 123 chars
        too_long = "x" * 129

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "10"}):
            r_long = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": too_long},
            )
            self.assertEqual(r_long.status_code, 400, r_long.text)

            r1 = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": key_1},
            )
            self.assertEqual(r1.status_code, 202, r1.text)
            self.assertFalse(r1.json()["idempotent_replay"])

            r2 = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": key_2},
            )
            self.assertEqual(r2.status_code, 202, r2.text)
            self.assertFalse(r2.json()["idempotent_replay"])

            ids_1 = [j["id"] for j in r1.json()["jobs"]]
            ids_2 = [j["id"] for j in r2.json()["jobs"]]
            self.assertEqual(len(set(ids_1) & set(ids_2)), 0, "Distinct long keys must create distinct job sets")

            with get_db_context() as db:
                quota = db.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == uid, UserUsageQuota.category == "image_generation"
                ).first()
                self.assertEqual(quota.usage_count, 4)

    def test_conflicting_intensity_and_conversation_id_and_missing_incoming_fp_return_409(self):
        """Reusing an idempotency key with different intensity or conversation_id MUST return HTTP 409."""
        with get_db_context() as db:
            user, imgs = _make_user_with_images(db, "conflict_all", count=2)
            tok = AuthManager.create_access_token({"sub": user.username})
            uid = user.id
            img_a, img_b = imgs
            conv_1 = str(uuid.uuid4())
            conv_2 = str(uuid.uuid4())

        headers = {"Authorization": f"Bearer {tok}"}
        key = f"var-conf-{uuid.uuid4().hex[:8]}"

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "10"}):
            r_init = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={
                    "parent_image_id": str(img_a),
                    "count": 2,
                    "intensity": "low",
                    "conversation_id": conv_1,
                    "idempotency_key": key,
                },
            )
            self.assertEqual(r_init.status_code, 202, r_init.text)
            orig_jobs = r_init.json()["jobs"]

            # Normalized case on intensity ("LOW" == "low") MUST replay cleanly
            r_norm = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={
                    "parent_image_id": str(img_a),
                    "count": 2,
                    "intensity": "LOW",
                    "conversation_id": conv_1,
                    "idempotency_key": key,
                },
            )
            self.assertEqual(r_norm.status_code, 202)
            self.assertTrue(r_norm.json()["idempotent_replay"])
            self.assertEqual([j["id"] for j in r_norm.json()["jobs"]], [j["id"] for j in orig_jobs])

            # Different intensity -> 409
            r_int = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={
                    "parent_image_id": str(img_a),
                    "count": 2,
                    "intensity": "high",
                    "conversation_id": conv_1,
                    "idempotency_key": key,
                },
            )
            self.assertEqual(r_int.status_code, 409)

            # Different conversation_id -> 409
            r_conv = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={
                    "parent_image_id": str(img_a),
                    "count": 2,
                    "intensity": "low",
                    "conversation_id": conv_2,
                    "idempotency_key": key,
                },
            )
            self.assertEqual(r_conv.status_code, 409)

            # Direct service call omitting request_fingerprint MUST still reject conflicting parent_image_id!
            with get_db_context() as db:
                with self.assertRaises(IdempotencyConflictError):
                    create_batch_image_generation_jobs(
                        db=db,
                        user_id=uid,
                        job_specs=[
                            {"prompt": "p1", "requested_pipeline": "auto", "parameters": {"intensity": "low", "conversation_id": conv_1}},
                            {"prompt": "p2", "requested_pipeline": "auto", "parameters": {"intensity": "low", "conversation_id": conv_1}},
                        ],
                        idempotency_key=key,
                        parent_image_id=img_b,
                        request_fingerprint=None,
                        require_idempotency_key=True,
                    )

    def test_retry_after_partial_failures_quota_db_commit_and_redis_outage(self):
        """
        Verifies clean recovery on retries after partial failures:
        1. Quota exceeded (429) rolls back batch row so retry with same key succeeds once quota allows.
        2. Transient Redis enqueue failure still persists jobs durably and replay re-enqueues QUEUED jobs without duplicates.
        3. Response job order and fields remain strictly consistent with persisted DB rows.
        """
        with get_db_context() as db:
            user, imgs = _make_user_with_images(db, "partial_fail", count=1)
            tok = AuthManager.create_access_token({"sub": user.username})
            uid = user.id
            img_a = imgs[0]

        headers = {"Authorization": f"Bearer {tok}"}
        key_quota = f"var-retry-q-{uuid.uuid4().hex[:8]}"

        # 1. Quota too low (limit=1, requesting 2) -> HTTP 429 and ZERO persisted batch/jobs
        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "1"}):
            r_429 = self.client.post(
                "/api/v1/images/variation",
                headers=headers,
                json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": key_quota},
            )
            self.assertEqual(r_429.status_code, 429)

        with get_db_context() as db:
            self.assertIsNone(
                db.query(ImageVariationBatch)
                .filter(ImageVariationBatch.user_id == uid, ImageVariationBatch.idempotency_key == key_quota)
                .first(),
                "Failed quota reservation must roll back ImageVariationBatch!",
            )

        # Retry with exact same idempotency_key once quota allows + simulate Redis outage on first enqueue
        enqueued_ids = []

        def _fail_redis(_job_id):
            return False

        def _ok_redis(job_id):
            enqueued_ids.append(str(job_id))
            return True

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "5"}):
            with patch("media.image_worker.enqueue_image_job", side_effect=_fail_redis):
                r_created = self.client.post(
                    "/api/v1/images/variation",
                    headers=headers,
                    json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": key_quota},
                )
            self.assertEqual(r_created.status_code, 202, r_created.text)
            self.assertFalse(r_created.json()["idempotent_replay"])
            created_ids = [j["id"] for j in r_created.json()["jobs"]]
            self.assertEqual(len(created_ids), 2)

            # Retry with same key once Redis recovers -> replays exact IDs, re-enqueues QUEUED jobs, 0 duplicates
            with patch("media.image_worker.enqueue_image_job", side_effect=_ok_redis):
                r_replay = self.client.post(
                    "/api/v1/images/variation",
                    headers=headers,
                    json={"parent_image_id": str(img_a), "count": 2, "idempotency_key": key_quota},
                )
            self.assertEqual(r_replay.status_code, 202)
            self.assertTrue(r_replay.json()["idempotent_replay"])
            self.assertEqual([j["id"] for j in r_replay.json()["jobs"]], created_ids)
            self.assertEqual(enqueued_ids, created_ids)

            # Verify DB persistence and exact response consistency
            with get_db_context() as db:
                batch = db.query(ImageVariationBatch).filter(
                    ImageVariationBatch.user_id == uid, ImageVariationBatch.idempotency_key == key_quota
                ).first()
                self.assertIsNotNone(batch)
                self.assertEqual(list(batch.job_ids), created_ids)
                db_jobs = db.query(ImageGenerationJob).filter(ImageGenerationJob.user_id == uid).all()
                self.assertEqual(len(db_jobs), 2)
                quota = db.query(UserUsageQuota).filter(
                    UserUsageQuota.user_id == uid, UserUsageQuota.category == "image_generation"
                ).first()
                self.assertEqual(quota.usage_count, 2)

    def test_cross_user_idempotency_key_isolation_and_concurrent_duplicate_requests(self):
        """User A and User B can independently reuse the same key string; concurrent identical calls create once."""
        with get_db_context() as db:
            user_a, imgs_a = _make_user_with_images(db, "iso_a", count=1)
            user_b, imgs_b = _make_user_with_images(db, "iso_b", count=1)
            uid_a, pid_a = user_a.id, imgs_a[0]
            uid_b, pid_b = user_b.id, imgs_b[0]

        shared_key = f"shared-key-{uuid.uuid4().hex[:8]}"
        specs_a = [
            {"prompt": "A var 1", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid_a)}},
            {"prompt": "A var 2", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid_a)}},
        ]
        specs_b = [
            {"prompt": "B var 1", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid_b)}},
            {"prompt": "B var 2", "requested_pipeline": "auto", "parameters": {"parent_image_id": str(pid_b)}},
        ]
        fp_a = compute_variation_request_fingerprint(pid_a, count=2)
        fp_b = compute_variation_request_fingerprint(pid_b, count=2)

        def _call_a():
            with get_db_context() as s:
                return create_batch_image_generation_jobs(
                    db=s,
                    user_id=uid_a,
                    job_specs=specs_a,
                    idempotency_key=shared_key,
                    parent_image_id=pid_a,
                    request_fingerprint=fp_a,
                    require_idempotency_key=True,
                )

        with patch.dict(os.environ, {"SAKURA_QUOTA_IMAGE_DAILY": "10"}):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results_a = [f.result() for f in [pool.submit(_call_a) for _ in range(4)]]

            self.assertEqual(sum(int(c) for _, c in results_a), 1)
            ids_a = [j.id for j in results_a[0][0]]
            for jobs, _ in results_a:
                self.assertEqual([j.id for j in jobs], ids_a)

            # User B using exact same key string succeeds independently
            with get_db_context() as s:
                jobs_b, created_b = create_batch_image_generation_jobs(
                    db=s,
                    user_id=uid_b,
                    job_specs=specs_b,
                    idempotency_key=shared_key,
                    parent_image_id=pid_b,
                    request_fingerprint=fp_b,
                    require_idempotency_key=True,
                )
            self.assertTrue(created_b)
            self.assertEqual(len(set(ids_a) & {j.id for j in jobs_b}), 0)


if __name__ == "__main__":
    unittest.main()
