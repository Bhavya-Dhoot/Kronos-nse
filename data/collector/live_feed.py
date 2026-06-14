"""Live feed consumer: Angel websocket -> Redis + TimescaleDB."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)
IST = "Asia/Kolkata"


class LiveFeedConsumer:
    """Consumes ticks via a thread-safe queue, publishes Redis, persists candle closes."""

    def __init__(
        self,
        client: Any,
        db: Any,
        redis_cache: Any,
        config: dict[str, Any],
        candle_timeframe: str = "5min",
    ) -> None:
        self.client = client
        self.db = db
        self.redis_cache = redis_cache
        self.config = config
        self.candle_timeframe = candle_timeframe
        self._running = False
        self._symbol_by_token: dict[str, str] = {}
        self._last_bucket: dict[str, pd.Timestamp] = {}
        self._candle_buf: dict[str, dict[str, Any]] = defaultdict(dict)
        self._tick_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10_000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._processor_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_attempt: int = 0

    async def start(self, symbols: list[dict[str, Any]]) -> None:
        """Subscribe to websocket and process ticks on the asyncio loop."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._symbol_by_token = {str(s["token"]): s["symbol"] for s in symbols}
        tokens = [str(s["token"]) for s in symbols]
        tokens_list = [{"exchangeType": 1, "tokens": tokens}]

        self._processor_task = asyncio.create_task(self._process_ticks())

        def _tick_cb(msg: dict[str, Any]) -> None:
            if not self._running or self._loop is None:
                return
            try:
                self._loop.call_soon_threadsafe(self._enqueue_tick, msg)
            except RuntimeError:
                logger.warning("Tick dropped — event loop not running")

        def _err_cb(err: Exception) -> None:
            logger.error("Websocket error: %s", err, exc_info=err)
            if self._running and self._loop:
                self._loop.call_soon_threadsafe(
                    lambda: self._schedule_reconnect(tokens_list, _tick_cb, _err_cb)
                )

        self.client.start_websocket(tokens_list, _tick_cb, _err_cb)

    def _enqueue_tick(self, msg: dict[str, Any]) -> None:
        try:
            self._tick_queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Tick queue full — dropping tick")

    def _schedule_reconnect(
        self,
        tokens_list: list[dict[str, Any]],
        on_tick,
        on_error,
    ) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = asyncio.create_task(
            self._reconnect(tokens_list, on_tick, on_error)
        )

    async def _reconnect(
        self,
        tokens_list: list[dict[str, Any]],
        on_tick,
        on_error,
    ) -> None:
        try:
            delays = [5, 15, 45, 120, 300]
            idx = min(self._reconnect_attempt, len(delays) - 1)
            delay = delays[idx]
            self._reconnect_attempt += 1
            logger.info(
                "Reconnecting websocket in %ds (attempt %d)...",
                delay,
                self._reconnect_attempt,
            )
            await asyncio.sleep(delay)
            if self._running:
                self.client.stop_websocket()
                self.client.start_websocket(tokens_list, on_tick, on_error)
        except asyncio.CancelledError:
            logger.debug("Previous reconnect superseded")
            raise

    async def _process_ticks(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._tick_queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._on_tick(msg)

    async def stop(self) -> None:
        """Stop processing and close websocket."""
        self._running = False
        self.client.stop_websocket()
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None

    async def _on_tick(self, raw_message: dict[str, Any]) -> None:
        self._reconnect_attempt = 0  # Reset backoff on successful data
        token = str(raw_message.get("symbol_token") or raw_message.get("token") or "")
        symbol = self._symbol_by_token.get(token, token)

        ts_raw = (
            raw_message.get("exchange_timestamp")
            or raw_message.get("timestamp")
            or datetime.now().isoformat()
        )
        ts = pd.Timestamp(ts_raw)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)

        ltp = float(raw_message.get("ltp") or raw_message.get("last_traded_price") or 0)
        o = float(raw_message.get("open") or ltp)
        h = float(raw_message.get("high") or ltp)
        low = float(raw_message.get("low") or ltp)
        v = float(raw_message.get("volume") or 0)

        tick = {
            "symbol": symbol,
            "symbol_token": token,
            "timestamp": ts.isoformat(),
            "ltp": ltp,
            "open": o,
            "high": h,
            "low": low,
            "volume": v,
        }
        await self.redis_cache.publish_tick(symbol, tick)

        buf = self._candle_buf[symbol]
        if not buf:
            buf.update(
                {
                    "open": ltp,
                    "high": h,
                    "low": low,
                    "close": ltp,
                    "volume": v,
                    "timestamp": ts,
                }
            )
        else:
            buf["high"] = max(buf["high"], h)
            buf["low"] = min(buf["low"], low)
            buf["close"] = ltp
            buf["volume"] = max(buf["volume"], v)
            buf["timestamp"] = ts

        if self._detect_candle_close(tick, timeframe=self.candle_timeframe):
            completed = {
                "time": self._last_bucket[symbol].to_pydatetime(),
                "symbol": symbol,
                "timeframe": self.candle_timeframe,
                "open": float(buf["open"]),
                "high": float(buf["high"]),
                "low": float(buf["low"]),
                "close": float(buf["close"]),
                "volume": float(buf["volume"]),
                "is_adjusted": False,
                "source": "angel_one_ws",
            }
            await self._on_candle_close(symbol, completed)
            self._candle_buf[symbol] = {}

    async def _on_candle_close(
        self, symbol: str, completed_candle: dict[str, Any]
    ) -> None:
        await self.db.bulk_insert_candles([completed_candle])
        await self.redis_cache.set(
            f"kronos:last_candle:{symbol}",
            {"symbol": symbol, "candle": completed_candle},
            ttl=300,
        )
        await self.redis_cache.publish_candle(symbol, completed_candle)
        await self.redis_cache.publish_dqg_status(
            symbol,
            {
                "type": "staleness_refresh",
                "symbol": symbol,
                "timeframe": self.candle_timeframe,
            },
        )

    def _detect_candle_close(
        self, tick: dict[str, Any], timeframe: str = "5min"
    ) -> bool:
        token = str(tick.get("symbol_token") or tick.get("token") or "")
        symbol = self._symbol_by_token.get(token, token)
        ts = pd.Timestamp(tick.get("timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        minutes = int(timeframe.replace("min", ""))
        bucket = ts.floor(f"{minutes}min")
        prev = self._last_bucket.get(symbol)
        if prev is None:
            self._last_bucket[symbol] = bucket
            return False
        if bucket > prev:
            self._last_bucket[symbol] = bucket
            return True
        return False
