from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from data.quality import checks
from data.quality.gate import DataQualityGate, DQGFailureError, DQGStatus
from tests.data_quality.conftest import (
    IST,
    make_clean_nse_df,
    make_df_with_gap,
    make_df_with_ohlcv_violation,
)


def test_check_coverage_clean_data_passes():
    df = make_clean_nse_df("SBIN", "1m", days=10, start_date=date(2025, 4, 1))
    res = checks.check_coverage(df, "1m")
    assert res["critical"] is True
    assert res["passed"] is True
    assert res["coverage_pct"] >= 90.0


def test_check_coverage_below_90_fails():
    df = make_clean_nse_df("SBIN", "1m", days=10, start_date=date(2025, 4, 1))
    # Drop random rows to reduce coverage below 90% without changing date range
    drop_idx = df.index[::4]  # drop every 4th row = ~25% reduction → well below 90%
    df2 = df.drop(drop_idx).copy()
    res = checks.check_coverage(df2, "1m")
    assert res["passed"] is False
    assert res["coverage_pct"] < 90.0


def test_check_no_critical_gaps_clean_passes():
    df = make_clean_nse_df("SBIN", "1m", days=3, start_date=date(2025, 4, 1))
    res = checks.check_no_critical_gaps(df, "1m")
    assert res["passed"] is True
    assert res["gap_count"] == 0


def test_check_no_critical_gaps_intraday_gap_fails():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    gap_start = df.index[50].to_pydatetime()
    df_gap = make_df_with_gap(df, gap_start, gap_minutes=30)
    res = checks.check_no_critical_gaps(df_gap, "1m")
    assert res["passed"] is False
    assert res["gap_count"] >= 1
    assert res["worst_gap_minutes"] >= 30


def test_check_no_critical_gaps_overnight_gap_passes():
    df = make_clean_nse_df("SBIN", "1m", days=2, start_date=date(2025, 4, 1))
    # big gap exists overnight by construction — should not be critical
    res = checks.check_no_critical_gaps(df, "1m")
    assert res["passed"] is True


def test_check_no_critical_gaps_holiday_gap_passes():
    # 2025-05-01 is an NSE holiday in our calendar
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 30))
    df2 = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 5, 2))
    combined = pd.concat([df, df2]).sort_index()
    res = checks.check_no_critical_gaps(combined, "1m")
    assert res["passed"] is True


def test_check_ohlcv_high_below_close_fails():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    bad = make_df_with_ohlcv_violation(df, 10, "high_below_close")
    res = checks.check_ohlcv_constraints(bad)
    assert res["passed"] is False
    assert res["violation_count"] >= 1


def test_check_ohlcv_low_above_open_fails():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    bad = make_df_with_ohlcv_violation(df, 10, "low_above_open")
    res = checks.check_ohlcv_constraints(bad)
    assert res["passed"] is False
    assert res["violation_count"] >= 1


def test_check_ohlcv_negative_volume_fails():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    bad = make_df_with_ohlcv_violation(df, 10, "negative_volume")
    res = checks.check_ohlcv_constraints(bad)
    assert res["passed"] is False
    assert res["violation_count"] >= 1


def test_check_ohlcv_clean_data_passes():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    res = checks.check_ohlcv_constraints(df)
    assert res["passed"] is True


def test_check_staleness_during_market_hours_old_data_fails(monkeypatch):
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    # Fake \"now\" to be during market hours on the same date, far after last candle
    fake_now = pd.Timestamp("2025-04-01 15:00:00", tz=IST)
    monkeypatch.setattr(
        checks.pd.Timestamp, "now", classmethod(lambda cls, tz=None: fake_now)
    )
    # Make last candle very old compared to now
    df2 = df.copy()
    df2.index = df2.index - pd.Timedelta(hours=3)
    res = checks.check_staleness(df2, threshold_seconds=30)
    assert res["passed"] is False


def test_check_staleness_outside_market_hours_always_passes(monkeypatch):
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    fake_now = pd.Timestamp("2025-04-01 20:00:00", tz=IST)  # outside market hours
    monkeypatch.setattr(
        checks.pd.Timestamp, "now", classmethod(lambda cls, tz=None: fake_now)
    )
    res = checks.check_staleness(df, threshold_seconds=30)
    assert res["passed"] is True


@pytest.mark.asyncio
async def test_dqg_gate_pass_on_clean_data():
    df = make_clean_nse_df("SBIN", "1m", days=10, start_date=date(2025, 4, 1))
    # Gate in VISUAL mode runs staleness during market hours; freeze time outside hours.
    import pandas as pd

    from data.quality import checks as checks_module

    checks_module.pd.Timestamp.now = classmethod(
        lambda cls, tz=None: pd.Timestamp("2025-04-01 20:00:00", tz=IST)
    )
    db = AsyncMock()
    db.get_candles = AsyncMock(return_value=df)
    db._pool = None  # skip DB persistence in unit test
    redis_cache = AsyncMock()
    redis_cache.set_dqg_report = AsyncMock()
    redis_cache.publish_dqg_status = AsyncMock()

    gate = DataQualityGate(
        config={"dqg": {"min_lookback_bars": 400}}, db=db, redis_cache=redis_cache
    )
    rep = await gate.run("SBIN", "1m", "VISUAL")

    assert rep.status == DQGStatus.PASS
    redis_cache.set_dqg_report.assert_called_once()


@pytest.mark.asyncio
async def test_dqg_gate_fail_on_insufficient_history():
    df = make_clean_nse_df("SBIN", "1m", days=2, start_date=date(2025, 4, 1))
    db = AsyncMock()
    db.get_candles = AsyncMock(return_value=df)
    db._pool = None
    redis_cache = AsyncMock()
    redis_cache.set_dqg_report = AsyncMock()
    redis_cache.publish_dqg_status = AsyncMock()

    gate = DataQualityGate(
        config={"dqg": {"min_lookback_bars": 400}}, db=db, redis_cache=redis_cache
    )
    rep = await gate.run("SBIN", "1m", "VISUAL")

    assert rep.status != DQGStatus.PASS
    assert rep.checks["min_history"]["passed"] is False


@pytest.mark.asyncio
async def test_dqg_gate_fail_on_critical_gap():
    df = make_clean_nse_df("SBIN", "1m", days=1, start_date=date(2025, 4, 1))
    df = make_df_with_gap(df, df.index[50].to_pydatetime(), gap_minutes=30)
    # add enough days to satisfy min_history (VISUAL requires 10 days)
    df2 = make_clean_nse_df("SBIN", "1m", days=10, start_date=date(2025, 4, 2))
    combined = pd.concat([df, df2]).sort_index()

    db = AsyncMock()
    db.get_candles = AsyncMock(return_value=combined)
    db._pool = None
    redis_cache = AsyncMock()
    redis_cache.set_dqg_report = AsyncMock()
    redis_cache.publish_dqg_status = AsyncMock()

    gate = DataQualityGate(
        config={"dqg": {"min_lookback_bars": 400}}, db=db, redis_cache=redis_cache
    )
    rep = await gate.run("SBIN", "1m", "VISUAL")

    assert rep.status != DQGStatus.PASS
    assert rep.checks["no_critical_gaps"]["passed"] is False


@pytest.mark.asyncio
async def test_dqg_gate_assert_pass_raises_on_fail():
    df = make_clean_nse_df("SBIN", "1m", days=2, start_date=date(2025, 4, 1))
    db = AsyncMock()
    db.get_candles = AsyncMock(return_value=df)
    db._pool = None
    redis_cache = AsyncMock()
    redis_cache.set_dqg_report = AsyncMock()
    redis_cache.publish_dqg_status = AsyncMock()

    gate = DataQualityGate(
        config={"dqg": {"min_lookback_bars": 400}}, db=db, redis_cache=redis_cache
    )

    with pytest.raises(DQGFailureError):
        await gate.assert_pass("SBIN", "1m", "VISUAL")
