"""Top-level application entrypoint for Kronos NSE."""

from __future__ import annotations

import argparse
import asyncio
import enum
import logging
import os
import sys

from api.main import app as fastapi_app

import yaml
from data.storage.redis_cache import RedisCache
from variance.collectors import (
    FIIDIICollector, GIFTNiftyCollector, GlobalMarketsCollector,
    MacroCollector, OICollector, OptionsCollector, VIXCollector,
)
from variance.engine import MarketVarianceEngine

logger = logging.getLogger(__name__)


class AppMode(str, enum.Enum):
    COLLECT = "COLLECT"
    BACKTEST = "BACKTEST"
    VISUAL = "VISUAL"
    HEADLESS = "HEADLESS"
    TRAIN = "TRAIN"
    PAPER = "PAPER"


def get_mode() -> AppMode:
    raw = os.getenv("APP_MODE", "COLLECT").upper()
    try:
        return AppMode(raw)
    except ValueError:
        return AppMode.COLLECT


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def _async_main() -> None:
    from headless.runtime import ApplicationRuntime

    mode = get_mode()
    runtime = ApplicationRuntime(mode.value)
    try:
        await runtime.start()
    finally:
        await runtime.shutdown()


async def _run_standalone_mve(variance_cfg: dict[str, Any]) -> None:
    """Start MVE engine standalone (no API server per D-17)."""
    import signal

    redis = RedisCache()
    await redis.initialize()

    collectors = {
        "vix": VIXCollector(),
        "options": OptionsCollector(),
        "fii_dii": FIIDIICollector(),
        "oi": OICollector(),
        "gift_nifty": GIFTNiftyCollector(),
        "global_markets": GlobalMarketsCollector(),
        "macro": MacroCollector(),
    }

    engine = MarketVarianceEngine(
        collectors=collectors,
        redis_cache=redis,
        config=variance_cfg,
    )

    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows fallback
            pass

    await engine.start()
    logger.info("Standalone MVE running (ready=%s, degraded=%s)", engine.is_ready, engine.is_degraded)

    try:
        await shutdown_event.wait()
    finally:
        await engine.stop()
        await redis.close()
        logger.info("Standalone MVE stopped")


def main() -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(description="Kronos NSE")
    parser.add_argument(
        "--collect-task",
        choices=["loop", "incremental", "bootstrap", "live"],
        help="COLLECT mode task (overrides COLLECT_TASK env)",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in AppMode],
        help="Operating mode (overrides APP_MODE env)",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Run historical bootstrap before collect loop",
    )
    parser.add_argument(
        "--standalone-mve",
        action="store_true",
        help="Run MVE standalone in COLLECT/HEADLESS mode (no API server)",
    )
    args, _ = parser.parse_known_args()
    if args.collect_task:
        os.environ["COLLECT_TASK"] = args.collect_task
    if args.mode:
        os.environ["APP_MODE"] = args.mode
    if args.bootstrap:
        os.environ["BOOTSTRAP"] = "true"

    # ── Standalone MVE mode (COLLECT/HEADLESS, no API) per D-17 ──────
    standalone_mve = args.standalone_mve or os.getenv("STANDALONE_MVE", "").lower() in ("1", "true")
    if standalone_mve:
        logger = logging.getLogger(__name__)
        mode = get_mode()
        logger.info("Standalone MVE mode — starting engine (app_mode=%s)", mode.value)
        try:
            with open("config/base.yaml") as f:
                raw_cfg = yaml.safe_load(f)
            variance_cfg = raw_cfg.get("variance", {})

            asyncio.run(_run_standalone_mve(variance_cfg))
        except KeyboardInterrupt:
            logger.info("Standalone MVE shutdown requested")
        return  # Don't proceed to normal API/async_main startup

    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        sys.exit(0)


app = fastapi_app


if __name__ == "__main__":
    main()
