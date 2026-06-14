from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from headless.ledger import PredictionLedger


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def ledger(db):
    return PredictionLedger(db)


@pytest.mark.asyncio
async def test_record_delegates_to_db(ledger, db):
    prediction = {"symbol": "RELIANCE", "pred_close": [100.0]}
    db.store_prediction.return_value = 42
    lid = await ledger.record(prediction)
    assert lid == 42
    db.store_prediction.assert_awaited_once_with(prediction)


def test_prediction_from_engine_result_basic():
    result = {
        "symbol": "RELIANCE",
        "timeframe": "5min",
        "mode": "HEADLESS",
        "generated_at": "2025-01-01T00:00:00Z",
        "model_version": "v1",
        "pred_open": [100.0],
        "pred_high": [101.0],
        "pred_low": [99.0],
        "pred_close": [100.5],
        "pred_volume": [1000],
        "pred_timestamps": ["2025-01-01T00:05:00"],
    }
    out = PredictionLedger.prediction_from_engine_result(result)
    assert out["symbol"] == "RELIANCE"
    assert out["model_version"] == "v1"
    assert isinstance(out["generated_at"], datetime)


def test_prediction_from_engine_result_missing_fields():
    result = {"symbol": "NIFTY50", "pred_close": []}
    out = PredictionLedger.prediction_from_engine_result(result)
    assert out["symbol"] == "NIFTY50"
    assert out["model_version"] == "unknown"
    assert isinstance(out["generated_at"], datetime)


@pytest.mark.asyncio
async def test_resolve_delegates_to_db(ledger, db):
    await ledger.resolve(1, [100.0, 101.0])
    db.resolve_prediction.assert_awaited_once_with(
        1, [100.0, 101.0], actual_high=None, actual_low=None
    )


@pytest.mark.asyncio
async def test_get_unresolved_delegates_to_db(ledger, db):
    db.get_unresolved_predictions.return_value = [{"id": 1}]
    result = await ledger.get_unresolved("RELIANCE", older_than_hours=48)
    assert result == [{"id": 1}]
    db.get_unresolved_predictions.assert_awaited_once_with(
        "RELIANCE", older_than_hours=48
    )
