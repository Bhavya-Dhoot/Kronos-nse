"""Historical data ingestion pipeline for Angel One -> TimescaleDB."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from scripts.seed_instruments import get_universe

logger = logging.getLogger(__name__)


def _timeframe_minutes(tf: str) -> int:
    t = tf.strip().lower()
    if t in ("1d", "1day", "one_day"):
        return 1440
    if t in ("1h", "1hour", "one_hour"):
        return 60
    if t.endswith("min"):
        try:
            return int(t[:-3])
        except ValueError:
            pass
    if t.endswith("m"):
        try:
            return int(t[:-1])
        except ValueError:
            pass
    return 5


class HistoricalFetcher:
    """Fetches and persists historical candles for a symbol universe."""

    def __init__(self, client: Any, db: Any, config: dict[str, Any]) -> None:
        self.client = client
        self.db = db
        self.config = config
        collector_cfg = config.get("collector") or {}
        self.fetch_concurrency = int(collector_cfg.get("fetch_concurrency", 1))

    async def fetch_symbol(
        self,
        symbol: str,
        token: int | str,
        exchange: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
    ) -> int:
        """Fetch one symbol/timeframe and insert into DB."""
        t0 = time.monotonic()
        # Run the synchronous SmartAPI + rate limiter calls in a thread
        # to avoid blocking the asyncio event loop
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.get_historical_chunked,
                    symbol_token=str(token),
                    exchange=exchange,
                    interval=timeframe,
                    from_date=from_date,
                    to_date=to_date,
                ),
                timeout=300,
            )
        except TimeoutError:
            logger.error(
                "Timeout fetching %s %s (from=%s to=%s) — check network or increase timeout",
                symbol,
                timeframe,
                from_date,
                to_date,
            )
            return 0
        fetch_elapsed = time.monotonic() - t0
        if not rows:
            logger.warning(
                "No candles fetched for %s %s (%.1fs)", symbol, timeframe, fetch_elapsed
            )
            return 0

        candles: list[dict[str, Any]] = []
        violation_count = 0
        skipped = 0
        for row in rows:
            # Angel format: [timestamp, open, high, low, close, volume]
            try:
                ts = pd.Timestamp(row[0])
                if ts.tzinfo is None:
                    ts = ts.tz_localize("Asia/Kolkata")
                o, h, lo, c, v = (
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                )
            except Exception:
                skipped += 1
                continue

            # Sanitize OHLCV violations that would fail DB CHECK constraint:
            #   high >= open, high >= close, low <= open, low <= close, volume >= 0
            raw_valid = h >= o and h >= c and lo <= o and lo <= c and h >= lo and v >= 0
            if not raw_valid:
                violation_count += 1
                # Fix negative volume (common Angel One data issue)
                v = max(v, 0.0)
                # Fix high/low to satisfy constraints
                h = max(h, o, c)
                lo = min(lo, o, c)
                if h < lo:
                    # Degenerate candle — skip entirely
                    skipped += 1
                    continue

            candles.append(
                {
                    "time": ts.tz_convert("UTC").to_pydatetime(),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": v,
                    "is_adjusted": False,
                    "source": "angel_one",
                }
            )

        if violation_count:
            logger.warning(
                "%s %s: sanitized %d OHLCV violations, skipped %d degenerate rows",
                symbol,
                timeframe,
                violation_count,
                skipped,
            )

        inserted = await self.db.bulk_insert_candles(candles)
        total_elapsed = time.monotonic() - t0
        logger.info(
            "%s %s: fetched %d rows, inserted %d candles in %.1fs",
            symbol,
            timeframe,
            len(rows),
            int(inserted),
            total_elapsed,
        )
        return int(inserted)

    async def fetch_universe(
        self,
        universe_name: str,
        timeframes: list[str],
        from_date: datetime,
        to_date: datetime,
        concurrency: int | None = None,
    ) -> dict[str, dict[str, int]]:
        """Fetch all symbols/timeframes with bounded concurrency."""
        universe = get_universe(universe_name)
        if concurrency is None:
            concurrency = self.fetch_concurrency
        sem = asyncio.Semaphore(concurrency)
        out: dict[str, dict[str, int]] = {sym: {} for sym in universe}
        total_pairs = len(universe) * len(timeframes)
        completed = 0
        t_start = time.monotonic()

        async def _one(symbol: str, token: int, timeframe: str) -> None:
            nonlocal completed
            async with sem:
                logger.info(
                    "[%d/%d] Fetching %s %s ...",
                    completed + 1,
                    total_pairs,
                    symbol,
                    timeframe,
                )
                count = await self.fetch_symbol(
                    symbol=symbol,
                    token=token,
                    exchange="NSE",
                    timeframe=timeframe,
                    from_date=from_date,
                    to_date=to_date,
                )
                out[symbol][timeframe] = count
                completed += 1
                elapsed = time.monotonic() - t_start
                logger.info(
                    "[%d/%d] %s %s → %d candles (elapsed %.0fs)",
                    completed,
                    total_pairs,
                    symbol,
                    timeframe,
                    count,
                    elapsed,
                )

        tasks = [
            asyncio.create_task(_one(sym, token, tf))
            for sym, token in universe.items()
            for tf in timeframes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any per-symbol failures without aborting the whole run
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                sym_list = list(universe.keys())
                tf_idx = i % len(timeframes)
                sym_idx = i // len(timeframes)
                sym = sym_list[sym_idx] if sym_idx < len(sym_list) else "?"
                tf = timeframes[tf_idx] if tf_idx < len(timeframes) else "?"
                logger.error(
                    "FAILED: %s %s — %s: %s",
                    sym,
                    tf,
                    type(result).__name__,
                    result,
                )

        total_elapsed = time.monotonic() - t_start
        total_rows = sum(v for d in out.values() for v in d.values())
        failed_count = sum(1 for r in results if isinstance(r, Exception))
        logger.info(
            "Universe fetch complete: %d symbols × %d timeframes, "
            "%d total candles in %.1f minutes (%d failures)",
            len(universe),
            len(timeframes),
            total_rows,
            total_elapsed / 60,
            failed_count,
        )
        return out

    async def incremental_update(
        self, universe_name: str, timeframes: list[str]
    ) -> dict[str, dict[str, int]]:
        """Fetch only candles newer than current DB latest timestamp.

        Skips API calls when:
        - Market is closed and data already exists (no new data available)
        - Latest candle is recent enough that no new candle could have closed yet
        """
        from scripts.seed_instruments import is_market_open

        now_ts = pd.Timestamp.now(tz="Asia/Kolkata")
        now_ist = now_ts.to_pydatetime()
        market_open = is_market_open(now_ts)
        universe = get_universe(universe_name)
        out: dict[str, dict[str, int]] = {sym: {} for sym in universe}

        for symbol, token in universe.items():
            for tf in timeframes:
                latest = await self.db.get_latest_timestamp(symbol, tf)

                # Skip if data exists but market is closed — no new data possible
                if latest is not None and not market_open:
                    out[symbol][tf] = 0
                    continue

                # Skip if latest candle is too fresh for a new one to exist
                if latest is not None:
                    latest_ist = (
                        latest
                        if latest.tz is not None
                        else pd.Timestamp(latest)
                        .tz_localize("UTC")
                        .tz_convert("Asia/Kolkata")
                    )
                    age_seconds = (now_ts - latest_ist).total_seconds()
                    tf_min = _timeframe_minutes(tf)
                    min_age_for_fetch = max(tf_min * 0.8, 0.5) * 60
                    if age_seconds < min_age_for_fetch:
                        out[symbol][tf] = 0
                        continue

                if latest is None:
                    from data.collector.angel_client import AngelOneClient

                    lookback_days = AngelOneClient.max_chunk_days_for_interval(tf)
                    from_date = now_ist - timedelta(days=lookback_days)
                else:
                    from_date = (
                        pd.Timestamp(latest).tz_convert("Asia/Kolkata")
                        + pd.Timedelta(minutes=1)
                    ).to_pydatetime()
                count = await self.fetch_symbol(
                    symbol=symbol,
                    token=token,
                    exchange="NSE",
                    timeframe=tf,
                    from_date=from_date,
                    to_date=now_ist,
                )
                out[symbol][tf] = count
        return out
