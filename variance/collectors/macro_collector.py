"""MacroCollector — polls macro indicators via yfinance every 300s.

4 tickers: USD/INR, Brent Crude, Gold, US 10Y.
All macro is inverse — rising price = bearish for India per MAC-02.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from variance.base_collector import BaseVarianceCollector
from variance.schemas import ParseResult

_logger = logging.getLogger(__name__)

MACRO_TICKERS: dict[str, float] = {
    "USDINR=X": 0.35,
    "CL=F": 0.30,
    "GC=F": 0.15,
    "^TNX": 0.20,
}


def _compute_change_pct(ticker: str) -> float | None:
    """Fetch ticker change percentage via yfinance.

    Returns change_pct = (latest_close - prev_close) / prev_close * 100
    or None on failure (network error, missing data, NaN).
    """
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty or len(hist) < 2:
            return None
        closes = hist["Close"].values
        prev_close = float(closes[-2])
        latest_close = float(closes[-1])
        if prev_close <= 0:
            return None
        return round((latest_close - prev_close) / prev_close * 100, 4)
    except Exception:
        _logger.warning("Failed to fetch ticker %s", ticker, exc_info=True)
        return None


class MacroCollector(BaseVarianceCollector):
    """Poll macro indicators every 300s via yfinance.

    All macro is inverse per MAC-02: rising = bearish for India.
    Final score = -(weighted_avg), clamped to [-1.0, 1.0].
    """

    def __init__(self) -> None:
        super().__init__(name="macro", poll_interval=300)

    async def fetch(self) -> dict[str, float | None]:
        """Fetch change_pct for all macro tickers via to_thread."""
        results: dict[str, float | None] = {}
        for ticker in MACRO_TICKERS:
            result = await asyncio.to_thread(_compute_change_pct, ticker)
            results[ticker] = result
        return results

    def parse(self, raw: dict[str, float | None]) -> ParseResult:
        """Compute weighted average, then invert (all macro is inverse)."""
        total_weight = 0.0
        weighted_sum = 0.0
        ticker_details: dict[str, Any] = {}

        for ticker, change_pct in raw.items():
            weight = MACRO_TICKERS.get(ticker, 0.0)
            ticker_details[ticker] = {
                "change_pct": change_pct,
                "weight": weight,
                "included": False,
            }

            if change_pct is not None:
                ticker_details[ticker]["included"] = True
                total_weight += weight
                weighted_sum += change_pct * weight

        raw_composite = weighted_sum / total_weight if total_weight > 0 else 0.0
        composite = -raw_composite  # All macro is inverse per D-15

        return ParseResult(
            raw_value=round(composite, 4),
            normalized=0.0,
            direction=1 if composite > 0 else (-1 if composite < 0 else 0),
            magnitude=min(1.0, abs(composite)),
            detail={
                "tickers": ticker_details,
                "raw_composite": round(raw_composite, 4),
                "included_count": sum(1 for d in ticker_details.values() if d["included"]),
                "total_tickers": len(MACRO_TICKERS),
            },
            source="yfinance",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Clamp inverted composite to [-1.0, 1.0]."""
        return max(-1.0, min(1.0, float(parsed["raw_value"])))
