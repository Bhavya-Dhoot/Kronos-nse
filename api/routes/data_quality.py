"""DQG HTTP endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_db, get_dqg, get_redis
from api.helpers import (
    dqg_dict_to_response,
    dqg_mode,
    dqg_report_to_response,
    resolve_universe,
)
from api.schemas import DQGReportResponse
from data.quality.gate import DataQualityGate
from data.storage.redis_cache import RedisCache
from data.storage.timescale import TimescaleClient

router = APIRouter(prefix="/dqg", tags=["dqg"])


@router.get(
    "/batch/{universe}",
    response_model=dict[str, DQGReportResponse],
    summary="Run DQG for all symbols in a universe",
)
async def get_dqg_batch(
    universe: str,
    timeframe: str = Query("5min"),
    mode: str = Query("STANDARD"),
    dqg: Annotated[DataQualityGate, Depends(get_dqg)] = ...,
) -> dict[str, DQGReportResponse]:
    """Run DQG concurrently for every symbol in the universe."""
    symbols = resolve_universe(universe)
    reports = await dqg.run_batch(symbols, timeframe, dqg_mode(mode))
    return {sym: dqg_report_to_response(rep) for sym, rep in reports.items()}


@router.get(
    "/history/{symbol}",
    response_model=list[DQGReportResponse],
    summary="DQG report history from database",
)
async def get_dqg_history(
    symbol: str,
    limit: int = Query(50, ge=1, le=500),
    db: Annotated[TimescaleClient, Depends(get_db)] = ...,
) -> list[DQGReportResponse]:
    """Return last 24h of DQG reports for a symbol."""
    rows = await db.get_dqg_history(symbol, limit=limit, hours=24)
    if not rows:
        return []
    return [dqg_dict_to_response(row) for row in rows]


@router.get("/{symbol}", response_model=DQGReportResponse, summary="Latest DQG report")
async def get_dqg_report(
    symbol: str,
    timeframe: str = Query("5min"),
    mode: str = Query("STANDARD"),
    redis: Annotated[RedisCache, Depends(get_redis)] = ...,
    dqg: Annotated[DataQualityGate, Depends(get_dqg)] = ...,
) -> DQGReportResponse:
    """Return cached DQG report from Redis or run a fresh check."""
    cached = await redis.get_dqg_report(symbol, timeframe)
    if cached is not None:
        return dqg_dict_to_response(cached)

    report = await dqg.run(symbol, timeframe, dqg_mode(mode))
    return dqg_report_to_response(report)
