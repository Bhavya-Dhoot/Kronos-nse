"""GlobalMarketsCollector — polls global indices via yfinance every 300s.

8 tickers: US futures (ES, YM, NQ) + Asian indices (N225, HSI, SH, KS11) + DXY.
DXY has negative weight (strong USD = NSE headwind).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import yfinance as yf

from variance.base_collector import BaseVarianceCollector
from variance.schemas import ParseResult

_logger = logging.getLogger(__name__)

GLOBAL_TICKERS: dict[str, float] = {
    "ES=F": 0.30,
    "NQ=F": 0.20,
    "YM=F": 0.10,
    "^N225": 0.15,
    "^HSI": 0.12,
    "000001.SS": 0.08,
    "^KS11": 0.05,
    "DX-Y.NYB": -0.10,
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


class GlobalMarketsCollector(BaseVarianceCollector):
    """Poll global indices every 300s via yfinance."""

    def __init__(self) -> None:
        super().__init__(name="global_markets", poll_interval=300)

    async def fetch(self) -> dict[str, float | None]:
        """Fetch change_pct for all tickers via to_thread with 0.25s inter-request delay."""
        results: dict[str, float | None] = {}
        for ticker in GLOBAL_TICKERS:
            result = await asyncio.to_thread(_compute_change_pct, ticker)
            results[ticker] = result
            await asyncio.sleep(0.25)  # Rate-limit: max 4 req/s for yfinance
        return results

    def parse(self, raw: dict[str, float | None]) -> ParseResult:
        """Compute weighted average from individual ticker changes."""
        total_weight = 0.0
        weighted_sum = 0.0
        ticker_details: dict[str, Any] = {}

        for ticker, change_pct in raw.items():
            weight = GLOBAL_TICKERS.get(ticker, 0.0)
            ticker_details[ticker] = {
                "change_pct": change_pct,
                "weight": weight,
                "included": False,
            }

            if change_pct is not None:
                ticker_details[ticker]["included"] = True
                if weight >= 0:
                    total_weight += weight
                else:
                    total_weight += abs(weight)
                weighted_sum += change_pct * weight

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0

        return ParseResult(
            raw_value=round(composite, 4),
            normalized=0.0,
            direction=1 if composite > 0 else (-1 if composite < 0 else 0),
            magnitude=min(1.0, abs(composite)),
            detail={
                "tickers": ticker_details,
                "included_count": sum(
                    1 for d in ticker_details.values() if d["included"]
                ),
                "total_tickers": len(GLOBAL_TICKERS),
            },
            source="yfinance",
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Clamp weighted average to [-1.0, 1.0]."""
        return max(-1.0, min(1.0, float(parsed["raw_value"])))
