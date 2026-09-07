import os
import sys
import uuid
import unittest
from datetime import timedelta

# Adjust import path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient
from main import app
from database.db import Base, engine, get_db_context
from database.models import User, Conversation, Message, ConversationShare, utc_now
from auth.manager import AuthManager


class TestShareExpiration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

        cls.user_id = uuid.uuid4()
        cls.username = f"share_user_{cls.user_id.hex[:6]}"
        with get_db_context() as db:
            user = User(
                id=cls.user_id,
                username=cls.username,
                hashed_password=AuthManager.hash_password("password123")
            )
            db.add(user)
            db.commit()

        cls.token = AuthManager.create_access_token({"sub": cls.username})
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_share_creation_with_expiration_and_revocation(self):
        # 1. Create a conversation and message
        conv_id = uuid.uuid4()
        with get_db_context() as db:
            conv = Conversation(
                id=conv_id,
                user_id=self.user_id,
                title="Shared Conversation Title"
            )
            db.add(conv)
            msg = Message(
                id=uuid.uuid4(),
                conversation_id=conv_id,
                role="user",
                content="Hello Sakura!"
            )
            db.add(msg)
            db.commit()

        # 2. Share with 1d expiration
        res = self.client.post(f"/api/v1/conversations/{conv_id}/share?expires_in=1d", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        share_data = res.json()
        share_token = share_data["share_token"]
        self.assertIsNotNone(share_data.get("expires_at"))

        # 3. Retrieve public shared conversation -> succeeds
        get_res = self.client.get(f"/api/v1/share/{share_token}")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.json()
        self.assertEqual(get_data["title"], "Shared Conversation Title")
        self.assertEqual(len(get_data["messages"]), 1)

        # 4. Simulate expiration by moving expires_at to the past
        with get_db_context() as db:
            share = db.query(ConversationShare).filter(ConversationShare.share_token == share_token).first()
            share.expires_at = utc_now() - timedelta(hours=2)
            db.commit()

        # Retrieve expired conversation -> 404
        expired_res = self.client.get(f"/api/v1/share/{share_token}")
        self.assertEqual(expired_res.status_code, 404)

        # 5. Reactivate share and then revoke it
        with get_db_context() as db:
            share = db.query(ConversationShare).filter(ConversationShare.share_token == share_token).first()
            share.expires_at = utc_now() + timedelta(days=1)
            db.commit()

        # Lookup succeeds after reactivation
        active_res = self.client.get(f"/api/v1/share/{share_token}")
        self.assertEqual(active_res.status_code, 200)

        # Revoke share via DELETE /api/v1/share/{token}
        rev_res = self.client.delete(f"/api/v1/share/{share_token}", headers=self.headers)
        self.assertEqual(rev_res.status_code, 200)
        self.assertEqual(rev_res.json()["status"], "revoked")

        # Verify revoked share lookup returns 404
        after_rev_res = self.client.get(f"/api/v1/share/{share_token}")
        self.assertEqual(after_rev_res.status_code, 404)

        # Verify DB row has is_active == False and revoked_at is set
        with get_db_context() as db:
            rev_share = db.query(ConversationShare).filter(ConversationShare.share_token == share_token).first()
            self.assertFalse(rev_share.is_active)
            self.assertIsNotNone(rev_share.revoked_at)


if __name__ == "__main__":
    unittest.main()
