"""Pydantic v2 schemas for Kronos NSE API requests and responses."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AppMode(str, enum.Enum):
    """Valid operating modes for Kronos NSE."""

    COLLECT = "COLLECT"
    BACKTEST = "BACKTEST"
    VISUAL = "VISUAL"
    HEADLESS = "HEADLESS"
    TRAIN = "TRAIN"
    PAPER = "PAPER"


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    mode: str
    model_version: str | None = None


class CheckResult(BaseModel):
    """Single DQG check outcome."""

    passed: bool
    critical: bool
    detail: str


class PredictionResponse(BaseModel):
    """Model prediction returned to clients."""

    symbol: str
    timeframe: str
    mode: str
    generated_at: str
    model_version: str
    pred_open: list[float]
    pred_high: list[float]
    pred_low: list[float]
    pred_close: list[float]
    pred_volume: list[float]
    timestamps: list[str]
    dqg_status: str
    data_coverage: float
    confidence: str
    latency_ms: float | None = None
    cached: bool = False
    data_age_seconds: float | None = None


class DQGReportResponse(BaseModel):
    """DQG report for a symbol."""

    symbol: str
    timeframe: str
    status: str
    checks: dict[str, CheckResult] = Field(default_factory=dict)
    coverage_pct: float
    days_collected: int
    last_candle_time: str | None = None
    recommendation: str | None = None


class ModelInfoResponse(BaseModel):
    """Production model metadata."""

    version: str
    created_at: str | None = None
    is_production: bool = True
    metrics: dict[str, Any] = Field(default_factory=dict)
    train_symbols: list[str] = Field(default_factory=list)


class ModelVersionListItem(BaseModel):
    """Summary row for a registered model version."""

    version: str
    created_at: str | None = None
    is_production: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    promoted_at: str | None = None


class ModelCompareResponse(BaseModel):
    """Metric delta between two model versions."""

    v1: str
    v2: str
    delta: dict[str, Any] = Field(default_factory=dict)


class ModeResponse(BaseModel):
    """Current operating mode."""

    mode: str


class ModeChangeRequest(BaseModel):
    """Request to change operating mode."""

    mode: str

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {m.value for m in AppMode}
        if normalized not in allowed:
            raise ValueError(f"Invalid mode '{value}'. Allowed: {sorted(allowed)}")
        return normalized


class ModeChangeResponse(BaseModel):
    """Result of a mode change attempt."""

    mode: str
    messages: list[str] = Field(default_factory=list)


class SkippedSymbol(BaseModel):
    """Symbol skipped during batch prediction."""

    symbol: str
    reason: str


class BatchPredictionResponse(BaseModel):
    """Batch prediction result with skipped symbols."""

    predictions: list[PredictionResponse]
    skipped: list[SkippedSymbol] = Field(default_factory=list)


class CandleBar(BaseModel):
    """Single OHLCV candle for chart rendering."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleHistoryResponse(BaseModel):
    """Historical candle series for a symbol."""

    symbol: str
    timeframe: str
    candles: list[CandleBar] = Field(default_factory=list)


class DimensionScoreSchema(BaseModel):
    """Single dimension score within an MVS response."""

    name: str
    score: float
    weight: float
    is_stale: bool
    detail: dict[str, Any] = Field(default_factory=dict)
    collected_at: str


class VarianceScoreResponse(BaseModel):
    """Full Market Variance Score response."""

    composite: float
    market_state: str
    vix_value: float | None = None
    created_at: str
    dimensions: list[DimensionScoreSchema] = Field(default_factory=list)
    temperature_adjustment: float = 0.0
    directional_bias: float = 0.0
    band_width_multiplier: float = 1.0
    signal_threshold: float = 0.005
    confidence_override: str | None = None


class DimensionDetailResponse(BaseModel):
    """Per-dimension detail for a single collector."""

    name: str
    score: float
    weight: float
    is_stale: bool
    collected_at: str
    raw_value: float | None = None


class VarianceHistoryResponse(BaseModel):
    """Wrapper for historical MVS entries."""

    entries: list[VarianceScoreResponse] = Field(default_factory=list)
    total: int = 0


class VarianceConfigUpdate(BaseModel):
    """PATCH /api/v1/variance/config request body — all fields optional for partial updates."""

    weights: dict[str, float] | None = None
    modification: dict[str, Any] | None = None
    poll_interval_seconds: dict[str, int] | None = None


class MveConfigResponse(BaseModel):
    """Full merged MVE config (base + overlay) returned after update."""

    weights: dict[str, float] = Field(default_factory=dict)
    modification: dict[str, Any] = Field(default_factory=dict)
    poll_interval_seconds: dict[str, int] = Field(default_factory=dict)
    engine: dict[str, Any] = Field(default_factory=dict)
    mve_history: dict[str, Any] = Field(default_factory=dict)



