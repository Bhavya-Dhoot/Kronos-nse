"""Unit tests for InstitutionalDimensionAggregator.

Tests cover score combination, partial data, stale flags, clamping,
and detail dict completeness.
"""

from __future__ import annotations

import pytest

from variance.aggregators.institutional import (
    FII_DII_WEIGHT,
    INSTITUTIONAL_WEIGHT,
    OI_WEIGHT,
    InstitutionalDimensionAggregator,
)


def _drop_collected_at(detail: dict) -> dict:
    """Return detail without the timestamp key for easy comparison."""
    return {k: v for k, v in detail.items() if k != "collected_at"}


class TestInstitutionalDimensionAggregator:

    def test_combines_both_scores(self):
        """FII/DII 0.5 + OI 0.3 = (0.5*0.7 + 0.3*0.3) / 1.0 = 0.44"""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=0.3)
        assert result["name"] == "institutional"
        assert result["score"] == pytest.approx(0.44, abs=1e-4)
        assert result["weight"] == INSTITUTIONAL_WEIGHT
        assert result["is_stale"] is False
        assert result["detail"]["active_weight"] == 1.0

    def test_combines_opposite_signs(self):
        """FII/DII 0.7 + OI -0.5 = (0.7*0.7 + -0.5*0.3) / 1.0 = 0.34"""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.7, oi_score=-0.5)
        assert result["score"] == pytest.approx(0.34, abs=1e-4)

    def test_fii_dii_only(self):
        """OI=None → score = 0.5, active_weight = 0.7"""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=None)
        assert result["score"] == pytest.approx(0.5, abs=1e-4)
        assert result["detail"]["active_weight"] == FII_DII_WEIGHT
        assert result["is_stale"] is False

    def test_oi_only(self):
        """FII/DII=None → score = 0.3, active_weight = 0.3"""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=None, oi_score=0.3)
        assert result["score"] == pytest.approx(0.3, abs=1e-4)
        assert result["detail"]["active_weight"] == OI_WEIGHT
        assert result["is_stale"] is False

    def test_both_none_returns_zero(self):
        """Both scores None → score=0.0, is_stale=True, active_weight=0.0"""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=None, oi_score=None)
        assert result["score"] == 0.0
        assert result["is_stale"] is True
        assert result["detail"]["active_weight"] == 0.0

    def test_partial_data_not_stale(self):
        """One dimension available → is_stale=False (no stale data)."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=None)
        assert result["is_stale"] is False
        result2 = agg.compute(fii_dii_score=None, oi_score=0.3)
        assert result2["is_stale"] is False

    def test_clamping_above_1(self):
        """Both scores at 1.0 → clamped to 1.0."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=1.0, oi_score=1.0)
        assert result["score"] == 1.0

    def test_clamping_below_neg1(self):
        """Both scores at -1.0 → clamped to -1.0."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=-1.0, oi_score=-1.0)
        assert result["score"] == -1.0

    def test_detail_contains_all_keys(self):
        """Detail dict includes all expected fields."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=0.3, fii_dii_stale=True, oi_stale=False)
        detail = result["detail"]
        assert "fii_dii_score" in detail
        assert "oi_score" in detail
        assert "fii_dii_stale" in detail
        assert "oi_stale" in detail
        assert "active_weight" in detail
        assert "fii_dii_weight" in detail
        assert "oi_weight" in detail
        assert detail["fii_dii_weight"] == FII_DII_WEIGHT
        assert detail["oi_weight"] == OI_WEIGHT

    def test_stale_flags_passed_through(self):
        """Stale flags reflected in detail and is_stale."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=0.3, fii_dii_stale=True, oi_stale=False)
        assert result["is_stale"] is True
        assert result["detail"]["fii_dii_stale"] is True
        assert result["detail"]["oi_stale"] is False

        result2 = agg.compute(fii_dii_score=0.5, oi_score=0.3, fii_dii_stale=False, oi_stale=True)
        assert result2["is_stale"] is True

    def test_collected_at_is_isoformat(self):
        """collected_at contains a valid ISO-8601 timestamp."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.5, oi_score=0.3)
        assert "collected_at" in result
        assert "T" in result["collected_at"]
        assert result["collected_at"].endswith("+00:00") or result["collected_at"].endswith("Z")

    def test_score_rounded_to_4_places(self):
        """Score rounded to 4 decimal places."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=0.3333333, oi_score=0.6666667)
        score_str = str(result["score"])
        if "." in score_str:
            decimals = len(score_str.split(".")[1])
            assert decimals <= 4, f"Expected ≤4 decimal places, got {decimals}"

    def test_default_constructor_no_side_effects(self):
        """Default-constructed aggregator compute() with no args returns stale zero."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute()
        assert result["score"] == 0.0
        assert result["is_stale"] is True

    @pytest.mark.parametrize("fii_dii,oi,expected", [
        (0.5, 0.5, 0.5),
        (1.0, -0.5, 0.55),
        (-0.3, 0.1, -0.18),
        (0.0, 1.0, 0.3),
        (-0.8, -0.2, -0.62),
    ])
    def test_parametrized_combinations(self, fii_dii, oi, expected):
        """Various combinations produce correct weighted averages."""
        agg = InstitutionalDimensionAggregator()
        result = agg.compute(fii_dii_score=fii_dii, oi_score=oi)
        assert result["score"] == pytest.approx(expected, abs=1e-4)
