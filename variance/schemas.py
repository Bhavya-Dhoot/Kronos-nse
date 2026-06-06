"""Standardized parse output schemas for MVE dimension collectors."""

from __future__ import annotations

from typing import Any, TypedDict


class ParseResult(TypedDict, total=False):
    """Standardized output from a collector's parse() method."""
    raw_value: float
    normalized: float
    direction: int
    magnitude: float
    detail: dict[str, Any]
    source: str
    as_of: str


class DimensionScore(TypedDict, total=False):
    """Individual dimension score for MarketVarianceScore."""
    name: str
    score: float
    weight: float
    is_stale: bool
    detail: dict[str, Any]
    collected_at: str
