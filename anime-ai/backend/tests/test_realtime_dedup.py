import os
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"

from realtime.manager import RealtimeManager


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent_messages = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent_messages.append(data)


class TestRealtimeManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager1 = RealtimeManager()
        self.manager2 = RealtimeManager()

    async def asyncTearDown(self):
        await self.manager1.shutdown()
        await self.manager2.shutdown()

    async def test_local_subscriber_gets_exactly_one_event_when_published(self):
        """When manager1 sends to a local user, the local websocket gets exactly 1 event."""
        ws = FakeWebSocket()
        user_id = "user_123"
        await self.manager1.connect(user_id, ws)

        # Mock Redis so publish succeeds
        mock_redis = AsyncMock()
        self.manager1._redis_client = mock_redis

        await self.manager1.send_to_user(user_id, {"type": "test_event", "payload": "hello"})

        self.assertEqual(len(ws.sent_messages), 1)
        event = ws.sent_messages[0]
        self.assertEqual(event["type"], "test_event")
        self.assertEqual(event["payload"], "hello")
        self.assertIn("event_id", event)
        self.assertEqual(event["origin_worker_id"], self.manager1.worker_id)

    async def test_dedup_discards_own_event_from_redis_pubsub(self):
        """When manager1 receives its own published message from Redis pubsub, it discards it."""
        ws = FakeWebSocket()
        user_id = "user_123"
        await self.manager1.connect(user_id, ws)

        # Message originated from manager1 itself
        event_payload = {
            "type": "test_event",
            "event_id": "evt_abc123",
            "origin_worker_id": self.manager1.worker_id,
            "data": "test"
        }

        raw_msg = {
            "type": "message",
            "channel": f"sakura:realtime:{user_id}",
            "data": json.dumps(event_payload)
        }

        initial_count = len(ws.sent_messages)

        class MockPubSub:
            def __init__(self, messages):
                self.messages = list(messages)

            async def psubscribe(self, *args, **kwargs):
                pass

            async def listen(self):
                for m in self.messages:
                    yield m
                while True:
                    await asyncio.sleep(10)

        mock_client = MagicMock()
        mock_pubsub = MockPubSub([raw_msg])
        mock_client.pubsub.return_value = mock_pubsub

        with patch("redis.asyncio.from_url", return_value=mock_client):
            self.manager1._running = True
            loop_task = asyncio.create_task(self.manager1._redis_subscriber_loop())
            await asyncio.sleep(0.05)
            self.manager1._running = False
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # Since it had origin_worker_id == self.manager1.worker_id, it was discarded
        self.assertEqual(len(ws.sent_messages), initial_count)

    async def test_subscriber_on_second_worker_receives_event(self):
        """When manager2 receives an event from manager1 via Redis pubsub, it delivers it locally."""
        ws2 = FakeWebSocket()
        user_id = "user_123"
        await self.manager2.connect(user_id, ws2)

        event_payload = {
            "type": "cross_worker_event",
            "event_id": "evt_xyz789",
            "origin_worker_id": self.manager1.worker_id,  # From manager 1
            "data": "cross worker payload"
        }
        raw_msg = {
            "type": "message",
            "channel": f"sakura:realtime:{user_id}",
            "data": json.dumps(event_payload)
        }

        class MockPubSub:
            def __init__(self, messages):
                self.messages = list(messages)

            async def psubscribe(self, *args, **kwargs):
                pass

            async def listen(self):
                for m in self.messages:
                    yield m
                while True:
                    await asyncio.sleep(10)

        mock_client = MagicMock()
        mock_pubsub = MockPubSub([raw_msg])
        mock_client.pubsub.return_value = mock_pubsub

        with patch("redis.asyncio.from_url", return_value=mock_client):
            self.manager2._running = True
            loop_task = asyncio.create_task(self.manager2._redis_subscriber_loop())
            await asyncio.sleep(0.05)
            self.manager2._running = False
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        # manager2 should deliver to ws2 because origin_worker_id != manager2.worker_id
        self.assertEqual(len(ws2.sent_messages), 1)
        self.assertEqual(ws2.sent_messages[0]["type"], "cross_worker_event")

    async def test_user_specific_events_remain_isolated(self):
        """An event sent to user_A is not delivered to user_B."""
        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        await self.manager1.connect("user_A", ws_a)
        await self.manager1.connect("user_B", ws_b)

        mock_redis = AsyncMock()
        self.manager1._redis_client = mock_redis

        await self.manager1.send_to_user("user_A", {"type": "private_data"})

        self.assertEqual(len(ws_a.sent_messages), 1)
        self.assertEqual(len(ws_b.sent_messages), 0)

    async def test_broadcast_delivers_to_all_local_users(self):
        """Broadcast reaches all locally connected users."""
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        await self.manager1.connect("u1", ws1)
        await self.manager1.connect("u2", ws2)

        mock_redis = AsyncMock()
        self.manager1._redis_client = mock_redis

        await self.manager1.broadcast({"type": "system_announcement"})

        self.assertEqual(len(ws1.sent_messages), 1)
        self.assertEqual(len(ws2.sent_messages), 1)

    async def test_truthful_status_reporting(self):
        """Status accurately reflects whether Redis is reachable."""
        with patch.object(self.manager1, "_get_redis", return_value=None):
            status = await self.manager1.get_status()
            self.assertEqual(status["redis_connected"], False)
            self.assertEqual(status["status"], "DEGRADED")
            self.assertEqual(status["worker_id"], self.manager1.worker_id)
            self.assertEqual(status["local_delivery_available"], True)
            self.assertEqual(status["cross_worker_delivery_available"], False)


if __name__ == "__main__":
    unittest.main()
