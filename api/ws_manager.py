"""WebSocket connection manager with Redis pub/sub bridging."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks WebSocket clients per channel and broadcasts JSON payloads."""

    def __init__(self) -> None:
        self.active: dict[str, set[WebSocket]] = defaultdict(set)
        self._listener_tasks: dict[str, asyncio.Task] = {}
        self._listener_refs: dict[str, int] = defaultdict(int)

    async def connect(self, websocket: WebSocket, channel: str) -> None:
        """Accept a WebSocket and register it on a channel."""
        await websocket.accept()
        self.active[channel].add(websocket)
        await websocket.send_json({"type": "ping", "channel": channel})

    async def disconnect(self, websocket: WebSocket, channel: str) -> None:
        """Remove a WebSocket from a channel."""
        self.active[channel].discard(websocket)
        if not self.active[channel]:
            del self.active[channel]

    async def broadcast(self, channel: str, data: dict[str, Any]) -> None:
        """Send JSON to all clients subscribed to a channel."""
        dead: list[WebSocket] = []
        for ws in list(self.active.get(channel, set())):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, channel)

    def start_redis_listener(
        self,
        channel: str,
        redis_cache: Any,
        redis_channel: str,
        *,
        transform: Any | None = None,
    ) -> None:
        """Start a shared Redis pub/sub listener for a logical WS channel."""
        self._listener_refs[channel] += 1
        if channel in self._listener_tasks:
            return
        self._listener_tasks[channel] = asyncio.create_task(
            self._redis_listen_loop(channel, redis_cache, redis_channel, transform)
        )

    def stop_redis_listener(self, channel: str) -> None:
        """Stop Redis listener when no clients remain on the channel."""
        self._listener_refs[channel] = max(0, self._listener_refs[channel] - 1)
        if self._listener_refs[channel] == 0:
            task = self._listener_tasks.pop(channel, None)
            if task:
                task.cancel()

    async def _redis_listen_loop(
        self,
        ws_channel: str,
        redis_cache: Any,
        redis_channel: str,
        transform: Any | None,
    ) -> None:
        pubsub = redis_cache.pubsub()
        await pubsub.subscribe(redis_channel)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if not message or message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    payload = {"raw": message.get("data")}
                if transform is not None:
                    payload = await transform(payload)
                    if payload is None:
                        continue
                await self.broadcast(ws_channel, payload)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Redis listener failed for %s", ws_channel)
        finally:
            await pubsub.unsubscribe(redis_channel)
            await pubsub.aclose()
            self._listener_tasks.pop(ws_channel, None)


ws_manager = ConnectionManager()
