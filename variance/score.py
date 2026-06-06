"""MarketVarianceScore dataclass and MarketState enumeration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from variance.schemas import DimensionScore


class MarketState(Enum):
    """Market state classification based on VIX and composite score."""
    PANIC = "panic"
    FEAR = "fear"
    UNCERTAIN = "uncertain"
    BULL_RUN = "bull_run"
    NEUTRAL = "neutral"


@dataclass
class MarketVarianceScore:
    """Composite market variance score with derived modification properties."""

    dimensions: list[DimensionScore]
    composite: float
    market_state: MarketState
    vix_value: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def build(
        cls,
        dimensions: list[DimensionScore],
        vix_value: float | None = None,
    ) -> MarketVarianceScore:
        total_weight = 0.0
        weighted_sum = 0.0

        for dim in dimensions:
            w = dim["weight"] / 2 if dim["is_stale"] else dim["weight"]
            total_weight += w
            weighted_sum += dim["score"] * w

        composite = (weighted_sum / total_weight) if total_weight > 0 else 0.0
        composite = max(-1.0, min(1.0, composite))
        market_state = cls._classify_state(vix_value, composite)
        return cls(
            dimensions=dimensions,
            composite=composite,
            market_state=market_state,
            vix_value=vix_value,
        )

    @staticmethod
    def _classify_state(vix: float | None, composite: float) -> MarketState:
        if vix is None:
            if composite > 0.4:
                return MarketState.BULL_RUN
            if composite < -0.4:
                return MarketState.FEAR
            if -0.4 <= composite <= 0.4:
                return MarketState.UNCERTAIN
            return MarketState.NEUTRAL
        if vix > 22 and composite < -0.4:
            return MarketState.FEAR
        if vix > 28:
            return MarketState.PANIC
        if vix < 14 and composite > 0.4:
            return MarketState.BULL_RUN
        if 14 <= vix <= 22 and -0.4 <= composite <= 0.4:
            return MarketState.UNCERTAIN
        return MarketState.NEUTRAL

    @property
    def temperature_adjustment(self) -> float:
        if self.vix_value is None or self.vix_value <= 15:
            return 0.0
        return min((self.vix_value - 15) * 0.015, 0.3)

    @property
    def directional_bias(self) -> float:
        return self.composite

    @property
    def band_width_multiplier(self) -> float:
        if self.vix_value is None or self.vix_value <= 15:
            return 1.0
        return 1.0 + (self.vix_value - 15) * 0.008

    @property
    def signal_threshold(self) -> float:
        if self.vix_value is None or self.vix_value <= 15:
            return 0.005
        return 0.005 + (self.vix_value - 15) * 0.0002

    @property
    def confidence_override(self) -> str | None:
        if self.market_state in (MarketState.PANIC, MarketState.FEAR):
            return "LOW"
        if self.market_state == MarketState.UNCERTAIN and abs(self.composite) < 0.5:
            return "LOW"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "composite": self.composite,
            "market_state": self.market_state.value,
            "vix_value": self.vix_value,
            "created_at": self.created_at,
            "temperature_adjustment": self.temperature_adjustment,
            "directional_bias": self.directional_bias,
            "band_width_multiplier": self.band_width_multiplier,
            "signal_threshold": self.signal_threshold,
            "confidence_override": self.confidence_override,
        }
