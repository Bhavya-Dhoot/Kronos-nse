"""Global dimension aggregator — combines GIFT Nifty and Global Markets/Macro scores.

Per D-05: GIFT Nifty 0.5, Global Markets 0.5 internal weighting.
Per D-06: Combined weight in MVS = 0.30 (sum of gift_nifty 0.15 + global_macro 0.15 config entries).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from variance.schemas import DimensionScore

GLOBAL_MARKET_COMBINED_WEIGHT = 0.30
GIFT_NIFTY_INTERNAL_WEIGHT = 0.5
GLOBAL_MACRO_INTERNAL_WEIGHT = 0.5


class GlobalDimensionAggregator:
    """Aggregates GIFT Nifty and Global Markets/Macro dimension scores into a single DimensionScore.

    The aggregator handles partial data (one dimension None) gracefully,
    reducing the active weight proportionally.
    """

    def __init__(
        self,
        gift_score: float | None = None,
        global_score: float | None = None,
        gift_stale: bool = False,
        global_stale: bool = False,
    ) -> None:
        """Initialize with optional pre-set scores."""
        self.gift_score = gift_score
        self.global_score = global_score
        self.gift_stale = gift_stale
        self.global_stale = global_stale

    def compute(
        self,
        gift_score: float | None = None,
        global_score: float | None = None,
        gift_stale: bool = False,
        global_stale: bool = False,
    ) -> DimensionScore:
        """Compute the combined global market dimension score.

        Args:
            gift_score: GIFT Nifty score [-1, 1], or None if unavailable.
            global_score: Global Markets/Macro score [-1, 1], or None if unavailable.
            gift_stale: Whether the GIFT Nifty data is stale.
            global_stale: Whether the Global Markets data is stale.

        Returns:
            A DimensionScore dict with the aggregated result.
        """
        scores: list[float] = []
        weights: list[float] = []
        stales: list[bool] = []

        if gift_score is not None:
            scores.append(gift_score)
            weights.append(GIFT_NIFTY_INTERNAL_WEIGHT)
            stales.append(gift_stale)

        if global_score is not None:
            scores.append(global_score)
            weights.append(GLOBAL_MACRO_INTERNAL_WEIGHT)
            stales.append(global_stale)

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
            "gift_score": gift_score,
            "global_score": global_score,
            "gift_stale": gift_stale,
            "global_stale": global_stale,
            "active_weight": active_weight,
            "gift_internal_weight": GIFT_NIFTY_INTERNAL_WEIGHT,
            "global_internal_weight": GLOBAL_MACRO_INTERNAL_WEIGHT,
        }

        return DimensionScore(
            name="global_market",
            score=combined,
            weight=GLOBAL_MARKET_COMBINED_WEIGHT,
            is_stale=is_stale,
            detail=detail,
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
