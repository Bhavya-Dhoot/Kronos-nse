from __future__ import annotations

import asyncio
import time
from datetime import datetime
from datetime import time as market_time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from data.quality.gate import DQGFailureError, DQGReport, DQGStatus
from model.context_builder import ContextBuilder
from model.engine import KronosEngine
from model.predictor import PredictionError, clip_ohlcv_dataframe
from model.registry import ModelRegistry
from scripts.seed_instruments import is_trading_day

IST = "Asia/Kolkata"


def _make_registry(tmp_path: Path) -> ModelRegistry:
    reg = ModelRegistry(tmp_path)
    tok = tmp_path / "tok_src"
    pred = tmp_path / "pred_src"
    tok.mkdir()
    pred.mkdir()
    (tok / "config.json").write_text("{}", encoding="utf-8")
    (pred / "config.json").write_text("{}", encoding="utf-8")
    version = reg.register_checkpoint(
        tok, pred, {"val_mae": 0.01, "val_directional_acc": 0.55}
    )
    reg.promote_to_production(version)
    return reg


def _sample_df(rows: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2025-04-01 09:15", periods=rows, freq="5min", tz=IST)
    return pd.DataFrame(
        {
            "open": np.linspace(100, 101, rows),
            "high": np.linspace(101, 102, rows),
            "low": np.linspace(99, 100, rows),
            "close": np.linspace(100.5, 101.5, rows),
            "volume": np.full(rows, 1000.0),
        },
        index=idx,
    )


class MockKronosModel:
    def eval(self):
        return self

    def half(self):
        return self

    def to(self, *args, **kwargs):
        return self


class MockKronosPredictor:
    def __init__(self, output_df: pd.DataFrame | None = None, with_nan: bool = False):
        self.output_df = output_df
        self.with_nan = with_nan

    def predict(
        self, df, x_timestamp, y_timestamp, pred_len, sample_count, temperature
    ):
        if self.output_df is not None:
            out = self.output_df.copy()
        else:
            idx = y_timestamp[:pred_len]
            out = pd.DataFrame(
                {
                    "open": [100.0] * pred_len,
                    "high": [101.0] * pred_len,
                    "low": [99.0] * pred_len,
                    "close": [100.5] * pred_len,
                    "volume": [500.0] * pred_len,
                },
                index=idx,
            )
        if self.with_nan:
            out.loc[out.index[0], "close"] = np.nan
        return out


@pytest.fixture
async def engine_setup(tmp_path):
    reg = _make_registry(tmp_path)
    redis = AsyncMock()
    redis.get_prediction = AsyncMock(return_value=None)
    redis.set_prediction = AsyncMock()
    redis.publish_prediction = AsyncMock()

    config = {
        "model": {
            "device": "cpu",
            "dtype": "float16",
            "default_sample_count": 2,
            "default_temperature": 0.7,
            "default_pred_len": 3,
        }
    }

    class TestPredictor:
        def __init__(self):
            self._inner = MockKronosPredictor()

        def predict(
            self,
            df,
            x_ts,
            y_ts,
            pred_len=None,
            temperature=None,
            sample_count=None,
            vix_level=None,
        ):
            pred_df = self._inner.predict(df, x_ts, y_ts, pred_len or 3, 2, 0.7)
            return pred_df, {"sample_count": 2, "temperature": 0.7, "confidence": 0.75}

    def loader_fn(paths):
        return TestPredictor()

    engine = KronosEngine(
        config=config,
        registry=reg,
        redis_cache=redis,
        model_loader=loader_fn,
        watcher_interval_s=3600,
    )
    return engine, redis


@pytest.mark.asyncio
async def test_engine_returns_cached_result_on_second_call(engine_setup):
    engine, redis = engine_setup
    df = _sample_df()
    x_ts = df.index
    y_ts = pd.date_range(df.index[-1], periods=3, freq="5min", tz=IST)[1:]

    cached_payload = {"symbol": "SBIN", "pred_close": [1, 2, 3], "cached": True}
    redis.get_prediction = AsyncMock(side_effect=[None, cached_payload])

    first = await engine.predict("SBIN", df, x_ts, y_ts)
    assert first.get("cached") is False
    second = await engine.predict("SBIN", df, x_ts, y_ts)
    assert second["cached"] is True
    assert second["pred_close"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_engine_blocks_on_dqg_failure(tmp_path):
    reg = _make_registry(tmp_path)
    redis = AsyncMock()
    redis.get_prediction = AsyncMock(return_value=None)
    redis.set_prediction = AsyncMock()
    redis.publish_prediction = AsyncMock()

    fail_report = DQGReport(
        symbol="SBIN",
        timeframe="5min",
        mode="VISUAL",
        status=DQGStatus.FAIL,
        created_at=datetime.utcnow(),
        last_candle_time=None,
        coverage_pct=50.0,
        days_collected=1,
        checks={"min_history": {"passed": False, "critical": True}},
    )
    dqg = AsyncMock()
    dqg.run = AsyncMock(return_value=fail_report)

    engine = KronosEngine(
        config={"model": {"device": "cpu", "dtype": "float16"}},
        registry=reg,
        redis_cache=redis,
        dqg=dqg,
        model_loader=lambda p: MagicMock(),
        watcher_interval_s=3600,
    )
    df = _sample_df()
    with pytest.raises(DQGFailureError):
        await engine.predict(
            "SBIN",
            df,
            df.index,
            pd.date_range(df.index[-1], periods=3, freq="5min", tz=IST)[1:],
        )
    dqg.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_force_bypasses_cache(engine_setup):
    engine, redis = engine_setup
    df = _sample_df()
    x_ts = df.index
    y_ts = pd.date_range(df.index[-1], periods=3, freq="5min", tz=IST)[1:]

    redis.get_prediction = AsyncMock(return_value={"cached": True})
    out = await engine.predict("SBIN", df, x_ts, y_ts, force=True)
    assert out.get("cached") is False
    redis.set_prediction.assert_awaited()


@pytest.mark.asyncio
async def test_engine_raises_on_nan_prediction(tmp_path):
    reg = _make_registry(tmp_path)
    redis = AsyncMock()
    redis.get_prediction = AsyncMock(return_value=None)
    redis.set_prediction = AsyncMock()

    class NanPredictor:
        def __init__(self):
            self._inner = MockKronosPredictor(with_nan=True)

        def predict(
            self,
            df,
            x_ts,
            y_ts,
            pred_len=None,
            temperature=None,
            sample_count=None,
            vix_level=None,
        ):
            pred_df = self._inner.predict(df, x_ts, y_ts, pred_len or 3, 2, 0.7)
            return pred_df, {}

    engine = KronosEngine(
        config={"model": {"device": "cpu", "dtype": "float16"}},
        registry=reg,
        redis_cache=redis,
        model_loader=lambda p: NanPredictor(),
        watcher_interval_s=3600,
    )
    df = _sample_df()
    with pytest.raises(PredictionError):
        await engine.predict(
            "SBIN",
            df,
            df.index,
            pd.date_range(df.index[-1], periods=3, freq="5min", tz=IST)[1:],
        )


def test_engine_clips_ohlcv_violations():
    """Demonstrate OHLCV clipping: high below close is fixed."""
    idx = pd.date_range("2025-04-01 09:15", periods=2, freq="5min", tz=IST)
    bad = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [99.0, 100.0],  # invalid: high < open/close
            "low": [101.0, 99.0],  # invalid: low > open on row 0
            "close": [100.5, 100.5],
            "volume": [-5.0, 100.0],
        },
        index=idx,
    )
    clipped, was_clipped = clip_ohlcv_dataframe(bad)
    assert was_clipped is True
    assert (clipped["high"] >= clipped[["open", "close"]].max(axis=1)).all()
    assert (clipped["low"] <= clipped[["open", "close"]].min(axis=1)).all()
    assert (clipped["volume"] >= 0).all()


@pytest.mark.asyncio
async def test_engine_predict_batch_returns_correct_count(engine_setup):
    engine, _ = engine_setup
    df = _sample_df()
    x_ts = df.index
    y_ts = pd.date_range(df.index[-1], periods=3, freq="5min", tz=IST)[1:]
    reqs = [{"symbol": "SBIN", "df": df, "x_ts": x_ts, "y_ts": y_ts} for _ in range(3)]
    out = await engine.predict_batch(reqs)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_version_watcher_triggers_reload_on_version_change(tmp_path):
    reg = _make_registry(tmp_path)
    redis = AsyncMock()

    load_count = {"n": 0}

    def loader(paths):
        load_count["n"] += 1
        return MagicMock()

    engine = KronosEngine(
        config={"model": {"device": "cpu", "dtype": "float16"}},
        registry=reg,
        redis_cache=redis,
        model_loader=loader,
        watcher_interval_s=0.05,
    )

    v2_src_tok = tmp_path / "tok2"
    v2_src_pred = tmp_path / "pred2"
    v2_src_tok.mkdir()
    v2_src_pred.mkdir()
    v2 = reg.register_checkpoint(
        v2_src_tok, v2_src_pred, {"val_mae": 0.02}, version="v_watcher_test"
    )
    reg.promote_to_production(v2)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if load_count["n"] >= 2:
            break
        await asyncio.sleep(0.05)
    assert load_count["n"] >= 2
    await engine.close()


@pytest.mark.asyncio
async def test_context_builder_generates_correct_future_timestamps():
    db = AsyncMock()
    idx = pd.date_range("2025-04-04 15:20", periods=400, freq="5min", tz=IST)  # Friday
    db.get_candles = AsyncMock(
        return_value=pd.DataFrame(
            {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            },
            index=idx,
        )
    )
    builder = ContextBuilder(db, {"model": {"lookback": 400, "default_pred_len": 5}})
    ctx = await builder.build("SBIN", "5min", "VISUAL")
    y_ts = ctx["y_ts"]
    assert len(y_ts) == 5
    # Next timestamps should skip weekend (Apr 5-6 2025 is Sat/Sun)
    assert all(ts.weekday() < 5 for ts in y_ts)


@pytest.mark.asyncio
async def test_context_builder_skips_weekends_and_holidays():
    db = AsyncMock()
    idx = pd.date_range("2025-04-04 15:25", periods=10, freq="5min", tz=IST)
    db.get_candles = AsyncMock(
        return_value=pd.DataFrame(
            {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1}, index=idx
        )
    )
    builder = ContextBuilder(db, {"model": {"lookback": 10, "default_pred_len": 3}})
    y_ts = builder._generate_future_timestamps(idx[-1], "5min", 3)
    for ts in y_ts:
        assert is_trading_day(ts.to_pydatetime())


@pytest.mark.asyncio
async def test_context_builder_skips_outside_market_hours():
    db = AsyncMock()
    # Only mid-day bars
    idx = pd.date_range("2025-04-04 10:00", periods=50, freq="5min", tz=IST)
    df = pd.DataFrame(
        {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1}, index=idx
    )
    db.get_candles = AsyncMock(return_value=df)
    builder = ContextBuilder(db, {"model": {"lookback": 50}})
    ctx = await builder.build("SBIN", "5min", "VISUAL")
    assert not ctx["df"].empty
    for ts in ctx["df"].index:
        t = ts.time()
        assert market_time(9, 15) <= t <= market_time(15, 30)


def test_registry_register_promote_and_compare(tmp_path):
    reg = ModelRegistry(tmp_path)
    tok = tmp_path / "t"
    pred = tmp_path / "p"
    tok.mkdir()
    pred.mkdir()
    v1 = reg.register_checkpoint(
        tok, pred, {"val_mae": 0.1, "val_directional_acc": 0.5}
    )
    v2 = reg.register_checkpoint(
        tok, pred, {"val_mae": 0.08, "val_directional_acc": 0.52}, version="v_test2"
    )
    reg.promote_to_production(v1)
    paths = reg.get_production_paths()
    assert paths["version"] == v1
    cmp = reg.compare(v1, v2)
    assert "delta" in cmp
    assert cmp["delta"]["val_mae"] == pytest.approx(-0.02)
