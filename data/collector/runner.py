"""Collection runner: incremental updates, live feed, and scheduled COLLECT loop."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta

import pandas as pd

from data.collector.context import (
    CollectorContext,
    build_collector_context,
    close_collector_context,
)
from data.collector.live_feed import LiveFeedConsumer
from scripts.seed_instruments import get_universe, is_market_open

logger = logging.getLogger(__name__)
IST = "Asia/Kolkata"


class CollectionRunner:
    """Orchestrates historical and live data collection."""

    def __init__(self, ctx: CollectorContext) -> None:
        self.ctx = ctx
        collector_cfg = (
            (ctx.config.get("collector") or {}) if isinstance(ctx.config, dict) else {}
        )
        self.universe = str(
            collector_cfg.get(
                "universe", ctx.config.get("data", {}).get("universe", "NIFTY50")
            )
        )
        self.timeframes: list[str] = list(
            collector_cfg.get("timeframes", ["5min", "15min", "1day"])
        )
        self.fetch_concurrency = int(collector_cfg.get("fetch_concurrency", 1))
        self.live_timeframe = str(collector_cfg.get("live_candle_timeframe", "5min"))
        self.incremental_interval_minutes = int(
            collector_cfg.get("incremental_interval_minutes", 60)
        )
        self._stop = asyncio.Event()
        self._live: LiveFeedConsumer | None = None

    def request_stop(self) -> None:
        self._stop.set()

    async def run_incremental(self) -> dict[str, dict[str, int]]:
        logger.info("Running incremental update for %s", self.universe)
        return await self.ctx.fetcher.incremental_update(self.universe, self.timeframes)

    async def run_bootstrap(
        self,
        *,
        years: int = 5,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        timeframes: list[str] | None = None,
    ) -> dict[str, dict[str, int]]:
        to_date = to_date or datetime.now()
        from_date = from_date or (to_date - timedelta(days=365 * years))
        tfs = timeframes or self.timeframes
        logger.info(
            "Bootstrap %s from %s to %s",
            self.universe,
            from_date.date(),
            to_date.date(),
        )
        return await self.ctx.fetcher.fetch_universe(
            self.universe,
            tfs,
            from_date,
            to_date,
            concurrency=self.fetch_concurrency,
        )

    async def run_live(self) -> None:
        universe = get_universe(self.universe)
        symbols = [{"symbol": sym, "token": tok} for sym, tok in universe.items()]
        self._live = LiveFeedConsumer(
            client=self.ctx.client,
            db=self.ctx.db,
            redis_cache=self.ctx.redis,
            config=self.ctx.config,
            candle_timeframe=self.live_timeframe,
        )
        logger.info("Starting live feed for %d symbols", len(symbols))
        await self._live.start(symbols)
        await self._stop.wait()
        await self._live.stop()
        self._live = None

    async def run_collect_loop(self) -> None:
        """COLLECT mode: incremental on schedule; live feed during market hours."""
        last_incremental: datetime | None = None
        live_task: asyncio.Task | None = None

        try:
            await self.run_incremental()
            last_incremental = datetime.now()
        except Exception:
            logger.exception("Initial incremental update failed")

        while not self._stop.is_set():
            now = pd.Timestamp.now(tz=IST).to_pydatetime()
            market_open = is_market_open(now)

            if market_open and live_task is None:
                logger.info("Market open — starting live feed")
                live_task = asyncio.create_task(self.run_live())
            elif not market_open and live_task is not None:
                logger.info("Market closed — stopping live feed")
                if self._live:
                    await self._live.stop()
                    self._live = None
                live_task.cancel()
                try:
                    await live_task
                except asyncio.CancelledError:
                    pass
                live_task = None

            due_incremental = last_incremental is None or (
                now - last_incremental
            ) >= timedelta(minutes=self.incremental_interval_minutes)
            if due_incremental and not market_open:
                try:
                    counts = await self.run_incremental()
                    logger.info(
                        "Incremental update complete: %d symbol entries",
                        sum(len(v) for v in counts.values()),
                    )
                except Exception:
                    logger.exception("Incremental update failed")
                last_incremental = now

            await asyncio.sleep(30)

        if live_task:
            live_task.cancel()
            try:
                await live_task
            except asyncio.CancelledError:
                pass


async def run_collect_mode(task: str = "loop") -> None:
    """Entry for APP_MODE=COLLECT."""
    ctx = await build_collector_context()
    runner = CollectionRunner(ctx)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.request_stop)
        except NotImplementedError:
            # Windows
            pass

    try:
        if task == "incremental":
            await runner.run_incremental()
        elif task == "bootstrap":
            await runner.run_bootstrap()
        elif task == "live":
            await runner.run_live()
        else:
            await runner.run_collect_loop()
    finally:
        if runner._live:
            await runner._live.stop()
        await close_collector_context(ctx)
