"""Unit tests for the training pipeline (mocked torch and DB)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest
import torch

from training.dataset import NSEKronosDataset
from training.drift_detector import DriftDetector
from training.evaluator import ModelEvaluator
from training.scheduler import RetrainingScheduler

IST = "Asia/Kolkata"


def _intraday_df(
    start: str,
    periods: int,
    freq: str = "5min",
    *,
    gap_at: int | None = None,
) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq=freq, tz=IST)
    if gap_at is not None and gap_at < len(idx) - 1:
        idx = idx.delete(gap_at)
    close = np.linspace(100, 110, len(idx))
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(len(idx), 1000.0),
        },
        index=idx,
    )


def _make_dataset(
    candles: dict[str, pd.DataFrame],
    *,
    lookback: int = 5,
    pred_len: int = 3,
    augment: bool = False,
    split: str = "train",
) -> NSEKronosDataset:
    return NSEKronosDataset(
        db=None,
        symbols=list(candles.keys()),
        timeframe="5min",
        lookback=lookback,
        pred_len=pred_len,
        augment=augment,
        split=split,
        candles_by_symbol=candles,
    )


def test_nse_dataset_skips_eod_crossing_samples():
    """Samples whose y window spans two trading days are excluded."""
    friday = _intraday_df("2025-04-04 14:50", periods=20)
    ds = _make_dataset({"SBIN": friday}, lookback=5, pred_len=8)
    for sample in ds.samples:
        assert sample["y"].shape[0] == 8

    late = _intraday_df("2025-04-04 15:10", periods=10)
    ds_late = _make_dataset({"SBIN": late}, lookback=3, pred_len=6)
    assert len(ds_late.samples) == 0


def test_nse_dataset_clean_handles_gaps_correctly():
    """Forward-fill closes gaps up to 2 bars and zeros filled volume."""
    raw = _intraday_df("2025-04-01 09:15", periods=8, gap_at=3)
    cleaned = NSEKronosDataset.clean(raw, "5min")
    assert cleaned["close"].isna().sum() == 0
    assert (cleaned["volume"] >= 0).all()
    assert len(cleaned) >= len(raw) - 1


def test_nse_dataset_augment_preserves_shape():
    """Augmentation keeps tensor shape unchanged."""
    candles = {"SBIN": _intraday_df("2025-04-01 09:15", periods=30)}
    ds = _make_dataset(candles, lookback=5, pred_len=3, augment=True, split="train")
    item = ds[0]
    assert item["x"].shape == torch.Size([5, 6])
    assert item["y"].shape == torch.Size([3, 6])


def test_evaluator_directional_accuracy_correct_calculation():
    pred = [100.0, 101.0, 99.0, 100.0]
    actual = [100.0, 101.0, 100.0, 99.0]
    acc = ModelEvaluator.compute_directional_accuracy(pred, actual)
    assert acc == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_drift_detector_triggers_on_mae_degradation():
    db = AsyncMock()
    db.get_resolved_predictions = AsyncMock(
        side_effect=[
            [{"mae": 0.20, "directional_acc": 0.55}] * 100,
            [{"mae": 0.10, "directional_acc": 0.56}] * 200,
        ]
    )
    detector = DriftDetector(
        db,
        {
            "drift": {
                "window_days": 7,
                "baseline_days": 30,
                "min_samples": 100,
                "mae_degradation_threshold": 0.15,
                "directional_acc_threshold": 0.52,
            }
        },
    )
    result = await detector.check()
    assert result["drift_detected"] is True
    assert result["trigger"] == "mae_degradation"
    assert result["mae_degradation"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_drift_detector_no_trigger_insufficient_samples():
    db = AsyncMock()
    db.get_resolved_predictions = AsyncMock(return_value=[{"mae": 0.1}] * 10)
    detector = DriftDetector(db, {"drift": {"min_samples": 100}})
    result = await detector.check()
    assert result["drift_detected"] is False
    assert result["reason"] == "insufficient_samples"


@pytest.mark.asyncio
async def test_scheduler_skips_if_insufficient_new_samples():
    db = AsyncMock()
    db.get_last_registry_created_at = AsyncMock(return_value=datetime(2025, 1, 1))
    db.count_candles_since = AsyncMock(return_value=50)

    scheduler = RetrainingScheduler(
        config={"training": {"min_new_samples": 10_000}},
        registry=MagicMock(),
        drift_detector=AsyncMock(),
        db=db,
    )

    await scheduler._weekly_cycle_async()
    db.count_candles_since.assert_awaited_once()
