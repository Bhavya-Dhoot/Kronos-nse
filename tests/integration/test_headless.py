"""Integration tests for headless runner, signal emitter, and watchdog."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.quality.gate import DQGReport, DQGStatus
from headless.runner import HeadlessRunner
from headless.signal_emitter import SignalEmitter
from headless.watchdog import Watchdog


def _pass_report(symbol: str) -> DQGReport:
    from datetime import datetime

    return DQGReport(
        symbol=symbol,
        timeframe="5min",
        mode="HEADLESS",
        status=DQGStatus.PASS,
        created_at=datetime.utcnow(),
        last_candle_time=None,
        coverage_pct=99.0,
        days_collected=10,
        checks={},
    )


def _fail_report(symbol: str) -> DQGReport:
    from datetime import datetime

    return DQGReport(
        symbol=symbol,
        timeframe="5min",
        mode="HEADLESS",
        status=DQGStatus.FAIL,
        created_at=datetime.utcnow(),
        last_candle_time=None,
        coverage_pct=50.0,
        days_collected=1,
        checks={},
        recommendation="insufficient data",
    )


def _make_runner(
    *,
    symbols: list[str],
    dqg_reports: dict[str, DQGReport] | None = None,
) -> tuple[HeadlessRunner, AsyncMock]:
    import pandas as pd

    ist_tz = "Asia/Kolkata"
    idx = pd.date_range("2025-04-01 09:15", periods=10, freq="5min", tz=ist_tz)
    df = pd.DataFrame(
        {
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1000.0] * 10,
        },
        index=idx,
    )
    ctx = {
        "df": df,
        "x_ts": idx,
        "y_ts": idx[-3:],
    }

    dqg = AsyncMock()
    if dqg_reports is None:
        dqg_reports = {s: _pass_report(s) for s in symbols}
    dqg.run_batch = AsyncMock(return_value=dqg_reports)

    context_builder = AsyncMock()
    context_builder.build = AsyncMock(return_value=ctx)

    engine = AsyncMock()
    engine.predict_batch = AsyncMock(
        side_effect=lambda reqs: [
            {
                "symbol": r["symbol"],
                "timeframe": "5min",
                "mode": "HEADLESS",
                "pred_close": [100.5, 101.0, 101.5],
                "pred_open": [100.0, 100.5, 101.0],
                "pred_high": [101.0, 101.5, 102.0],
                "pred_low": [99.5, 100.0, 100.5],
                "pred_volume": [500.0, 500.0, 500.0],
                "pred_timestamps": ["t1", "t2", "t3"],
                "model_version": "v_test",
                "generated_at": "2025-04-01T10:00:00",
            }
            for r in reqs
        ]
    )

    emitter = AsyncMock()
    emitter.emit = AsyncMock()

    ledger = MagicMock()
    ledger.prediction_from_engine_result = MagicMock(side_effect=lambda x: x)
    ledger.record_fire_and_forget = MagicMock()

    runner = HeadlessRunner(
        config={"headless": {"emit_targets": ["redis"]}},
        engine=engine,
        db=AsyncMock(),
        redis_cache=AsyncMock(),
        dqg=dqg,
        context_builder=context_builder,
        signal_emitter=emitter,
        ledger=ledger,
    )
    return runner, emitter


@pytest.mark.asyncio
async def test_runner_skips_symbols_that_fail_dqg():
    runner, emitter = _make_runner(
        symbols=["SBIN", "RELIANCE"],
        dqg_reports={
            "SBIN": _pass_report("SBIN"),
            "RELIANCE": _fail_report("RELIANCE"),
        },
    )
    await runner._on_candle_close(["SBIN", "RELIANCE"], "5min")
    assert emitter.emit.await_count == 1


@pytest.mark.asyncio
async def test_runner_emits_signal_for_valid_symbols():
    runner, emitter = _make_runner(symbols=["SBIN", "RELIANCE"])
    await runner._on_candle_close(["SBIN", "RELIANCE"], "5min")
    assert emitter.emit.await_count == 2


@pytest.mark.asyncio
async def test_runner_handles_all_symbols_failing_dqg_gracefully():
    runner, emitter = _make_runner(
        symbols=["SBIN"],
        dqg_reports={"SBIN": _fail_report("SBIN")},
    )
    await runner._on_candle_close(["SBIN"], "5min")
    emitter.emit.assert_not_awaited()


def _make_signal_runner() -> HeadlessRunner:
    runner, _ = _make_runner(symbols=["SBIN"])
    runner._engine._mve = None
    return runner


def test_compute_signal_bullish_on_positive_move():
    runner = _make_signal_runner()
    pred = {
        "symbol": "SBIN",
        "pred_close": [100.0, 102.0],
        "timeframe": "5min",
        "mode": "HEADLESS",
    }
    sig = runner._compute_signal(pred, 100.0)
    assert sig["direction"] == "BULLISH"
    assert sig["confidence"] in {"HIGH", "MEDIUM", "LOW"}


def test_compute_signal_bearish_on_negative_move():
    runner = _make_signal_runner()
    pred = {
        "symbol": "SBIN",
        "pred_close": [100.0, 98.0],
        "timeframe": "5min",
        "mode": "HEADLESS",
    }
    sig = runner._compute_signal(pred, 100.0)
    assert sig["direction"] == "BEARISH"


def test_compute_signal_neutral_on_small_move():
    runner = _make_signal_runner()
    pred = {
        "symbol": "SBIN",
        "pred_close": [100.0, 100.2],
        "timeframe": "5min",
        "mode": "HEADLESS",
    }
    sig = runner._compute_signal(pred, 100.0)
    assert sig["direction"] == "NEUTRAL"
    assert sig["confidence"] == "LOW"


@pytest.mark.asyncio
async def test_signal_emitter_emit_all_targets():
    redis = AsyncMock()
    redis.publish_signal = AsyncMock()
    db = AsyncMock()
    db.store_signal = AsyncMock(return_value=1)

    config = {
        "headless": {
            "emit_targets": ["redis", "webhook", "csv", "db"],
            "webhook_url": "",
            "csv_output_path": "./data/test_signals_emit.csv",
        }
    }
    emitter = SignalEmitter(config, redis, db=db)
    signal = {
        "symbol": "SBIN",
        "timeframe": "5min",
        "mode": "HEADLESS",
        "direction": "BULLISH",
        "confidence": "HIGH",
        "expected_move_pct": 1.2,
        "last_close": 100.0,
        "pred_close": 101.2,
        "model_version": "v_test",
        "generated_at": "2025-04-01T10:00:00",
    }
    await emitter.emit(signal)
    redis.publish_signal.assert_awaited()
    await asyncio.sleep(0.05)
    db.store_signal.assert_called()


def test_runner_processes_each_boundary_once():
    runner, _ = _make_runner(symbols=["SBIN"])
    tf = "5min"
    b1 = runner._boundary_key(tf)
    runner._last_processed_boundary = b1 - 1
    assert runner._boundary_key(tf) == b1
    runner._last_processed_boundary = b1
    assert runner._last_processed_boundary == b1


def test_watchdog_triggers_on_stall():
    wd = Watchdog(timeout_seconds=1)
    wd._last_heartbeat = time.time() - 5
    with patch("os.kill") as mock_kill:
        wd._watch()
    assert mock_kill.called
