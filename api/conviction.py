"""ConvictionTracker — sticky prediction lifecycle with validity checking."""

from __future__ import annotations

import enum
import time
from typing import Any


class ConvictionState(enum.StrEnum):
    INITIAL = "INITIAL"
    CONFIRMED = "CONFIRMED"
    WATCHING = "WATCHING"
    DIVERGING = "DIVERGING"
    STALE = "STALE"


# Confidence-based divergence thresholds (%)
_CONF_THRESHOLDS = {
    "HIGH": 1.0,
    "MEDIUM": 0.5,
    "LOW": 0.25,
}


class ConvictionTracker:
    """In-memory registry tracking active predictions per symbol/timeframe.

    The tracker stores each prediction when generated and checks its
    validity against incoming LTP ticks.  A prediction goes through:

        INITIAL → CONFIRMED → WATCHING → DIVERGING → re-predict → CONFIRMED
                              └→ recovery → CONFIRMED
                    └→ STALE (80 % horizon elapsed) → re-predict
    """

    def __init__(self) -> None:
        self._active: dict[str, dict[str, Any]] = {}

    # ── public API ─────────────────────────────────────────────────────────

    def get_active(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        return self._active.get(self._key(symbol, timeframe))

    def set_active(self, symbol: str, timeframe: str, result: dict[str, Any]) -> None:
        self._active[self._key(symbol, timeframe)] = {
            "result": result,
            "generated_at": time.time(),
            "divergence_count": 0,
        }

    def invalidate(self, symbol: str, timeframe: str) -> None:
        self._active.pop(self._key(symbol, timeframe), None)

    def clear(self, symbol: str, timeframe: str) -> None:
        self.invalidate(symbol, timeframe)

    def check_validity(
        self,
        symbol: str,
        timeframe: str,
        latest_ltp: float | None,
        latest_close: float | None,
        confidence_str: str | None = None,
    ) -> ConvictionState:
        """Compare latest price against expected prediction path.

        Returns the current :class:`ConvictionState`.
        """
        entry = self.get_active(symbol, timeframe)
        if entry is None:
            return ConvictionState.INITIAL

        result = entry["result"]
        pred_close: list[float] = result.get("pred_close", [])
        if not pred_close:
            return ConvictionState.INITIAL

        pred_len = len(pred_close)
        pred_timestamps: list[str] = result.get("pred_timestamps", [])

        # Horizon progress: how far into the prediction window we are
        if pred_timestamps:
            try:
                t0 = _parse_ts(pred_timestamps[0])
                t1 = _parse_ts(pred_timestamps[-1])
                horizon_span = max(t1 - t0, 1)
                elapsed = time.time() - t0
                horizon_pct = elapsed / horizon_span
            except Exception:
                horizon_pct = 0.0
        else:
            bar_span_s = _timeframe_seconds(timeframe)
            horizon_span = pred_len * bar_span_s
            elapsed = time.time() - entry["generated_at"]
            horizon_pct = elapsed / max(horizon_span, 1)

        # 80 % horizon consumed → STALE
        if horizon_pct >= 0.8:
            return ConvictionState.STALE

        # LTP divergence check
        price = latest_ltp or latest_close
        if price is None:
            return ConvictionState.CONFIRMED

        bar_idx = min(int(horizon_pct * pred_len), pred_len - 1)
        expected = pred_close[bar_idx]
        if expected == 0:
            return ConvictionState.CONFIRMED

        divergence_pct = abs(price - expected) / expected * 100

        # Threshold scaled by confidence
        threshold = _CONF_THRESHOLDS.get(confidence_str or "MEDIUM", 0.5)

        if divergence_pct > threshold:
            entry["divergence_count"] = entry.get("divergence_count", 0) + 1
        else:
            entry["divergence_count"] = 0

        dc = entry["divergence_count"]
        if dc >= 2:
            return ConvictionState.DIVERGING
        if dc == 1:
            return ConvictionState.WATCHING
        return ConvictionState.CONFIRMED

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _key(symbol: str, timeframe: str) -> str:
        return f"{symbol.upper()}:{timeframe}"


def _parse_ts(ts: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _timeframe_seconds(timeframe: str) -> int:
    """Parse e.g. '5min' / '1h' / '1d' -> seconds."""
    tf = timeframe.lower().strip()
    if tf.endswith("min") or tf.endswith("m"):
        return int(tf.rstrip("minm")) * 60
    if tf.endswith("h"):
        return int(tf.rstrip("h")) * 3600
    if tf.endswith("d"):
        return int(tf.rstrip("d")) * 86400
    return 300  # fallback 5min
