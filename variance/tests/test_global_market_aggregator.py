"""Unit tests for GlobalDimensionAggregator.

Tests cover score combination, partial data, stale flags, clamping,
and detail dict completeness. Follows same pattern as test_aggregators.py.
"""

from __future__ import annotations

import pytest

from variance.aggregators.global_market import (
    GIFT_NIFTY_INTERNAL_WEIGHT,
    GLOBAL_MACRO_INTERNAL_WEIGHT,
    GLOBAL_MARKET_COMBINED_WEIGHT,
    GlobalDimensionAggregator,
)


def _drop_collected_at(result: dict) -> dict:
    """Return result without the timestamp key for easy comparison."""
    return {k: v for k, v in result.items() if k != "collected_at"}


class TestGlobalDimensionAggregator:

    def test_combines_both_scores(self):
        """GIFT 0.5 + Global 0.3 = (0.5*0.5 + 0.3*0.5) / 1.0 = 0.4"""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.5, global_score=0.3)
        assert result["name"] == "global_market"
        assert result["score"] == pytest.approx(0.4, abs=1e-4)
        assert result["weight"] == GLOBAL_MARKET_COMBINED_WEIGHT
        assert result["is_stale"] is False
        assert result["detail"]["active_weight"] == 1.0

    def test_combines_opposite_signs(self):
        """GIFT 0.7 + Global -0.5 = (0.7*0.5 + -0.5*0.5) / 1.0 = 0.1"""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.7, global_score=-0.5)
        assert result["score"] == pytest.approx(0.1, abs=1e-4)

    def test_gift_only(self):
        """Global=None -> score = 0.5, active_weight = 0.5"""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.5, global_score=None)
        assert result["score"] == pytest.approx(0.5, abs=1e-4)
        assert result["detail"]["active_weight"] == GIFT_NIFTY_INTERNAL_WEIGHT
        assert result["is_stale"] is False

    def test_global_only(self):
        """GIFT=None -> score = 0.3, active_weight = 0.5"""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=None, global_score=0.3)
        assert result["score"] == pytest.approx(0.3, abs=1e-4)
        assert result["detail"]["active_weight"] == GLOBAL_MACRO_INTERNAL_WEIGHT
        assert result["is_stale"] is False

    def test_both_none_returns_zero(self):
        """Both scores None -> score=0.0, is_stale=True, active_weight=0.0"""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=None, global_score=None)
        assert result["score"] == 0.0
        assert result["is_stale"] is True
        assert result["detail"]["active_weight"] == 0.0

    def test_partial_data_not_stale(self):
        """One dimension available (not stale) -> is_stale=False."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.5, global_score=None)
        assert result["is_stale"] is False
        result2 = agg.compute(gift_score=None, global_score=0.3)
        assert result2["is_stale"] is False

    def test_clamping_above_1(self):
        """Both scores at 1.0 -> clamped to 1.0."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=1.0, global_score=1.0)
        assert result["score"] == 1.0

    def test_clamping_below_neg1(self):
        """Both scores at -1.0 -> clamped to -1.0."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=-1.0, global_score=-1.0)
        assert result["score"] == -1.0

    def test_detail_contains_all_keys(self):
        """Detail dict includes all expected fields."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(
            gift_score=0.5, global_score=0.3,
            gift_stale=True, global_stale=False,
        )
        detail = result["detail"]
        assert "gift_score" in detail
        assert "global_score" in detail
        assert "gift_stale" in detail
        assert "global_stale" in detail
        assert "active_weight" in detail
        assert "gift_internal_weight" in detail
        assert "global_internal_weight" in detail
        assert detail["gift_internal_weight"] == GIFT_NIFTY_INTERNAL_WEIGHT
        assert detail["global_internal_weight"] == GLOBAL_MACRO_INTERNAL_WEIGHT

    def test_stale_flags_passed_through(self):
        """Stale flags reflected in detail and is_stale."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(
            gift_score=0.5, global_score=0.3,
            gift_stale=True, global_stale=False,
        )
        assert result["is_stale"] is True
        assert result["detail"]["gift_stale"] is True
        assert result["detail"]["global_stale"] is False

        result2 = agg.compute(
            gift_score=0.5, global_score=0.3,
            gift_stale=False, global_stale=True,
        )
        assert result2["is_stale"] is True

        result3 = agg.compute(
            gift_score=0.5, global_score=0.3,
            gift_stale=False, global_stale=False,
        )
        assert result3["is_stale"] is False

    def test_collected_at_is_isoformat(self):
        """collected_at contains a valid ISO-8601 timestamp."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.5, global_score=0.3)
        assert "collected_at" in result
        assert "T" in result["collected_at"]
        assert (
            result["collected_at"].endswith("+00:00")
            or result["collected_at"].endswith("Z")
        )

    def test_score_rounded_to_4_places(self):
        """Score rounded to 4 decimal places."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.3333333, global_score=0.6666667)
        score_str = str(result["score"])
        if "." in score_str:
            decimals = len(score_str.split(".")[1])
            assert decimals <= 4, f"Expected <=4 decimal places, got {decimals}"

    def test_default_constructor_no_side_effects(self):
        """Default-constructed aggregator compute() with no args returns stale zero."""
        agg = GlobalDimensionAggregator()
        result = agg.compute()
        assert result["score"] == 0.0
        assert result["is_stale"] is True

    @pytest.mark.parametrize("gift,global_,expected", [
        (0.5, 0.5, 0.5),
        (1.0, -0.5, 0.25),
        (-0.3, 0.1, -0.1),
        (0.0, 1.0, 0.5),
        (-0.8, -0.2, -0.5),
    ])
    def test_parametrized_combinations(self, gift, global_, expected):
        """Various combinations produce correct weighted averages."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=gift, global_score=global_)
        assert result["score"] == pytest.approx(expected, abs=1e-4)

    def test_weight_is_global_market_combined_weight(self):
        """DimensionScore weight equals GLOBAL_MARKET_COMBINED_WEIGHT."""
        agg = GlobalDimensionAggregator()
        result = agg.compute(gift_score=0.5, global_score=0.3)
        assert result["weight"] == GLOBAL_MARKET_COMBINED_WEIGHT
