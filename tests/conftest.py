"""Shared test fixtures for all test suites."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from model.factory import InferenceContext


@asynccontextmanager
async def lifespan_app(app):
    """Run app lifespan for testing."""
    async with app.router.lifespan_context(app):
        yield


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Return a standard 10-bar OHLCV DataFrame with 5min frequency."""
    idx = pd.date_range("2025-04-01 09:15", periods=10, freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(10)],
            "high": [101.0 + i for i in range(10)],
            "low": [99.0 + i for i in range(10)],
            "close": [100.5 + i for i in range(10)],
            "volume": [1000 + i * 100 for i in range(10)],
        },
        index=idx,
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    """Return a mocked TimescaleClient."""
    db = AsyncMock()
    db.initialize = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def mock_redis() -> MagicMock:
    """Return a mocked RedisCache."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.publish = AsyncMock()
    redis.initialize = AsyncMock()
    redis.close = AsyncMock()
    redis._client = MagicMock()
    redis._client.pipeline = MagicMock(return_value=MagicMock())
    redis._client.llen = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def mock_predictor() -> MagicMock:
    """Return a mocked KronosPredictorWrapper."""
    predictor = MagicMock()
    predictor.predict = AsyncMock(
        return_value={
            "open": [101.0, 102.0, 103.0],
            "high": [102.0, 103.0, 104.0],
            "low": [100.0, 101.0, 102.0],
            "close": [101.5, 102.5, 103.5],
            "volume": [1100, 1200, 1300],
        }
    )
    return predictor


@pytest.fixture
def mock_registry() -> MagicMock:
    """Return a mocked ModelRegistry."""
    class MockRegistry:
        async def get_production_paths(self):
            return {
                "version": "test-v1",
                "predictor": "/tmp/test-predictor",
                "tokenizer": "/tmp/test-tokenizer",
            }
        async def promote_to_production(self, *args, **kwargs):
            pass
        async def register_checkpoint(self, *args, **kwargs):
            pass
        def has_production(self):
            return True
    return MockRegistry()


@pytest.fixture
def mock_inference_context(
    mock_db: AsyncMock,
    mock_redis: MagicMock,
    mock_registry: MagicMock,
    mock_predictor: MagicMock,
) -> InferenceContext:
    """Create a fully mocked InferenceContext for testing."""
    context = InferenceContext(
        config={
            "model": {"device": "cpu"},
            "collector": {"universe": "NIFTY50"},
        },
        db=mock_db,
        redis=mock_redis,
        registry=mock_registry,
        dqg=MagicMock(),
        context_builder=MagicMock(),
        engine=MagicMock(),
    )
    context.dqg.run = AsyncMock(return_value=MagicMock(status="PASS"))
    context.dqg.run_batch = AsyncMock(return_value={})
    context.dqg.assert_pass = AsyncMock(return_value=None)
    context.dqg._redis = mock_redis
    context.context_builder.build = AsyncMock(return_value={
        "df": None, "x_ts": None, "y_ts": None, "temperature_override": None
    })
    context.engine.predict = AsyncMock(return_value={
        "symbol": "TEST",
        "pred_close": [100, 101, 102],
        "pred_open": [99, 100, 101],
        "pred_high": [101, 102, 103],
        "pred_low": [98, 99, 100],
        "pred_volume": [1000, 1100, 1200],
        "pred_timestamps": ["2025-01-01T09:15:00+05:30"] * 3,
        "model_version": "test-v1",
        "confidence": "HIGH",
        "generated_at": "2025-01-01T09:15:00+05:30",
    })
    context.engine.get_vix_level = MagicMock(return_value=15.0)
    return context


@pytest.fixture
def client(mock_inference_context: InferenceContext) -> TestClient:
    """Create a TestClient with lifespan running."""
    app = create_app(inference_override=mock_inference_context)
    with TestClient(app) as c:
        yield c
