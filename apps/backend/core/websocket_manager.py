from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from contextlib import suppress
from typing import Any

from fastapi import WebSocket

from database.config.config import settings


class ConnectionManager:
    """WebSocket channel registry with optional Redis cross-worker fan-out."""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = defaultdict(list)
        self.client_connections: dict[tuple[str, str], WebSocket] = {}
        self.instance_id = uuid.uuid4().hex
        self.redis: Any | None = None
        self.pubsub: Any | None = None
        self.listener_task: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        if not settings.REDIS_URL or self.redis is not None:
            return
        try:
            from redis.asyncio import Redis

            self.redis = Redis.from_url(
                settings.REDIS_URL,
                encoding='utf-8',
                decode_responses=True,
            )
            await self.redis.ping()
            self.pubsub = self.redis.pubsub()
            await self.pubsub.subscribe(settings.REDIS_REALTIME_CHANNEL)
            self.listener_task = asyncio.create_task(self._listen_for_events())
        except Exception:
            self.redis = None
            self.pubsub = None

    async def shutdown(self) -> None:
        if self.listener_task:
            self.listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.listener_task
            self.listener_task = None
        if self.pubsub:
            with suppress(Exception):
                await self.pubsub.unsubscribe(settings.REDIS_REALTIME_CHANNEL)
                await self.pubsub.aclose()
            self.pubsub = None
        if self.redis:
            with suppress(Exception):
                await self.redis.aclose()
            self.redis = None
        self.loop = None

    def schedule(self, coroutine: Any) -> None:
        """Schedule a realtime coroutine from async routes or sync worker threads."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None:
            running_loop.create_task(coroutine)
            return

        if self.loop is not None and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            return

        # No application loop is active (for example, an offline CLI command).
        # Close the un-awaited coroutine cleanly instead of leaking a warning.
        with suppress(Exception):
            coroutine.close()

    async def _listen_for_events(self) -> None:
        if not self.pubsub:
            return
        async for message in self.pubsub.listen():
            if message.get('type') != 'message':
                continue
            try:
                envelope = json.loads(message['data'])
                if envelope.get('origin') == self.instance_id:
                    continue
                channel = str(envelope['channel'])
                payload = envelope['payload']
                if isinstance(payload, dict):
                    await self._send_local(channel, payload)
            except Exception:
                continue

    async def register_client(self, user_id: str, client_id: str, websocket: WebSocket) -> None:
        key = (user_id, client_id)
        previous = self.client_connections.get(key)
        self.client_connections[key] = websocket
        if previous and previous is not websocket:
            with suppress(Exception):
                await previous.close(code=4000, reason='Replaced by a newer connection')

    def unregister_client(self, user_id: str, client_id: str, websocket: WebSocket) -> None:
        key = (user_id, client_id)
        if self.client_connections.get(key) is websocket:
            self.client_connections.pop(key, None)

    def subscribe(self, channel: str, websocket: WebSocket) -> None:
        connections = self.active_connections[channel]
        if websocket not in connections:
            connections.append(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        connections = self.active_connections.get(channel)
        if not connections:
            return
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active_connections.pop(channel, None)

    def disconnect_all(self, websocket: WebSocket) -> None:
        for channel in list(self.active_connections):
            self.disconnect(channel, websocket)

    async def _send_local(self, channel: str, data: dict) -> None:
        connections = list(self.active_connections.get(channel, []))
        if not connections:
            return
        message = json.dumps(data, default=str)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(channel, connection)

    async def send_to_channel(self, channel: str, data: dict) -> None:
        await self._send_local(channel, data)
        if not self.redis:
            return
        try:
            await self.redis.publish(
                settings.REDIS_REALTIME_CHANNEL,
                json.dumps(
                    {
                        'origin': self.instance_id,
                        'channel': channel,
                        'payload': data,
                    },
                    default=str,
                ),
            )
        except Exception:
            pass

    async def send_to_user(self, user_id: str, data: dict) -> None:
        await self.send_to_channel(f'user-{user_id}', data)

    async def broadcast(self, data: dict) -> None:
        for channel in list(self.active_connections):
            await self.send_to_channel(channel, data)


manager = ConnectionManager()
