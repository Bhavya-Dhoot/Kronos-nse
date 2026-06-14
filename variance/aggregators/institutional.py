"""Institutional dimension aggregator — combines FII/DII and OI flow scores.

The aggregator applies the configured weighting:
- FII/DII weight: 0.7
- OI weight: 0.3
- Combined weight in MVE: 0.25
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from variance.schemas import DimensionScore

INSTITUTIONAL_WEIGHT = 0.25
FII_DII_WEIGHT = 0.7
OI_WEIGHT = 0.3


class InstitutionalDimensionAggregator:
    """Aggregates FII/DII and OI dimension scores into a single DimensionScore.

    The aggregator handles partial data (one dimension None) gracefully,
    reducing the active weight proportionally.
    """

    def __init__(
        self,
        fii_dii_score: float | None = None,
        oi_score: float | None = None,
        fii_dii_stale: bool = False,
        oi_stale: bool = False,
    ) -> None:
        """Initialize with optional pre-set scores."""
        self.fii_dii_score = fii_dii_score
        self.oi_score = oi_score
        self.fii_dii_stale = fii_dii_stale
        self.oi_stale = oi_stale

    def compute(
        self,
        fii_dii_score: float | None = None,
        oi_score: float | None = None,
        fii_dii_stale: bool = False,
        oi_stale: bool = False,
    ) -> DimensionScore:
        """Compute the combined institutional dimension score.

        Args:
            fii_dii_score: FII/DII flow score [-1, 1], or None if unavailable.
            oi_score: OI flow score [-1, 1], or None if unavailable.
            fii_dii_stale: Whether the FII/DII data is stale.
            oi_stale: Whether the OI data is stale.

        Returns:
            A DimensionScore dict with the aggregated result.
        """
        scores: list[float] = []
        weights: list[float] = []
        stales: list[bool] = []

        if fii_dii_score is not None:
            scores.append(fii_dii_score)
            weights.append(FII_DII_WEIGHT)
            stales.append(fii_dii_stale)

        if oi_score is not None:
            scores.append(oi_score)
            weights.append(OI_WEIGHT)
            stales.append(oi_stale)

        if not scores:
            combined = 0.0
            is_stale = True
            active_weight = 0.0
        else:
            total_weight = sum(weights)
            combined = sum(s * w for s, w in zip(scores, weights)) / total_weight
            is_stale = any(stales)
            active_weight = total_weight

        combined = max(-1.0, min(1.0, combined))
        combined = round(combined, 4)

        detail: dict[str, Any] = {
            "fii_dii_score": fii_dii_score,
            "oi_score": oi_score,
            "fii_dii_stale": fii_dii_stale,
            "oi_stale": oi_stale,
            "active_weight": active_weight,
            "fii_dii_weight": FII_DII_WEIGHT,
            "oi_weight": OI_WEIGHT,
        }

        return DimensionScore(
            name="institutional",
            score=combined,
            weight=INSTITUTIONAL_WEIGHT,
            is_stale=is_stale,
            detail=detail,
            collected_at=datetime.now(UTC).isoformat(),
        )
