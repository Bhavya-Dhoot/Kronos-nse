"""FastAPI dependency providers for Kronos NSE."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from api.conviction import ConvictionTracker
from data.quality.gate import DataQualityGate
from data.storage.redis_cache import RedisCache
from data.storage.timescale import TimescaleClient
from model.context_builder import ContextBuilder
from model.engine import KronosEngine
from model.factory import InferenceContext
from model.registry import ModelRegistry
from variance.engine import MarketVarianceEngine


def get_conviction_tracker(request: Request) -> ConvictionTracker:
    """Return the conviction tracker from app.state, creating if needed."""
    tracker = getattr(request.app.state, "conviction_tracker", None)
    if tracker is None:
        from api.conviction import ConvictionTracker

        tracker = ConvictionTracker()
        request.app.state.conviction_tracker = tracker
    return tracker


def get_inference_context(request: Request) -> InferenceContext:
    """Return the application inference context from lifespan state."""
    ctx = getattr(request.app.state, "inference", None)
    if ctx is None:
        raise RuntimeError("Inference context not initialized — check app lifespan")
    return ctx


def get_db(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> TimescaleClient:
    """TimescaleDB client from app.state."""
    return ctx.db


def get_redis(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> RedisCache:
    """Redis client from app.state."""
    return ctx.redis


def get_engine(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> KronosEngine:
    """KronosEngine singleton from app.state."""
    return ctx.engine


def get_dqg(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> DataQualityGate:
    """DataQualityGate from app.state."""
    return ctx.dqg


def get_context_builder(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> ContextBuilder:
    """ContextBuilder from app.state."""
    return ctx.context_builder


def get_model_registry(
    ctx: Annotated[InferenceContext, Depends(get_inference_context)],
) -> ModelRegistry:
    """ModelRegistry from app.state."""
    return ctx.registry


def get_operating_mode(request: Request) -> str:
    """Current mutable operating mode stored on app.state."""
    return str(getattr(request.app.state, "operating_mode", "VISUAL")).upper()


def get_mve_engine(request: Request) -> MarketVarianceEngine | None:
    """Return the MarketVarianceEngine from lifespan state, or None."""
    return getattr(request.app.state, "mve", None)


def get_mve_redis(request: Request) -> RedisCache | None:
    """Return the MVE RedisCache from lifespan state, or None."""
    return getattr(request.app.state, "mve_redis", None)
