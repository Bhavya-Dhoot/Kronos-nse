"""Bootstrap historical OHLCV data for Kronos NSE with strict validation.

Defaults are tuned for accuracy:
  - 5 years of 5-min candles for Nifty 50
  - chunked fetches with truncation detection (SmartAPI can silently truncate)

Usage:
  python scripts/bootstrap_historical.py --universe NIFTY50
  python scripts/bootstrap_historical.py --universe NIFTY50 --years 5
  python scripts/bootstrap_historical.py --universe NIFTY50 --from-date 2016-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.collector.context import build_collector_context, close_collector_context
from data.collector.runner import CollectionRunner
from data.quality.gate import DataQualityGate
from data.quality.reporter import DQGReporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def async_main(
    universe: str,
    years: int,
    from_date: datetime | None,
    to_date: datetime | None,
    timeframes: list[str],
    concurrency: int = 1,
) -> int:
    import time as _time

    t0 = _time.time()
    ctx = await build_collector_context()
    ctx.config.setdefault("collector", {})["universe"] = universe
    runner = CollectionRunner(ctx)

    try:
        logger.info(
            "Starting bootstrap: universe=%s years=%d timeframes=%s concurrency=%d",
            universe,
            years,
            timeframes,
            concurrency,
        )
        counts = await runner.run_bootstrap(
            years=years,
            from_date=from_date,
            to_date=to_date,
            timeframes=timeframes,
        )

        # Summary
        total_candles = sum(v for d in counts.values() for v in d.values())
        symbols_with_data = sum(
            1 for d in counts.values() if any(v > 0 for v in d.values())
        )
        elapsed = _time.time() - t0
        logger.info(
            "Bootstrap complete: %d/%d symbols with data, %d total candles in %.1f minutes",
            symbols_with_data,
            len(counts),
            total_candles,
            elapsed / 60,
        )
        logger.info("Bootstrap counts: %s", counts)

        gate = DataQualityGate(config=ctx.config, db=ctx.db, redis_cache=ctx.redis)
        reports = await gate.run_batch(
            list(counts.keys()), timeframe="5min", mode="COLLECT"
        )

        reporter = DQGReporter()
        json_report = reporter.generate_json_report(reports)

        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)  # noqa: ASYNC240
        outfile = reports_dir / f"bootstrap_dqg_{datetime.now().date()}.json"
        outfile.write_text(
            json.dumps(json_report, indent=2, default=str), encoding="utf-8"
        )
        logger.info("DQG report written to %s", outfile)
        return 0
    except Exception:
        logger.exception("Bootstrap failed")
        return 1
    finally:
        await close_collector_context(ctx)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="NIFTY50")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument(
        "--from-date", default=None, help="YYYY-MM-DD (overrides --years)"
    )
    parser.add_argument(
        "--to-date", default=None, help="YYYY-MM-DD (defaults to today)"
    )
    parser.add_argument(
        "--timeframes", default="5min", help="Comma-separated list (default: 5min)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent symbol fetches (default: 1)",
    )
    args = parser.parse_args()
    f = datetime.fromisoformat(args.from_date) if args.from_date else None
    t = datetime.fromisoformat(args.to_date) if args.to_date else None
    tfs = [x.strip() for x in str(args.timeframes).split(",") if x.strip()]
    sys.exit(
        asyncio.run(
            async_main(args.universe.upper(), args.years, f, t, tfs, args.concurrency)
        )
    )


if __name__ == "__main__":
    main()
