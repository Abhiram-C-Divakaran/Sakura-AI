"""
Unit tests for single-use WebSocket ticket authentication.
Verifies issuance, CAS consumption, expiration enforcement, and replay prevention.
"""

import time
import uuid
import unittest
from datetime import datetime, timedelta, timezone

from database.db import get_db_context, Base, engine
from database.models import User, WebSocketTicket, utc_now
from auth.manager import AuthManager


class TestWebSocketTicket(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        with get_db_context() as db:
            # Create a test user
            self.user_id = uuid.uuid4()
            self.user = User(
                id=self.user_id,
                username=f"test_ws_user_{uuid.uuid4().hex[:8]}",
                hashed_password="fake_hash"
            )
            db.add(self.user)
            db.commit()

    def test_issue_and_consume_ticket_success(self):
        """Ticket can be issued and consumed once for the correct user."""
        with get_db_context() as db:
            result = AuthManager.issue_ws_ticket(user_id=self.user_id, ttl_seconds=60, db=db)
            self.assertIn("ticket", result)
            self.assertTrue(result["ticket"].startswith("wst_"))
            ticket_str = result["ticket"]

            # Consume the ticket
            consumed_user_id = AuthManager.consume_ws_ticket(ticket_str, db=db)
            self.assertEqual(consumed_user_id, self.user_id)

    def test_single_use_replay_prevention(self):
        """A ticket cannot be consumed more than once (single-use semantics)."""
        with get_db_context() as db:
            result = AuthManager.issue_ws_ticket(user_id=self.user_id, ttl_seconds=60, db=db)
            ticket_str = result["ticket"]

            # First consumption succeeds
            first_user_id = AuthManager.consume_ws_ticket(ticket_str, db=db)
            self.assertEqual(first_user_id, self.user_id)

            # Second consumption must return None
            second_user_id = AuthManager.consume_ws_ticket(ticket_str, db=db)
            self.assertIsNone(second_user_id)

            # Third consumption must also return None
            third_user_id = AuthManager.consume_ws_ticket(ticket_str, db=db)
            self.assertIsNone(third_user_id)

    def test_expired_ticket_rejected(self):
        """An expired ticket cannot be consumed."""
        with get_db_context() as db:
            # Issue ticket that expires immediately in the past
            ticket_str = f"wst_{uuid.uuid4().hex}"
            now = utc_now()
            expired_ticket = WebSocketTicket(
                ticket=ticket_str,
                user_id=self.user_id,
                created_at=now - timedelta(seconds=120),
                expires_at=now - timedelta(seconds=10),
                consumed_at=None
            )
            db.add(expired_ticket)
            db.commit()

            # Attempt consumption
            result = AuthManager.consume_ws_ticket(ticket_str, db=db)
            self.assertIsNone(result)

    def test_malformed_and_nonexistent_ticket_rejected(self):
        """Invalid or non-existent tickets are safely rejected without errors."""
        with get_db_context() as db:
            self.assertIsNone(AuthManager.consume_ws_ticket("", db=db))
            self.assertIsNone(AuthManager.consume_ws_ticket("invalid_prefix_token", db=db))
            self.assertIsNone(AuthManager.consume_ws_ticket(None, db=db))
            self.assertIsNone(AuthManager.consume_ws_ticket(f"wst_{uuid.uuid4().hex}_nonexistent", db=db))


if __name__ == "__main__":
    unittest.main()
