"""Unit tests for MarketVarianceScore scoring math.

No external dependencies required — all tests are pure math.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from variance.schemas import DimensionScore
from variance.score import MarketState, MarketVarianceScore


def make_dim(
    name: str,
    score: float,
    weight: float = 0.2,
    is_stale: bool = False,
) -> DimensionScore:
    return DimensionScore(
        name=name,
        score=score,
        weight=weight,
        is_stale=is_stale,
        detail={},
        collected_at=datetime.now(UTC).isoformat(),
    )


class TestCompositeWeighting:
    def test_weighted_composite_all_equal(self):
        dims = [
            make_dim("vix", 1.0),
            make_dim("options", 0.5),
            make_dim("institutional", -0.5),
            make_dim("gift_nifty", 0.0),
            make_dim("global_macro", -1.0),
        ]
        mvs = MarketVarianceScore.build(dims)
        assert mvs.composite == pytest.approx(0.0, rel=1e-5)

    def test_stale_dimension_half_weight(self):
        dims = [
            make_dim("vix", 1.0, weight=0.6, is_stale=False),
            make_dim("options", -1.0, weight=0.4, is_stale=True),
        ]
        mvs = MarketVarianceScore.build(dims)
        # Effective: vix=0.6, options=0.2, denominator=0.8
        # Composite = (0.6*1.0 + 0.2*(-1.0)) / 0.8 = 0.4 / 0.8 = 0.5
        assert mvs.composite == pytest.approx(0.5, rel=1e-5)

    def test_composite_clamped(self):
        dims = [
            make_dim("vix", 2.0, weight=1.0),
            make_dim("options", 2.0, weight=0.0),
        ]
        mvs = MarketVarianceScore.build(dims)
        assert mvs.composite <= 1.0
        assert mvs.composite >= -1.0

    def test_all_stale_dimensions(self):
        dims = [
            make_dim("vix", 1.0, weight=0.6, is_stale=True),
            make_dim("options", -1.0, weight=0.4, is_stale=True),
        ]
        mvs = MarketVarianceScore.build(dims)
        # Effective: vix=0.3, options=0.2, denominator=0.5
        # Composite = (0.3*1.0 + 0.2*(-1.0)) / 0.5 = 0.1 / 0.5 = 0.2
        assert mvs.composite == pytest.approx(0.2, rel=1e-5)


class TestMarketStateClassification:
    def test_panic(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", -0.5)],
            vix_value=30.0,
        )
        assert mvs.market_state == MarketState.PANIC

    def test_fear(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", -0.5)],
            vix_value=23.0,
        )
        assert mvs.market_state == MarketState.FEAR

    def test_bull_run(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", 0.5)],
            vix_value=12.0,
        )
        assert mvs.market_state == MarketState.BULL_RUN

    def test_uncertain(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", 0.0)],
            vix_value=15.0,
        )
        assert mvs.market_state == MarketState.UNCERTAIN

    def test_neutral(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", 0.0)],
            vix_value=25.0,
        )
        assert mvs.market_state == MarketState.NEUTRAL


class TestDerivedProperties:
    def test_temperature_adjustment(self):
        mvs_below = MarketVarianceScore.build([], vix_value=10.0)
        assert mvs_below.temperature_adjustment == 0.0

        mvs_mid = MarketVarianceScore.build([], vix_value=20.0)
        assert mvs_mid.temperature_adjustment == pytest.approx(0.075, rel=1e-5)

        mvs_capped = MarketVarianceScore.build([], vix_value=35.0)
        assert mvs_capped.temperature_adjustment == pytest.approx(0.3, rel=1e-5)

        mvs_none = MarketVarianceScore.build([], vix_value=None)
        assert mvs_none.temperature_adjustment == 0.0

    def test_band_and_signal_derived_properties(self):
        mvs_low = MarketVarianceScore.build([], vix_value=10.0)
        assert mvs_low.band_width_multiplier == pytest.approx(1.0, rel=1e-5)
        assert mvs_low.signal_threshold == pytest.approx(0.005, rel=1e-5)

        mvs_high = MarketVarianceScore.build([], vix_value=25.0)
        assert mvs_high.band_width_multiplier == pytest.approx(1.08, rel=1e-5)
        assert mvs_high.signal_threshold == pytest.approx(0.007, rel=1e-5)

        mvs_none = MarketVarianceScore.build([], vix_value=None)
        assert mvs_none.band_width_multiplier == pytest.approx(1.0, rel=1e-5)
        assert mvs_none.signal_threshold == pytest.approx(0.005, rel=1e-5)

    def test_directional_bias(self):
        dims = [make_dim("vix", 0.5, weight=1.0)]
        mvs = MarketVarianceScore.build(dims)
        assert mvs.directional_bias == pytest.approx(0.5, rel=1e-5)

    def test_confidence_override(self):
        mvs_panic = MarketVarianceScore.build(
            [make_dim("vix", -0.5)],
            vix_value=30.0,
        )
        assert mvs_panic.confidence_override == "LOW"

        mvs_fear = MarketVarianceScore.build(
            [make_dim("vix", -0.5)],
            vix_value=23.0,
        )
        assert mvs_fear.confidence_override == "LOW"

        mvs_bull = MarketVarianceScore.build(
            [make_dim("vix", 0.5)],
            vix_value=12.0,
        )
        assert mvs_bull.confidence_override is None

        mvs_uncertain_low = MarketVarianceScore.build(
            [make_dim("vix", 0.3)],
            vix_value=18.0,
        )
        assert mvs_uncertain_low.confidence_override == "LOW"

        mvs_uncertain_high = MarketVarianceScore.build(
            [make_dim("vix", 0.6)],
            vix_value=18.0,
        )
        assert mvs_uncertain_high.confidence_override is None


class TestSerialization:
    def test_to_dict_returns_json_serializable(self):
        mvs = MarketVarianceScore.build(
            [make_dim("vix", -0.8, weight=0.25)],
            vix_value=25.0,
        )
        d = mvs.to_dict()
        import json

        dumped = json.dumps(d)
        assert isinstance(dumped, str)
        assert d["composite"] == pytest.approx(-0.8, rel=1e-5)
        assert d["market_state"] == "fear"
        assert d["confidence_override"] == "LOW"

    def test_to_dict_contains_all_keys(self):
        mvs = MarketVarianceScore.build([], vix_value=20.0)
        d = mvs.to_dict()
        expected_keys = {
            "dimensions",
            "composite",
            "market_state",
            "vix_value",
            "created_at",
            "temperature_adjustment",
            "directional_bias",
            "band_width_multiplier",
            "signal_threshold",
            "confidence_override",
        }
        assert expected_keys.issubset(d.keys())
