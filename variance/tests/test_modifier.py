"""Unit tests for PredictionModifier.

All external dependencies (MVE, MVS) are mocked.
No live MVE, Redis, or collectors required.
"""

from __future__ import annotations

from typing import Any

import pytest

from variance.modifier import PredictionModifier


# ── Test Helpers ──────────────────────────────────────────────────────────


def make_mvs(
    composite: float = 0.0,
    vix_value: float | None = None,
    market_state: str = "neutral",
    confidence_override: str | None = None,
    band_width_multiplier: float = 1.0,
    signal_threshold: float = 0.005,
    temperature_adjustment: float = 0.0,
) -> dict[str, Any]:
    """Build a mock MVS dict matching MarketVarianceScore.to_dict() shape."""
    return {
        "composite": composite,
        "market_state": market_state,
        "vix_value": vix_value,
        "confidence_override": confidence_override,
        "band_width_multiplier": band_width_multiplier,
        "signal_threshold": signal_threshold,
        "temperature_adjustment": temperature_adjustment,
        "directional_bias": composite,
    }


def make_prediction(
    pred_close: list[float] | None = None,
    pred_high: list[float] | None = None,
    pred_low: list[float] | None = None,
    pred_open: list[float] | None = None,
) -> dict[str, Any]:
    """Build a prediction dict with sensible defaults (6 bars)."""
    N = len(pred_close) if pred_close is not None else 6
    return {
        "pred_open": pred_open if pred_open is not None else [100.0] * N,
        "pred_high": pred_high if pred_high is not None else [102.0] * N,
        "pred_low": pred_low if pred_low is not None else [98.0] * N,
        "pred_close": pred_close if pred_close is not None else [101.0] * N,
        "pred_volume": [1000] * N,
    }


class MockMVE:
    """Mock MarketVarianceEngine with controllable MVS output."""

    def __init__(self, mvs_dict: dict[str, Any], is_ready: bool = True) -> None:
        self.last_mvs = mvs_dict
        self.is_ready = is_ready


# ── Pre-inference: Temperature Adjustment ────────────────────────────────


class TestModifyPreInference:
    """MVS-driven temperature adjustment (VIX-based)."""

    def test_temperature_no_vix(self) -> None:
        """VIX=None → temperature_adjustment=0.0 → temperature unchanged."""
        mvs = make_mvs(vix_value=None, temperature_adjustment=0.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.7)
        assert result == 0.7

    def test_temperature_vix_above_baseline(self) -> None:
        """VIX=25 → adj +0.15, base=0.7 → effective=0.85."""
        mvs = make_mvs(temperature_adjustment=0.15)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.7)
        assert result == pytest.approx(0.85, rel=1e-5)

    def test_temperature_vix_capped(self) -> None:
        """VIX=40 → adj capped at +0.3 → effective=1.0."""
        mvs = make_mvs(temperature_adjustment=0.3)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.7)
        assert result == pytest.approx(1.0, rel=1e-5)

    def test_temperature_vix_below_baseline(self) -> None:
        """VIX=12 → adj=0.0 → base stays at 0.7."""
        mvs = make_mvs(temperature_adjustment=0.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.7)
        assert result == 0.7

    def test_temperature_with_regime_override(self) -> None:
        """VIX=25 (+0.15), regime=0.6 → max(0.6, 0.85)=0.85."""
        mvs = make_mvs(temperature_adjustment=0.15)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.6)
        assert result == pytest.approx(0.85, rel=1e-5)

    def test_temperature_with_volatile_regime(self) -> None:
        """VIX=12 (adj=0.0), regime=0.85 → max(0.85, 0.7)=0.85."""
        mvs = make_mvs(temperature_adjustment=0.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        result = modifier.modify_pre_inference(0.85)
        assert result == 0.85

    def test_temperature_mvs_not_ready(self) -> None:
        """MVE.is_ready=False → input temperature returned unchanged."""
        mvs = make_mvs(temperature_adjustment=0.3)
        modifier = PredictionModifier(mve=MockMVE(mvs, is_ready=False))
        result = modifier.modify_pre_inference(0.7)
        assert result == 0.7


# ── Post-inference: Bias, Bands, Constraints, Confidence ─────────────────


class TestModifyPostInference:
    """MVS-driven post-inference modifications (bias → bands → constraints → confidence)."""

    def test_bias_positive_composite(self) -> None:
        """composite=+0.5 → bar 0 shifted up ~0.5%, last bar ~0.25%."""
        mvs = make_mvs(composite=0.5)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction(pred_close=[100.0] * 6)
        result = modifier.modify_post_inference(pred)

        # N=6 bars, denom=5
        # bar 0: scale=1.0, shift=0.5*1.0*0.01=0.005 → 100*1.005=100.5
        # bar 5: scale=0.5, shift=0.5*0.5*0.01=0.0025 → 100*1.0025=100.25
        assert result["pred_close"][0] == pytest.approx(100.5, rel=1e-5)
        assert result["pred_close"][5] == pytest.approx(100.25, rel=1e-5)

        # Intermediate bars verify decay pattern
        assert result["pred_close"][1] == pytest.approx(100.45, rel=1e-5)
        assert result["pred_close"][2] == pytest.approx(100.4, rel=1e-5)
        assert result["pred_close"][3] == pytest.approx(100.35, rel=1e-5)
        assert result["pred_close"][4] == pytest.approx(100.3, rel=1e-5)

    def test_bias_negative_composite(self) -> None:
        """composite=-0.5 → bar 0 shifted down ~0.5%, last bar ~0.25%."""
        mvs = make_mvs(composite=-0.5)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction(pred_close=[100.0] * 6)
        result = modifier.modify_post_inference(pred)

        # bar 0: shift=-0.005 → 100*0.995=99.5
        # bar 5: shift=-0.0025 → 100*0.9975=99.75
        assert result["pred_close"][0] == pytest.approx(99.5, rel=1e-5)
        assert result["pred_close"][5] == pytest.approx(99.75, rel=1e-5)

    def test_bias_zero_composite(self) -> None:
        """composite=0 → pred_close unchanged."""
        mvs = make_mvs(composite=0.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction(pred_close=[101.0, 102.0, 103.0])
        result = modifier.modify_post_inference(pred)
        assert result["pred_close"] == [101.0, 102.0, 103.0]

    def test_band_scaling(self) -> None:
        """band_mult=1.08 → bars widened correctly around midpoint."""
        mvs = make_mvs(composite=0.0, band_width_multiplier=1.08)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        # mid = (102 + 98) / 2 = 100
        # new_high = 100 + (102-100)*1.08 = 102.16
        # new_low = 100 - (100-98)*1.08 = 97.84
        pred = make_prediction(pred_close=[101.0] * 6)
        result = modifier.modify_post_inference(pred)

        assert result["pred_high"][0] == pytest.approx(102.16, rel=1e-5)
        assert result["pred_low"][0] == pytest.approx(97.84, rel=1e-5)
        # pred_close unaffected by band scaling
        assert result["pred_close"][0] == pytest.approx(101.0, rel=1e-5)

    def test_ohlcv_constraints(self) -> None:
        """High below open → clamped up to max(open, close)."""
        mvs = make_mvs(composite=0.0, band_width_multiplier=1.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction(
            pred_open=[100.0] * 6,
            pred_high=[99.0] * 6,  # below open and close
            pred_low=[97.0] * 6,
            pred_close=[101.0] * 6,
        )
        result = modifier.modify_post_inference(pred)

        # hi = max(99, 100, 101) = 101
        assert result["pred_high"][0] == 101.0
        # lo = min(97, 100, 101) = 97 (unchanged)
        assert result["pred_low"][0] == 97.0

    def test_confidence_override_panic(self) -> None:
        """market_state='panic', confidence_override='LOW' → mve_confidence='LOW'."""
        mvs = make_mvs(
            market_state="panic",
            confidence_override="LOW",
        )
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction()
        result = modifier.modify_post_inference(pred)
        assert result.get("mve_confidence") == "LOW"

    def test_confidence_no_override_normal(self) -> None:
        """market_state='neutral', confidence_override=None → mve_confidence absent."""
        mvs = make_mvs(market_state="neutral", confidence_override=None)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction()
        result = modifier.modify_post_inference(pred)
        assert "mve_confidence" not in result

    def test_modifier_noop_without_mve(self) -> None:
        """PredictionModifier(mve=None) → all modifications are no-ops."""
        modifier = PredictionModifier(mve=None)

        # Pre-inference: temperature unchanged
        temp = modifier.modify_pre_inference(0.7)
        assert temp == 0.7

        # Post-inference: pred_close unchanged
        pred = make_prediction(pred_close=[101.0, 102.0, 103.0])
        result = modifier.modify_post_inference(pred)
        assert result["pred_close"] == [101.0, 102.0, 103.0]
        assert "mve_confidence" not in result


class TestModifyPostInferenceEdgeCases:
    """Edge cases and defensive behaviours."""

    def test_bias_single_bar(self) -> None:
        """Single-bar prediction — bias scale denominator handles N=1 safely."""
        mvs = make_mvs(composite=0.5)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        # N=1 → denom = max(1-1, 1) = 1, scale = 1 - 0.5*(0/1) = 1.0
        pred = make_prediction(pred_close=[100.0])
        result = modifier.modify_post_inference(pred)
        # shift = 0.5 * 1.0 * 0.01 = 0.005 → 100 * 1.005 = 100.5
        assert result["pred_close"][0] == pytest.approx(100.5, rel=1e-5)

    def test_band_no_widen_when_multiplier_one(self) -> None:
        """band_width_multiplier=1.0 → H/L unchanged."""
        mvs = make_mvs(composite=0.0, band_width_multiplier=1.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction()
        result = modifier.modify_post_inference(pred)
        assert result["pred_high"][0] == 102.0
        assert result["pred_low"][0] == 98.0

    def test_negative_volume_clamped_to_zero(self) -> None:
        """Negative volume values clamped to 0 by OHLCV constraints."""
        mvs = make_mvs(composite=0.0, band_width_multiplier=1.0)
        modifier = PredictionModifier(mve=MockMVE(mvs))
        pred = make_prediction(
            pred_open=[100.0] * 3,
            pred_high=[102.0] * 3,
            pred_low=[98.0] * 3,
            pred_close=[101.0] * 3,
        )
        pred["pred_volume"] = [1000, -500, -200]
        result = modifier.modify_post_inference(pred)
        assert result["pred_volume"][0] == 1000
        assert result["pred_volume"][1] == 0.0
        assert result["pred_volume"][2] == 0.0
