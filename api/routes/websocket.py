"""WebSocket routes for live predictions, ticks, DQG, and signals."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.helpers import dqg_mode, dqg_report_to_response, engine_result_to_prediction
from api.ws_manager import ws_manager
from data.quality.gate import DQGFailureError, DQGStatus
from model.factory import InferenceContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


def _ctx(websocket: WebSocket) -> InferenceContext:
    ctx = getattr(websocket.app.state, "inference", None)
    if ctx is None:
        raise RuntimeError("Inference context not initialized")
    return ctx


async def _prediction_transform(
    payload: dict,
    *,
    symbol: str,
    ctx: InferenceContext,
) -> dict | None:
    """Recompute prediction when a candle closes."""
    try:
        report = await ctx.dqg.run(symbol, payload.get("timeframe", "5min"), dqg_mode("STANDARD"))
        if report.status != DQGStatus.PASS:
            return {
                "type": "dqg_blocked",
                "symbol": symbol,
                "report": dqg_report_to_response(report).model_dump(),
            }
        built = await ctx.context_builder.build(symbol, payload.get("timeframe", "5min"), "STANDARD")
        last_close = float(payload.get("close") or built["df"]["close"].iloc[-1])
        raw = await ctx.engine.predict(
            symbol=symbol,
            df=built["df"],
            x_ts=built["x_ts"],
            y_ts=built["y_ts"],
            timeframe=payload.get("timeframe", "5min"),
            mode=dqg_mode("STANDARD"),
            skip_dqg=True,
        )
        pred = engine_result_to_prediction(
            raw,
            dqg_status=report.status.value,
            data_coverage=float(report.coverage_pct or 0.0),
            last_close=last_close,
        )
        return {"type": "prediction", "payload": pred.model_dump()}
    except DQGFailureError as exc:
        return {
            "type": "dqg_blocked",
            "symbol": symbol,
            "report": dqg_report_to_response(exc.report).model_dump(),
        }
    except Exception as exc:
        logger.exception("WS prediction failed for %s", symbol)
        return {"type": "error", "symbol": symbol, "detail": str(exc)}


@router.websocket("/ping")
async def ws_ping(websocket: WebSocket) -> None:
    """Simple ping endpoint for connectivity tests."""
    await websocket.accept()
    await websocket.send_json({"type": "ping", "channel": "ping"})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


@router.websocket("/predictions/{symbol}")
async def ws_predictions(websocket: WebSocket, symbol: str) -> None:
    """Stream predictions on candle close for a symbol."""
    ctx = _ctx(websocket)
    channel = f"predictions:{symbol.upper()}"

    async def _transform(payload: dict) -> dict | None:
        if payload.get("symbol", symbol).upper() != symbol.upper():
            return None
        return await _prediction_transform(payload, symbol=symbol.upper(), ctx=ctx)

    ws_manager.start_redis_listener(
        channel,
        ctx.redis,
        f"candles:{symbol.upper()}",
        transform=_transform,
    )
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, channel)
        ws_manager.stop_redis_listener(channel)


@router.websocket("/ticks/{symbol}")
async def ws_ticks(websocket: WebSocket, symbol: str) -> None:
    """Proxy Redis tick pub/sub to WebSocket clients."""
    ctx = _ctx(websocket)
    channel = f"ticks:{symbol.upper()}"
    ws_manager.start_redis_listener(channel, ctx.redis, f"ticks:{symbol.upper()}")
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, channel)
        ws_manager.stop_redis_listener(channel)


@router.websocket("/dqg/{symbol}")
async def ws_dqg(websocket: WebSocket, symbol: str) -> None:
    """Proxy Redis DQG pub/sub to WebSocket clients."""
    ctx = _ctx(websocket)
    channel = f"dqg:{symbol.upper()}"

    async def _transform(payload: dict) -> dict:
        return {"type": "dqg", "payload": payload}

    ws_manager.start_redis_listener(
        channel,
        ctx.redis,
        f"dqg:{symbol.upper()}",
        transform=_transform,
    )
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, channel)
        ws_manager.stop_redis_listener(channel)


@router.websocket("/signals")
async def ws_signals(websocket: WebSocket) -> None:
    """Broadcast all trading signals to connected clients."""
    ctx = _ctx(websocket)
    channel = "signals:all"
    pubsub = ctx.redis.pubsub()
    await pubsub.psubscribe("signals:*")
    await ws_manager.connect(websocket, channel)

    async def _forward() -> None:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message or message.get("type") != "pmessage":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                payload = {"raw": message.get("data")}
            await ws_manager.broadcast(channel, {"type": "signal", "payload": payload})

    task = asyncio.create_task(_forward())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        await pubsub.punsubscribe("signals:*")
        await pubsub.aclose()
        await ws_manager.disconnect(websocket, channel)


@router.websocket("/variance")
async def ws_variance(websocket: WebSocket) -> None:
    """Stream real-time MVS updates to connected clients.

    Listens on the Redis ``mve:mvs:updates`` channel (published by the
    MarketVarianceEngine on every recompute that passes the 1% threshold)
    and forwards typed ``{"type": "mvs_update", "payload": {...}}``
    messages to WebSocket clients.
    """
    mve_redis = getattr(websocket.app.state, "mve_redis", None)
    if mve_redis is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "detail": "MVE not available"})
        await websocket.close()
        return

    channel = "variance:all"

    async def _transform(payload: dict) -> dict:
        return {"type": "mvs_update", "payload": payload}

    ws_manager.start_redis_listener(
        channel,
        mve_redis,
        "mve:mvs:updates",
        transform=_transform,
    )
    await ws_manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, channel)
        ws_manager.stop_redis_listener(channel)
