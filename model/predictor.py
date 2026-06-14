"""Kronos prediction wrapper with IST handling and OHLCV clipping."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
IST = "Asia/Kolkata"
UTC = "UTC"


class PredictionError(Exception):
    """Raised when model output is invalid (NaN or unrecoverable OHLCV)."""


class SupportsKronosPredict(Protocol):
    """Protocol for underlying Kronos model predict API."""

    def predict(
        self,
        df: pd.DataFrame,
        x_timestamp: pd.DatetimeIndex,
        y_timestamp: pd.DatetimeIndex,
        pred_len: int,
        sample_count: int,
        temperature: float,
    ) -> pd.DataFrame: ...


def clip_ohlcv_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Clip OHLCV to valid constraints. Returns (df, was_clipped)."""
    if df.empty:
        return df, False

    out = df.copy()
    clipped = False
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(out.columns):
        raise PredictionError(
            f"Prediction missing columns: {required - set(out.columns)}"
        )

    for col in ("open", "high", "low", "close", "volume"):
        if out[col].isna().any():
            raise PredictionError(f"NaN detected in prediction column: {col}")

    high_floor = out[["open", "close"]].max(axis=1)
    if (out["high"] < high_floor).any():
        clipped = True
    out["high"] = np.maximum(out["high"], high_floor)

    low_cap = out[["open", "close"]].min(axis=1)
    if (out["low"] > low_cap).any():
        clipped = True
    out["low"] = np.minimum(out["low"], low_cap)

    if (out["volume"] < 0).any():
        clipped = True
    out["volume"] = out["volume"].clip(lower=0)

    if (out["high"] < out["low"]).any():
        clipped = True
        out["high"] = np.maximum(out["high"], out["low"])

    return out, clipped


class KronosPredictorWrapper:
    """Wrapper: UTC conversion, log1p volume/amount, predict, IST restore, clip, latency log.

    The vendor's KronosPredictor.predict() applies internal z-score normalization.
    Our fine-tuning (NSEKronosFinetuneDataset) additionally applies log1p to volume
    and amount before z-score. This wrapper applies that same log1p pre-transform
    to close the train-inference normalization gap, then inverts it on output.
    """

    def __init__(self, model: SupportsKronosPredict, config: dict[str, Any]) -> None:
        self.model = model
        self.config = config
        model_cfg = config.get("model") or {}
        self.sample_count = int(model_cfg.get("default_sample_count", 10))
        self.temperature = float(model_cfg.get("default_temperature", 0.7))

    def predict(
        self,
        df: pd.DataFrame,
        x_ts: pd.DatetimeIndex,
        y_ts: pd.DatetimeIndex,
        pred_len: int | None = None,
        temperature: float | None = None,
        sample_count: int | None = None,
        vix_level: float | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Run prediction and return clipped DataFrame + metadata."""
        pred_len = pred_len or len(y_ts)
        temperature = self.temperature if temperature is None else temperature
        sample_count = self.sample_count if sample_count is None else sample_count

        if df.isna().any().any():
            raise PredictionError("NaN values in model input")

        df_utc = df.copy()
        if "amount" not in df_utc.columns:
            df_utc["amount"] = df_utc["volume"] * df_utc[["open", "close"]].mean(axis=1)
        df_utc["volume"] = np.log1p(np.abs(df_utc["volume"]))
        df_utc["amount"] = np.log1p(np.abs(df_utc["amount"]))

        # Volume-derived features (auxiliary — ignored by 6-channel tokenizer).
        # Activate by expanding FEATURE_LIST + retraining with d_in=9.
        vol_cols = ["vol_zscore", "vol_ratio", "vol_obv_norm"]
        for col in vol_cols:
            if col in df_utc.columns:
                pass  # already normalized; pass through for future activation

        x_utc = (
            x_ts.tz_convert(UTC) if x_ts.tz else x_ts.tz_localize(IST).tz_convert(UTC)
        )
        y_utc = (
            y_ts.tz_convert(UTC) if y_ts.tz else y_ts.tz_localize(IST).tz_convert(UTC)
        )

        start = time.perf_counter()
        raw = self.model.predict(
            df_utc,
            x_timestamp=x_utc,
            y_timestamp=y_utc,
            pred_len=pred_len,
            T=temperature,
            sample_count=sample_count,
            verbose=False,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        logger.debug("Kronos predict latency: %.2f ms", latency_ms)

        raw["volume"] = np.expm1(raw["volume"])
        raw["amount"] = np.expm1(raw["amount"])

        if not isinstance(raw.index, pd.DatetimeIndex):
            if "timestamp" in raw.columns:
                raw.index = pd.to_datetime(raw["timestamp"])
            else:
                raw.index = y_ts[: len(raw)]

        if raw.index.tz is None:
            raw.index = raw.index.tz_localize(UTC)
        elif raw.index.tz != IST:
            raw.index = raw.index.tz_convert(IST)

        clipped_df, was_clipped = clip_ohlcv_dataframe(raw)
        meta = {
            "latency_ms": latency_ms,
            "clipped": was_clipped,
            "sample_count": sample_count,
            "temperature": temperature,
        }
        return clipped_df, meta
