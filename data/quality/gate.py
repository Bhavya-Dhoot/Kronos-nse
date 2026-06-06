"""Data Quality Gate (DQG) orchestrator for Kronos NSE."""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from data.quality.checks import (
    check_coverage,
    check_corporate_action_suspected,
    check_lookback_sufficient,
    check_min_history,
    check_mve_health,
    check_no_critical_gaps,
    check_ohlcv_constraints,
    check_outliers,
    check_staleness,
    check_volume_sanity,
)

logger = logging.getLogger(__name__)


class DQGStatus(str, enum.Enum):
    NOT_RUN = "NOT_RUN"
    COLLECTING = "COLLECTING"
    PARTIAL = "PARTIAL"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(slots=True)
class DQGReport:
    symbol: str
    timeframe: str
    mode: str
    status: DQGStatus
    created_at: datetime
    last_candle_time: str | None
    coverage_pct: float | None
    days_collected: int
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    recommendation: str | None = None


class DQGFailureError(Exception):
    """Raised when DQG blocks inference."""

    def __init__(self, report: DQGReport) -> None:
        super().__init__(f"DQG blocked inference: {report.symbol} {report.timeframe} {report.status}")
        self.report = report


class DataQualityGate:
    """Runs DQG checks and persists the report to Redis + DB."""

    def __init__(self, config: dict[str, Any], db: Any, redis_cache: Any, mve: Any | None = None) -> None:
        self._config = config
        self._db = db
        self._redis = redis_cache
        self._mve = mve

    async def run(self, symbol: str, timeframe: str, mode: str) -> DQGReport:
        mode_u = mode.upper()
        dqg_cfg = (self._config.get("dqg") or {}) if isinstance(self._config, dict) else {}

        # 1. Fetch data (last 10000 candles — enough for DQG checks)
        df: pd.DataFrame = await self._db.get_candles(symbol, timeframe, limit=10000)
        last_candle_time = df.index.max().isoformat() if not df.empty else None

        # days collected (trading days with any data)
        if df.empty:
            days_collected = 0
        else:
            days_collected = len(set(df.index.normalize().date))

        checks: dict[str, dict[str, Any]] = {}

        # 2. Run checks appropriate for mode
        checks["min_history"] = check_min_history(df, mode_u)
        checks["coverage"] = check_coverage(df, timeframe, mode_u)
        checks["no_critical_gaps"] = check_no_critical_gaps(df, timeframe)
        checks["ohlcv_valid"] = check_ohlcv_constraints(df)
        checks["lookback_ok"] = check_lookback_sufficient(df, required=int(dqg_cfg.get("min_lookback_bars", 400)))

        # warnings
        checks["outliers"] = check_outliers(df)
        checks["corporate_action_suspected"] = check_corporate_action_suspected(df)
        checks["volume_sanity"] = check_volume_sanity(df)

        # staleness only in VISUAL/HEADLESS modes
        if mode_u in {"VISUAL", "HEADLESS"}:
            checks["staleness"] = check_staleness(
                df,
                threshold_seconds=int(dqg_cfg.get("max_staleness_seconds_live", 30)),
            )

        # MVE health check (warning-level, non-critical)
        checks["mve_health"] = check_mve_health(self._mve)

        # 3. Determine overall status
        if df.empty:
            status = DQGStatus.FAIL
        else:
            critical = {k: v for k, v in checks.items() if v.get("critical") is True}
            passed_critical = [k for k, v in critical.items() if v.get("passed") is True]
            if len(passed_critical) == len(critical):
                status = DQGStatus.PASS
            elif len(passed_critical) > 0:
                status = DQGStatus.PARTIAL
            else:
                status = DQGStatus.FAIL

        coverage_pct = checks.get("coverage", {}).get("coverage_pct")

        recommendation = None
        if status != DQGStatus.PASS:
            recommendation = "Resolve failing critical checks before running inference."

        report = DQGReport(
            symbol=symbol,
            timeframe=timeframe,
            mode=mode_u,
            status=status,
            created_at=datetime.utcnow(),
            last_candle_time=last_candle_time,
            coverage_pct=float(coverage_pct) if coverage_pct is not None else None,
            days_collected=int(days_collected),
            checks=checks,
            recommendation=recommendation,
        )

        # 4. Store report in Redis
        await self._redis.set_dqg_report(symbol, timeframe, asdict(report), ttl=60)
        await self._redis.publish_dqg_status(symbol, asdict(report))

        # 5. Store report in DB (async, non-blocking)
        asyncio.create_task(self._store_report_db(report))

        return report

    async def _store_report_db(self, report: DQGReport) -> None:
        try:
            pool = getattr(self._db, "_pool", None)
            if pool is None:
                return
            sql = """
                INSERT INTO dqg_reports
                    (symbol, timeframe, mode, status, coverage_pct, days_collected, checks, recommendation, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, NOW())
            """
            payload = {
                "status": report.status.value,
                "checks": report.checks,
                "last_candle_time": report.last_candle_time,
            }
            import json

            async with pool.acquire() as conn:
                await conn.execute(
                    sql,
                    report.symbol,
                    report.timeframe,
                    report.mode,
                    report.status.value,
                    report.coverage_pct,
                    report.days_collected,
                    json.dumps(payload),
                    report.recommendation,
                )
        except Exception:
            logger.exception("Failed to store DQG report in DB")

    async def run_batch(self, symbols: list[str], timeframe: str, mode: str) -> dict[str, DQGReport]:
        sem = asyncio.Semaphore(10)
        async def _run(s: str) -> DQGReport:
            async with sem:
                return await self.run(s, timeframe, mode)
        results = await asyncio.gather(*(_run(s) for s in symbols))
        return {r.symbol: r for r in results}

    async def assert_pass(self, symbol: str, timeframe: str, mode: str) -> None:
        report = await self.run(symbol, timeframe, mode)
        if report.status != DQGStatus.PASS:
            raise DQGFailureError(report)

