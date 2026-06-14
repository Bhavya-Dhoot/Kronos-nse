from __future__ import annotations

from api.helpers import (
    compute_confidence,
    compute_direction,
    engine_result_to_prediction,
)


def test_compute_confidence_high():
    assert compute_confidence([105.0, 110.0], 100.0) == "HIGH"


def test_compute_confidence_medium():
    assert compute_confidence([100.5], 100.0) == "MEDIUM"
    assert compute_confidence([100.35], 100.0) == "MEDIUM"
    assert compute_confidence([101.0], 100.0) == "HIGH"


def test_compute_confidence_low():
    assert compute_confidence([100.05], 100.0) == "LOW"


def test_compute_confidence_no_data():
    assert compute_confidence([], None) == "LOW"
    assert compute_confidence(None, 100.0) == "LOW"


def test_compute_confidence_mve_override():
    assert compute_confidence([110.0], 100.0, mve_confidence="LOW") == "LOW"


def test_compute_direction_bullish():
    assert compute_direction([110.0], 100.0) == "BULLISH"


def test_compute_direction_bearish():
    assert compute_direction([90.0], 100.0) == "BEARISH"


def test_compute_direction_neutral():
    assert compute_direction([100.01], 100.0) == "NEUTRAL"


def test_compute_direction_no_data():
    assert compute_direction([], None) == "NEUTRAL"


def test_engine_result_to_prediction_basic():
    result = {
        "symbol": "RELIANCE",
        "timeframe": "5min",
        "mode": "VISUAL",
        "generated_at": "2025-01-01T00:00:00",
        "model_version": "v1",
        "pred_open": [100.0],
        "pred_high": [101.0],
        "pred_low": [99.0],
        "pred_close": [100.5],
        "pred_volume": [1000],
        "pred_timestamps": ["2025-01-01T00:05:00"],
    }
    resp = engine_result_to_prediction(result, last_close=100.0)
    assert resp.symbol == "RELIANCE"
    assert resp.model_version == "v1"
    assert resp.dqg_status == "PASS"
    assert resp.cached is False


def test_engine_result_to_prediction_missing_fields():
    result = {"symbol": "NIFTY50", "pred_close": [100.0]}
    resp = engine_result_to_prediction(result)
    assert resp.symbol == "NIFTY50"
    assert resp.model_version == ""
    assert resp.confidence == "LOW"
