"""Integration tests for FastAPI backend with mocked inference stack."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from data.quality.gate import DQGReport, DQGStatus
from model.engine import KronosEngine
from model.factory import InferenceContext
from model.registry import ModelRegistry

IST = "Asia/Kolkata"


def _sample_df(rows: int = 10) -> pd.DataFrame:
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


def _pass_report(symbol: str = "SBIN") -> DQGReport:
    return DQGReport(
        symbol=symbol,
        timeframe="5min",
        mode="VISUAL",
        status=DQGStatus.PASS,
        created_at=datetime.utcnow(),
        last_candle_time="2025-04-01T15:25:00+05:30",
        coverage_pct=99.5,
        days_collected=12,
        checks={"min_history": {"passed": True, "critical": True, "detail": "ok"}},
    )


def _fail_report(symbol: str = "SBIN") -> DQGReport:
    return DQGReport(
        symbol=symbol,
        timeframe="5min",
        mode="VISUAL",
        status=DQGStatus.FAIL,
        created_at=datetime.utcnow(),
        last_candle_time=None,
        coverage_pct=50.0,
        days_collected=1,
        checks={
            "min_history": {"passed": False, "critical": True, "detail": "insufficient"}
        },
        recommendation="Fix data",
    )


@pytest.fixture
async def mock_inference_context(tmp_path: Path) -> InferenceContext:
    reg = ModelRegistry(tmp_path)
    tok = tmp_path / "tok"
    pred = tmp_path / "pred"
    tok.mkdir()
    pred.mkdir()
    version = reg.register_checkpoint(
        tok,
        pred,
        {
            "val_mae": 0.01,
            "val_directional_acc": 0.55,
            "train_symbols": ["SBIN", "RELIANCE"],
        },
    )
    reg.promote_to_production(version)

    redis = AsyncMock()
    redis.get_prediction = AsyncMock(return_value=None)
    redis.set_prediction = AsyncMock()
    redis.publish_prediction = AsyncMock()
    redis.get_dqg_report = AsyncMock(return_value=None)
    redis.set_dqg_report = AsyncMock()
    redis.publish_dqg_status = AsyncMock()
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(return_value=None)
    redis.pubsub = MagicMock(return_value=pubsub)

    db = AsyncMock()
    db.get_candles = AsyncMock(return_value=_sample_df(400))
    db.get_dqg_history = AsyncMock(return_value=[])
    db.store_prediction = AsyncMock(return_value=1)

    dqg = AsyncMock()
    dqg.run = AsyncMock(return_value=_pass_report())
    dqg.run_batch = AsyncMock(
        side_effect=lambda symbols, timeframe, mode: {
            s: _pass_report(s) for s in symbols
        }
    )
    dqg.assert_pass = AsyncMock(return_value=None)

    df = _sample_df()
    context_builder = AsyncMock()
    context_builder.build = AsyncMock(
        return_value={
            "df": df,
            "x_ts": df.index,
            "y_ts": pd.date_range(df.index[-1], periods=60, freq="5min", tz=IST)[1:],
            "builder": "standard",
        }
    )

    class MockPredictor:
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
            n = pred_len or 3
            idx = y_ts[:n]
            out = pd.DataFrame(
                {
                    "open": [100.0] * n,
                    "high": [101.0] * n,
                    "low": [99.0] * n,
                    "close": [100.8] * n,
                    "volume": [500.0] * n,
                },
                index=idx,
            )
            return out, {"sample_count": 2, "temperature": 0.7, "latency_ms": 12.5}

    engine = KronosEngine(
        config={
            "model": {
                "device": "cpu",
                "dtype": "float16",
                "default_sample_count": 2,
                "default_temperature": 0.7,
                "default_pred_len": 10,
            },
            "collector": {"universe": "NIFTY50"},
        },
        registry=reg,
        redis_cache=redis,
        dqg=dqg,
        context_builder=context_builder,
        db=db,
        model_loader=lambda p: MockPredictor(),
        watcher_interval_s=3600,
    )

    return InferenceContext(
        config={
            "model": {"device": "cpu"},
            "collector": {"universe": "NIFTY50"},
        },
        db=db,
        redis=redis,
        registry=reg,
        dqg=dqg,
        context_builder=context_builder,
        engine=engine,
    )
    reg.promote_to_production(version)

    redis = AsyncMock()
    redis.get_prediction = AsyncMock(return_value=None)
    redis.set_prediction = AsyncMock()
    redis.publish_prediction = AsyncMock()
    redis.get_dqg_report = AsyncMock(return_value=None)
    redis.set_dqg_report = AsyncMock()
    redis.publish_dqg_status = AsyncMock()
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(return_value=None)
    redis.pubsub = MagicMock(return_value=pubsub)

    db = AsyncMock()
    db.get_dqg_history = AsyncMock(return_value=[])
    db.store_prediction = AsyncMock(return_value=1)

    dqg = AsyncMock()
    dqg.run = AsyncMock(return_value=_pass_report())
    dqg.run_batch = AsyncMock(
        side_effect=lambda symbols, timeframe, mode: {
            s: _pass_report(s) for s in symbols
        }
    )
    dqg.assert_pass = AsyncMock(return_value=None)

    df = _sample_df()
    context_builder = AsyncMock()
    context_builder.build = AsyncMock(
        return_value={
            "df": df,
            "x_ts": df.index,
            "y_ts": pd.date_range(df.index[-1], periods=60, freq="5min", tz=IST)[1:],
            "builder": "standard",
        }
    )

    class MockModel:
        def eval(self):
            return self

        def half(self):
            return self

        def to(self, *args, **kwargs):
            return self

    engine = KronosEngine(
        config={
            "model": {
                "device": "cpu",
                "dtype": "float16",
                "default_sample_count": 2,
                "default_temperature": 0.7,
                "default_pred_len": 10,
            },
            "collector": {"universe": "NIFTY50"},
        },
        registry=reg,
        redis_cache=redis,
        dqg=dqg,
        context_builder=context_builder,
        db=db,
        model_loader=lambda p: MockPredictor(),
        watcher_interval_s=3600,
    )

    return InferenceContext(
        config={
            "model": {"device": "cpu"},
            "collector": {"universe": "NIFTY50"},
        },
        db=db,
        redis=redis,
        registry=reg,
        dqg=dqg,
        context_builder=context_builder,
        engine=engine,
    )


@pytest.fixture
def client(mock_inference_context: InferenceContext) -> TestClient:
    app = create_app(inference_override=mock_inference_context)
    with TestClient(app) as test_client:
        test_client.app.state.operating_mode = "VISUAL"
        yield test_client


def test_health_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] == "VISUAL"
    assert body["model_version"] is not None


def test_prediction_endpoint_returns_correct_schema(client: TestClient):
    resp = client.get("/api/v1/predictions/SBIN?pred_len=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SBIN"
    assert body["dqg_status"] == "PASS"
    assert len(body["pred_close"]) == 5
    assert body["confidence"] in {"HIGH", "MEDIUM", "LOW"}
    assert "timestamps" in body


def test_prediction_endpoint_422_on_dqg_fail(mock_inference_context: InferenceContext):
    mock_inference_context.dqg.run = AsyncMock(return_value=_fail_report())
    app = create_app(inference_override=mock_inference_context)
    with TestClient(app) as client:
        resp = client.get("/api/v1/predictions/SBIN")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "DQG_FAIL"
    assert body["report"]["status"] == "FAIL"


def test_dqg_endpoint_returns_report(
    client: TestClient, mock_inference_context: InferenceContext
):
    cached = {
        "symbol": "SBIN",
        "timeframe": "5min",
        "status": "PASS",
        "coverage_pct": 99.0,
        "days_collected": 10,
        "checks": {"min_history": {"passed": True, "critical": True, "detail": "ok"}},
    }
    mock_inference_context.redis.get_dqg_report = AsyncMock(return_value=cached)
    resp = client.get("/api/v1/dqg/SBIN")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "SBIN"
    assert body["status"] == "PASS"
    assert "min_history" in body["checks"]


def test_mode_change_endpoint(client: TestClient):
    resp = client.post("/api/v1/mode", json={"mode": "PAPER"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "PAPER"
    assert any("PAPER" in msg for msg in body["messages"])


def test_websocket_connects_and_receives_ping(client: TestClient):
    with client.websocket_connect("/ws/ping") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "ping"
        assert msg["channel"] == "ping"
