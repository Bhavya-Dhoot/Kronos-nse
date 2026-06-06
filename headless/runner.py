"""Headless production runner: DQG-gated batch inference on candle close."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TypedDict

from data.quality.gate import DQGStatus

logger = logging.getLogger(__name__)

_TF_SECONDS = {
    "1min": 60,
    "1m": 60,
    "5min": 300,
    "5m": 300,
    "15min": 900,
    "15m": 900,
    "1day": 86400,
    "1d": 86400,
}


class SignalDict(TypedDict, total=False):
    symbol: str
    timeframe: str
    mode: str
    direction: str
    confidence: str
    expected_move_pct: float
    last_close: float
    pred_close: float
    pred_close_seq: list[float]
    model_version: str
    generated_at: str


class HeadlessRunner:
    """Polls candle boundaries and runs batch DQG → predict → signal emission."""

    def __init__(
        self,
        config: dict[str, Any],
        engine: Any,
        db: Any,
        redis_cache: Any,
        dqg: Any,
        context_builder: Any,
        signal_emitter: Any,
        ledger: Any,
        *,
        watchdog: Any | None = None,
    ) -> None:
        self._config = config
        self._engine = engine
        self._db = db
        self._redis = redis_cache
        self._dqg = dqg
        self._context_builder = context_builder
        self._signal_emitter = signal_emitter
        self._ledger = ledger
        self._watchdog = watchdog
        self._running = False
        self._symbols: list[str] = []
        self._timeframe = "5min"
        self._task: Any = None
        self._last_cycle_at: float | None = None
        self._last_processed_boundary: int | None = None

    async def run(self, symbols: list[str], timeframe: str = "5min") -> None:
        """Main polling loop until stopped."""
        self._symbols = symbols
        self._timeframe = timeframe
        self._running = True
        logger.info("HeadlessRunner started: %d symbols, %s", len(symbols), timeframe)

        while self._running:
            next_close = self._get_next_candle_time(timeframe)
            if time.time() >= next_close:
                boundary = self._boundary_key(timeframe)
                if boundary != self._last_processed_boundary:
                    self._last_processed_boundary = boundary
                    await self._on_candle_close(symbols, timeframe)
                    if self._watchdog is not None:
                        self._watchdog.heartbeat()
            await asyncio.sleep(0.1)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False

    # ── MVS helpers ──────────────────────────────────────────────────────

    def _get_mvs_threshold(self) -> float:
        """Read signal_threshold from engine MVS, or fall back to 0.005.

        Per D-22/D-23: replaces hardcoded 0.005 with dynamic threshold
        from MarketVarianceScore when MVE is available and ready.
        """
        try:
            mve = getattr(self._engine, "_mve", None)
            if mve is not None and getattr(mve, "is_ready", False):
                mvs = getattr(mve, "last_mvs", None) or {}
                return float(mvs.get("signal_threshold", 0.005))
        except Exception:
            logger.debug("Failed to read MVS signal_threshold, using default", exc_info=True)
        return 0.005

    def _get_mvs_confidence_override(self) -> str | None:
        """Read confidence_override from engine MVS, or return None.

        Per D-19/D-20: if MVS says PANIC/FEAR/UNCERTAIN, override
        signal confidence to LOW regardless of computed value.
        """
        try:
            mve = getattr(self._engine, "_mve", None)
            if mve is not None and getattr(mve, "is_ready", False):
                mvs = getattr(mve, "last_mvs", None) or {}
                return mvs.get("confidence_override")
        except Exception:
            logger.debug("Failed to read MVS confidence_override", exc_info=True)
        return None

    # ── core logic ───────────────────────────────────────────────────────

    async def _on_candle_close(self, symbols: list[str], timeframe: str) -> None:
        """Execute one full headless cycle for all symbols."""
        cycle_start = time.perf_counter()

        reports = await self._dqg.run_batch(symbols, timeframe, "HEADLESS")
        valid_symbols: list[str] = []
        for symbol in symbols:
            report = reports[symbol]
            if report.status == DQGStatus.PASS:
                valid_symbols.append(symbol)
            else:
                logger.warning(
                    "DQG failed for %s: status=%s recommendation=%s",
                    symbol,
                    report.status.value,
                    report.recommendation,
                )

        if not valid_symbols:
            logger.error("Headless cycle skipped: zero symbols passed DQG")
            return

        contexts: dict[str, dict[str, Any]] = {}
        last_closes: dict[str, float] = {}
        build_tasks = [self._context_builder.build(sym, timeframe, "HEADLESS") for sym in valid_symbols]
        built = await asyncio.gather(*build_tasks, return_exceptions=True)
        for symbol, ctx in zip(valid_symbols, built, strict=True):
            if isinstance(ctx, Exception):
                logger.exception("Context build failed for %s", symbol)
                continue
            contexts[symbol] = ctx
            if not ctx["df"].empty:
                last_closes[symbol] = float(ctx["df"]["close"].iloc[-1])

        predict_requests = []
        for symbol, ctx in contexts.items():
            temperature = ctx.get("temperature_override")
            predict_requests.append(
                {
                    "symbol": symbol,
                    "df": ctx["df"],
                    "x_ts": ctx["x_ts"],
                    "y_ts": ctx["y_ts"],
                    "timeframe": timeframe,
                    "mode": "HEADLESS",
                    "temperature": temperature,
                    "force": True,
                    "skip_dqg": True,
                }
            )

        predictions = await self._engine.predict_batch(predict_requests)

        signals: list[SignalDict] = []
        for pred in predictions:
            symbol = pred["symbol"]
            last_close = last_closes.get(symbol, float(pred["pred_close"][0]))
            ledger_payload = self._ledger.prediction_from_engine_result(pred)
            self._ledger.record_fire_and_forget(ledger_payload)

            signal = self._compute_signal(pred, last_close)
            signals.append(signal)

            if self._config.get("app", {}).get("mode") == "PAPER" or self._is_paper_mode():
                await self._log_paper_trade(signal)

        emit_tasks = [self._signal_emitter.emit(sig) for sig in signals]
        await asyncio.gather(*emit_tasks)

        elapsed_ms = (time.perf_counter() - cycle_start) * 1000
        logger.info("%d signals emitted in %.0fms", len(signals), elapsed_ms)
        self._last_cycle_at = time.time()

    def _is_paper_mode(self) -> bool:
        import os

        return os.getenv("APP_MODE", "").upper() == "PAPER"

    async def _log_paper_trade(self, signal: SignalDict) -> None:
        if signal.get("direction") == "NEUTRAL":
            return
        try:
            await self._db.store_paper_trade(
                {
                    "symbol": signal["symbol"],
                    "direction": signal["direction"],
                    "entry_price": signal.get("last_close", 0.0),
                    "quantity": 1.0,
                    "signal_id": None,
                }
            )
        except Exception:
            logger.exception("Failed to log paper trade for %s", signal.get("symbol"))

    def _compute_signal(self, pred: dict[str, Any], last_close: float) -> SignalDict:
        """Derive BULLISH/BEARISH/NEUTRAL signal from prediction.

        Uses MVS signal_threshold for direction classification (D-22/D-23)
        and applies MVS confidence_override after computed confidence (D-19/D-20).
        """
        threshold = self._get_mvs_threshold()

        pred_close = pred.get("pred_close") or []
        if not pred_close or not last_close:
            return SignalDict(
                symbol=pred["symbol"],
                timeframe=pred.get("timeframe", "5min"),
                mode=pred.get("mode", "HEADLESS"),
                direction="NEUTRAL",
                confidence="LOW",
                expected_move_pct=0.0,
                last_close=last_close,
                pred_close=float(pred_close[-1]) if pred_close else 0.0,
                pred_close_seq=[float(x) for x in pred_close],
                model_version=str(pred.get("model_version", "")),
                generated_at=str(pred.get("generated_at", "")),
            )

        target = float(pred_close[-1])
        expected_move = (target - last_close) / last_close
        expected_move_pct = expected_move * 100

        if expected_move > threshold:
            direction = "BULLISH"
        elif expected_move < -threshold:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        abs_move_pct = abs(expected_move_pct)
        if abs_move_pct > 1.0:
            confidence = "HIGH"
        elif abs_move_pct > 0.5:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # Override confidence if MVS says so (D-19/D-20)
        mvs_confidence = self._get_mvs_confidence_override()
        if mvs_confidence is not None:
            confidence = mvs_confidence

        return SignalDict(
            symbol=pred["symbol"],
            timeframe=pred.get("timeframe", "5min"),
            mode=pred.get("mode", "HEADLESS"),
            direction=direction,
            confidence=confidence,
            expected_move_pct=expected_move_pct,
            last_close=last_close,
            pred_close=target,
            pred_close_seq=[float(x) for x in pred_close],
            model_version=str(pred.get("model_version", "")),
            generated_at=str(pred.get("generated_at", "")),
        )

    @staticmethod
    def _boundary_key(timeframe: str) -> int:
        """Integer bucket id for the current candle period."""
        tf = timeframe.lower().strip()
        tf_seconds = _TF_SECONDS.get(tf, 300)
        return int(time.time() // tf_seconds)

    @staticmethod
    def _get_next_candle_time(timeframe: str) -> float:
        """Unix timestamp of next candle close (+500ms buffer)."""
        tf = timeframe.lower().strip()
        tf_seconds = _TF_SECONDS.get(tf, 300)
        now = time.time()
        return now + (tf_seconds - now % tf_seconds) + 0.5

    async def resolve_yesterday_predictions(self, symbols: list[str]) -> None:
        """Resolve stale ledger rows using actual candles from DB."""
        for symbol in symbols:
            rows = await self._ledger.get_unresolved(symbol, older_than_hours=24)
            for row in rows:
                try:
                    pred_ts = row.get("pred_timestamps") or []
                    if not pred_ts:
                        continue
                    tf = row.get("timeframe", self._timeframe)
                    limit = max(len(row.get("pred_close", [])), 10)
                    actual_df = await self._db.get_candles(symbol, tf, limit=limit + 5)
                    if actual_df.empty:
                        continue

                    actual_close = actual_df["close"].astype(float).tolist()[-limit:]
                    actual_high = actual_df["high"].astype(float).tolist()[-limit:]
                    actual_low = actual_df["low"].astype(float).tolist()[-limit:]
                    pred_len = len(row.get("pred_close", []))
                    await self._ledger.resolve(
                        int(row["id"]),
                        actual_close[:pred_len],
                        actual_high=actual_high[:pred_len],
                        actual_low=actual_low[:pred_len],
                    )
                except Exception:
                    logger.exception("Failed to resolve ledger id=%s for %s", row.get("id"), symbol)

