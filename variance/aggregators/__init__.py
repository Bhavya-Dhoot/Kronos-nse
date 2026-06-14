"""Dimension aggregators for MVE — combine related scores into a single DimensionScore."""

from __future__ import annotations

from variance.aggregators.global_market import GlobalDimensionAggregator
from variance.aggregators.institutional import InstitutionalDimensionAggregator

__all__ = [
    "GlobalDimensionAggregator",
    "InstitutionalDimensionAggregator",
]
