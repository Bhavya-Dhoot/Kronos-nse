from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.ws_manager import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.mark.asyncio
async def test_connect_adds_websocket(manager):
    ws = AsyncMock()
    await manager.connect(ws, "predictions")
    assert ws in manager.active["predictions"]
    ws.send_json.assert_awaited_once_with({"type": "ping", "channel": "predictions"})


@pytest.mark.asyncio
async def test_disconnect_removes_websocket(manager):
    ws = AsyncMock()
    await manager.connect(ws, "predictions")
    await manager.disconnect(ws, "predictions")
    assert "predictions" not in manager.active


@pytest.mark.asyncio
async def test_broadcast_sends_to_all(manager):
    ws1, ws2 = AsyncMock(), AsyncMock()
    await manager.connect(ws1, "test")
    await manager.connect(ws2, "test")
    ws1.send_json.reset_mock()
    ws2.send_json.reset_mock()
    await manager.broadcast("test", {"msg": "hello"})
    ws1.send_json.assert_awaited_once_with({"msg": "hello"})
    ws2.send_json.assert_awaited_once_with({"msg": "hello"})


@pytest.mark.asyncio
async def test_broadcast_removes_dead_clients(manager):
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await manager.connect(ws1, "test")
    await manager.connect(ws2, "test")
    ws2.send_json.side_effect = Exception("disconnected")
    await manager.broadcast("test", {"msg": "hello"})
    assert ws1 in manager.active.get("test", set())
    assert ws2 not in manager.active.get("test", set())


@pytest.mark.asyncio
async def test_start_redis_listener(manager):
    redis = MagicMock()
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    assert "mve" in manager._listener_tasks
    assert manager._listener_refs["mve"] == 1


@pytest.mark.asyncio
async def test_start_redis_listener_dedup(manager):
    redis = MagicMock()
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    task = manager._listener_tasks["mve"]
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    assert manager._listener_tasks["mve"] is task
    assert manager._listener_refs["mve"] == 2


@pytest.mark.asyncio
async def test_stop_redis_listener_keeps_task_with_refs(manager):
    redis = MagicMock()
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    manager.stop_redis_listener("mve")
    assert "mve" in manager._listener_tasks
    assert manager._listener_refs["mve"] == 1


@pytest.mark.asyncio
async def test_stop_redis_listener_removes_at_zero(manager):
    redis = MagicMock()
    manager.start_redis_listener("mve", redis, "mve:mvs:updates")
    manager.stop_redis_listener("mve")
    assert "mve" not in manager._listener_tasks
