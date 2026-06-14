"""OICollector — polls Nifty/BankNifty futures OI every 300s via AngelOneClient."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from variance.base_collector import BaseVarianceCollector
from variance.collectors._angel import _get_angel_client
from variance.schemas import ParseResult

OI_BASELINE_KEY_PREFIX = "mve:oi_baseline"
TRACKED_SYMBOLS = ["NIFTY", "BANKNIFTY"]


class OICollector(BaseVarianceCollector):
    """Poll Nifty/BankNifty futures OI every 300s for institutional sentiment.

    Per D-10: OI buildup (>= 3% change) → ±0.3 score, linear interpolation below.
    Persists baseline in Redis via poll_with_baseline() for change computation.
    """

    def __init__(self, redis_cache=None) -> None:
        super().__init__(name="oi", poll_interval=300)
        self._redis = redis_cache

    async def fetch(self) -> Any:
        """Fetch futures OI for all tracked symbols via AngelOneClient."""
        angel = _get_angel_client()
        results: dict[str, dict] = {}
        for symbol in TRACKED_SYMBOLS:
            try:
                data = await asyncio.to_thread(angel.get_futures_oi, symbol)
                results[symbol] = data if isinstance(data, dict) else {}
            except Exception:
                results[symbol] = {}
        return results

    def parse(self, raw: Any) -> ParseResult:
        if not isinstance(raw, dict):
            raise ValueError(f"Unexpected OI data type: {type(raw)}")

        symbols_detail = {}
        total_oi = 0.0
        symbols_with_data = 0
        for symbol in TRACKED_SYMBOLS:
            data = raw.get(symbol, {})
            if isinstance(data, dict) and data.get("open_interest") is not None:
                oi = self._to_float(data["open_interest"], 0.0)
                ltp = self._to_float(data.get("ltp"), 0.0)
                symbols_detail[symbol] = {
                    "open_interest": oi,
                    "ltp": ltp,
                    "has_data": True,
                }
                total_oi += oi
                symbols_with_data += 1
            else:
                symbols_detail[symbol] = {
                    "open_interest": 0.0,
                    "ltp": 0.0,
                    "has_data": False,
                }

        if symbols_with_data == 0:
            raise ValueError("No OI data received for any tracked symbol")

        return ParseResult(
            raw_value=total_oi,
            normalized=0.0,
            direction=0,
            magnitude=0.0,
            detail={
                "symbols": symbols_detail,
                "total_oi": total_oi,
                "symbols_with_data": symbols_with_data,
                "tracked_count": len(TRACKED_SYMBOLS),
            },
            source="angel",
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Score OI change percentage, clamped to [-0.3, 0.3].

        Per D-10: OI buildup >= 3% → +0.3 (bullish), OI unwind >= 3% → -0.3 (bearish).
        Below 3% uses linear interpolation: change_pct / 10.0.
        """
        oi_change_pct = parsed.get("detail", {}).get("oi_change_pct", 0.0)
        if oi_change_pct <= -3.0:
            return -0.3
        elif oi_change_pct >= 3.0:
            return 0.3
        else:
            return oi_change_pct / 10.0

    async def poll_with_baseline(self, redis_cache):
        """Full poll cycle with Redis baseline tracking for OI change computation.

        Stores current OI as baseline and computes percentage change from previous.
        Returns the parsed result with oi_change_pct and normalized score populated.
        """
        raw = await self.fetch()
        parsed = self.parse(raw)
        total_oi = parsed["detail"]["total_oi"]
        oi_change_pct = 0.0

        if redis_cache:
            baseline_key = f"{OI_BASELINE_KEY_PREFIX}:total"
            previous = await redis_cache.get_mve(baseline_key)
            if previous is not None and "total_oi" in previous:
                prev_oi = self._to_float(previous["total_oi"], 0.0)
                if prev_oi > 0:
                    oi_change_pct = round((total_oi - prev_oi) / prev_oi * 100, 2)
                for symbol in TRACKED_SYMBOLS:
                    sym_key = f"{OI_BASELINE_KEY_PREFIX}:{symbol}"
                    sym_data = parsed["detail"]["symbols"].get(symbol, {})
                    if sym_data.get("has_data"):
                        prev_sym = await redis_cache.get_mve(sym_key)
                        if prev_sym is not None and "open_interest" in prev_sym:
                            prev_oi_val = self._to_float(prev_sym["open_interest"], 0.0)
                            if prev_oi_val > 0:
                                parsed["detail"]["symbols"][symbol]["oi_change_pct"] = (
                                    round(
                                        (sym_data["open_interest"] - prev_oi_val)
                                        / prev_oi_val
                                        * 100,
                                        2,
                                    )
                                )

            await redis_cache.set_mve(
                baseline_key,
                {"total_oi": total_oi, "as_of": parsed["as_of"]},
                ttl=3600,
            )
            for symbol in TRACKED_SYMBOLS:
                sym_data = parsed["detail"]["symbols"].get(symbol, {})
                if sym_data.get("has_data"):
                    await redis_cache.set_mve(
                        f"{OI_BASELINE_KEY_PREFIX}:{symbol}",
                        {
                            "open_interest": sym_data["open_interest"],
                            "as_of": parsed["as_of"],
                        },
                        ttl=3600,
                    )

        parsed["detail"]["oi_change_pct"] = oi_change_pct
        score_val = self.score(parsed)
        parsed["normalized"] = score_val
        parsed["direction"] = 1 if score_val > 0 else (-1 if score_val < 0 else 0)
        parsed["magnitude"] = abs(score_val)
        self._last_successful_result = parsed
        self._last_poll_time = datetime.now(UTC)
        self._consecutive_errors = 0
        return parsed

    @staticmethod
    def _to_float(value, default=None):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
