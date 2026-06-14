"""Application runtime orchestration for all APP_MODE variants."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import uvicorn

from api.main import create_app
from data.collector.context import (
    build_collector_context,
    close_collector_context,
    load_config,
)
from data.collector.runner import CollectionRunner
from data.quality.gate import DataQualityGate
from headless.ledger import PredictionLedger
from headless.runner import HeadlessRunner
from headless.signal_emitter import SignalEmitter
from headless.watchdog import Watchdog
from model.factory import build_inference_context, close_inference_context
from scripts.seed_instruments import get_universe

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "storage",
    "migrations",
)


class ApplicationRuntime:
    """Wires collector, inference, headless runner, API, and training per mode."""

    def __init__(self, mode: str) -> None:
        self.mode = mode.upper()
        self.config = load_config()
        self.collector_ctx: Any = None
        self.inference_ctx: Any = None
        self.collector: CollectionRunner | None = None
        self.headless: HeadlessRunner | None = None
        self.watchdog: Watchdog | None = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all services for the active mode."""
        if self.mode in {"COLLECT", "VISUAL", "HEADLESS", "PAPER"}:
            self.collector_ctx = await build_collector_context(authenticate=False)
            # Run migrations BEFORE any collector/DQG queries start
            await self.collector_ctx.db.run_migrations(_MIGRATIONS_DIR)
            # Authenticate AFTER migrations (avoids rate-limit races)
            if not self.collector_ctx.client.authenticate():
                raise RuntimeError(
                    "Angel One authentication failed; check .env credentials."
                )
            self.collector = CollectionRunner(self.collector_ctx)
            if self.mode in {"COLLECT", "VISUAL"}:
                self._tasks.append(asyncio.create_task(self._dqg_publish_loop()))

        if self.mode in {"VISUAL", "HEADLESS", "PAPER"}:
            self.inference_ctx = await build_inference_context(
                config=self.config,
                db=self.collector_ctx.db if self.collector_ctx else None,
                redis=self.collector_ctx.redis if self.collector_ctx else None,
            )

        if self.mode in {"HEADLESS", "PAPER"}:
            await self._start_headless()

        if self.mode == "TRAIN":
            await self._run_training()
            return

        if self.mode == "BACKTEST":
            await self._run_backtest()
            return

        if self.mode == "VISUAL":
            self._start_collect_background()

        if self.mode in {"VISUAL", "HEADLESS", "PAPER"}:
            await self._serve_api()
            return

        if self.mode == "COLLECT":
            await self._run_collect()

    async def shutdown(self) -> None:
        """Stop all background tasks and release resources."""
        if self.collector:
            self.collector.request_stop()
        if self.headless:
            await self.headless.stop()
        if self.watchdog:
            self.watchdog.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.inference_ctx:
            await close_inference_context(self.inference_ctx)
        if self.collector_ctx:
            await close_collector_context(self.collector_ctx)

    def _start_collect_background(self) -> None:
        """Start incremental/live collection loop without blocking the API server."""
        assert self.collector is not None
        bootstrap = os.getenv("BOOTSTRAP", "").lower() in {"1", "true", "yes"}

        async def _loop() -> None:
            if bootstrap:
                await self.collector.run_bootstrap()
            await self.collector.run_collect_loop()

        self._tasks.append(asyncio.create_task(_loop()))

    async def _run_collect(self) -> None:
        assert self.collector is not None
        bootstrap = os.getenv("BOOTSTRAP", "").lower() in {"1", "true", "yes"}
        if bootstrap:
            await self.collector.run_bootstrap()
        task = os.getenv("COLLECT_TASK", "loop")
        if task == "incremental":
            await self.collector.run_incremental()
        elif task == "live":
            await self.collector.run_live()
        else:
            await self.collector.run_collect_loop()

    async def _dqg_publish_loop(self) -> None:
        """Continuously run DQG for universe and publish to Redis."""
        assert self.collector_ctx is not None
        dqg = DataQualityGate(
            config=self.config,
            db=self.collector_ctx.db,
            redis_cache=self.collector_ctx.redis,
        )
        universe = str((self.config.get("collector") or {}).get("universe", "NIFTY50"))
        symbols = list(get_universe(universe).keys())
        timeframe = str(
            (self.config.get("collector") or {}).get("live_candle_timeframe", "5min")
        )

        while True:
            try:
                await dqg.run_batch(symbols[:10], timeframe, self.mode)
            except Exception:
                logger.exception("DQG publish loop error")
            await asyncio.sleep(300)

    async def _start_headless(self) -> None:
        assert self.inference_ctx is not None
        ctx = self.inference_ctx
        ledger = PredictionLedger(ctx.db)
        emitter = SignalEmitter(self.config, ctx.redis, db=ctx.db)
        headless_cfg = self.config.get("headless") or {}
        self.watchdog = Watchdog(
            timeout_seconds=int(headless_cfg.get("watchdog_timeout", 120))
        )
        self.watchdog.start()

        self.headless = HeadlessRunner(
            config=self.config,
            engine=ctx.engine,
            db=ctx.db,
            redis_cache=ctx.redis,
            dqg=ctx.dqg,
            context_builder=ctx.context_builder,
            signal_emitter=emitter,
            ledger=ledger,
            watchdog=self.watchdog,
        )
        universe = str((self.config.get("collector") or {}).get("universe", "NIFTY50"))
        symbols = list(get_universe(universe).keys())
        tf = str(
            (self.config.get("collector") or {}).get("live_candle_timeframe", "5min")
        )
        self._tasks.append(
            asyncio.create_task(self.headless.run(symbols, timeframe=tf))
        )
        self._tasks.append(asyncio.create_task(self._daily_resolve_loop(symbols)))

        if self.collector and self.mode in {"HEADLESS", "PAPER"}:
            self._start_collect_background()

    async def _daily_resolve_loop(self, symbols: list[str]) -> None:
        while True:
            await asyncio.sleep(3600)
            if self.headless:
                try:
                    await self.headless.resolve_yesterday_predictions(symbols)
                except Exception:
                    logger.exception("Daily prediction resolution failed")

    async def _serve_api(self) -> None:
        app = create_app(inference_override=self.inference_ctx)
        app.state.operating_mode = self.mode
        host = os.getenv("API_HOST", "0.0.0.0")
        port = int(os.getenv("API_PORT", "8000"))
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _run_training(self) -> None:
        from training.drift_detector import DriftDetector
        from training.scheduler import RetrainingScheduler

        self.inference_ctx = await build_inference_context(
            config=self.config, run_migrations=False
        )
        scheduler = RetrainingScheduler(
            self.config,
            self.inference_ctx.registry,
            DriftDetector(self.inference_ctx.db, self.config),
            db=self.inference_ctx.db,
        )
        await scheduler._execute_training()
        logger.info("TRAIN mode complete")

    async def _run_backtest(self) -> None:
        from backtest.runner import BacktestRunner

        self.inference_ctx = await build_inference_context(config=self.config)
        runner = BacktestRunner(self.config, self.inference_ctx)
        report = await runner.run()
        logger.info("Backtest complete: %s", report)
