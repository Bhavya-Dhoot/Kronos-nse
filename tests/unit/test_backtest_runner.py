from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from backtest.runner import BacktestRunner


@pytest.fixture
def config():
    return {
        "backtest": {
            "universe": "NIFTY50",
            "timeframe": "5min",
            "max_symbols": 2,
            "start_date": "2025-01-01",
            "end_date": "2025-01-05",
        },
        "collector": {"universe": "NIFTY50"},
    }


@pytest.fixture
def inference_ctx():
    ctx = MagicMock()
    ctx.db.get_candles = AsyncMock()
    ctx.context_builder.build = AsyncMock()
    return ctx


def _make_df(rows: int = 100) -> pd.DataFrame:
    import numpy as np

    idx = pd.date_range("2025-01-01", periods=rows, freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "open": np.linspace(100, 101, rows),
            "high": np.linspace(101, 102, rows),
            "low": np.linspace(99, 100, rows),
            "close": np.linspace(100, 101, rows),
            "volume": np.full(rows, 1000),
        },
        index=idx,
    )


@pytest.mark.asyncio
async def test_run_returns_report(config, inference_ctx):
    inference_ctx.db.get_candles.return_value = _make_df(200)
    inference_ctx.context_builder.build.return_value = {
        "symbol": "RELIANCE",
        "df": _make_df(200),
        "x_ts": pd.date_range("2025-01-01", periods=225, freq="5min"),
        "y_ts": pd.date_range("2025-01-01 18:45", periods=12, freq="5min"),
    }
    inference_ctx.engine.predict = AsyncMock(
        return_value={
            "symbol": "RELIANCE",
            "pred_close": [100.0 + i * 0.1 for i in range(12)],
            "model_version": "v1",
            "generated_at": "2025-01-01T00:00:00",
        }
    )
    runner = BacktestRunner(config, inference_ctx)
    report = await runner.run()
    assert "symbols_tested" in report
    assert "mean_mae" in report
    assert "mean_directional_acc" in report


@pytest.mark.asyncio
async def test_run_empty_df_skipped(config, inference_ctx):
    inference_ctx.db.get_candles.return_value = pd.DataFrame()
    runner = BacktestRunner(config, inference_ctx)
    report = await runner.run()
    assert report["mean_mae"] is None
    assert report["mean_directional_acc"] is None
