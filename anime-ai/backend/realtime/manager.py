"""
Sakura AI — Multi-Worker Safe Realtime Event Manager
Distributes WebSocket events across multiple backend and worker processes using Redis Pub/Sub,
while maintaining local client WebSocket connection handles per process.
Falls back gracefully to local in-process delivery when Redis is not running.
"""
import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import WebSocket

logger = logging.getLogger("sakura.realtime")


class RealtimeManager:
    """Manages WebSocket connections and cross-worker event broadcasting via Redis pub/sub."""

    def __init__(self):
        self.user_connections: Dict[str, List[WebSocket]] = {}
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._running = False

    async def initialize(self):
        """Initializes Redis connection and starts background pub/sub subscriber if available."""
        if self._running:
            return
        self._running = True
        self._pubsub_task = asyncio.create_task(self._redis_subscriber_loop())

    async def shutdown(self):
        """Closes subscriber loop and cleans up connections."""
        self._running = False
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        if self._redis_client:
            try:
                await self._redis_client.close()
            except Exception:
                pass

    async def connect(self, user_id: str, websocket: WebSocket):
        """Registers a client WebSocket connection on this worker instance."""
        await websocket.accept()
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        """Removes a client WebSocket connection from this worker instance."""
        if user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def send_local(self, user_id: str, message: dict):
        """Sends a message directly to WebSockets connected to this local worker instance."""
        if user_id in self.user_connections:
            dead_sockets = []
            for ws in self.user_connections[user_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_sockets.append(ws)
            for ws in dead_sockets:
                self.disconnect(user_id, ws)

    async def send_to_user(self, user_id: str, message: dict):
        """
        Publishes message to Redis pub/sub for distribution across all backend workers,
        and delivers locally to any connected clients on this instance.
        """
        user_id_str = str(user_id)
        # 1. Local delivery immediately
        await self.send_local(user_id_str, message)

        # 2. Redis pub/sub for other workers
        published = await self._publish_to_redis(f"sakura:realtime:{user_id_str}", message)
        if not published:
            # Redis not running; local delivery already handled
            pass

    async def broadcast(self, message: dict):
        """Broadcasts message to all connected users across all workers."""
        for user_id in list(self.user_connections.keys()):
            await self.send_local(user_id, message)
        await self._publish_to_redis("sakura:realtime:broadcast", message)

    async def _get_redis(self):
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                client = aioredis.from_url(self.redis_url, decode_responses=True, socket_connect_timeout=2)
                await client.ping()
                self._redis_client = client
            except Exception:
                self._redis_client = None
        return self._redis_client

    async def _publish_to_redis(self, channel: str, message: dict) -> bool:
        client = await self._get_redis()
        if not client:
            return False
        try:
            payload = json.dumps(message)
            await client.publish(channel, payload)
            return True
        except Exception:
            self._redis_client = None
            return False

    async def _redis_subscriber_loop(self):
        """Background loop subscribing to Redis channels and routing events to local websockets."""
        backoff = 2
        while self._running:
            try:
                import redis.asyncio as aioredis
                client = aioredis.from_url(self.redis_url, decode_responses=True, socket_connect_timeout=3)
                pubsub = client.pubsub()
                await pubsub.psubscribe("sakura:realtime:*")
                backoff = 2

                async for raw_message in pubsub.listen():
                    if not self._running:
                        break
                    if raw_message and raw_message.get("type") in ["pmessage", "message"]:
                        channel = raw_message.get("channel", "")
                        data_str = raw_message.get("data", "")
                        try:
                            msg = json.loads(data_str)
                            if channel == "sakura:realtime:broadcast":
                                for uid in list(self.user_connections.keys()):
                                    await self.send_local(uid, msg)
                            elif channel.startswith("sakura:realtime:"):
                                target_user_id = channel.split("sakura:realtime:")[-1]
                                await self.send_local(target_user_id, msg)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


# Singleton manager instance
ws_manager = RealtimeManager()
