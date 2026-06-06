"""Variance MVS API endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from api.schemas import (
    DimensionDetailResponse,
    DimensionScoreSchema,
    VarianceHistoryResponse,
    VarianceScoreResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/variance", tags=["variance"])


@router.get(
    "/score",
    response_model=VarianceScoreResponse,
    summary="Current Market Variance Score",
    responses={204: {"description": "MVS not yet computed or engine not ready"}},
)
async def get_variance_score(request: Request) -> VarianceScoreResponse | Response:
    """Return the latest composite Market Variance Score.

    Returns 204 No Content when the engine is not ready or no MVS has been
    computed yet — consumers should retry with backoff.
    """
    mve = getattr(request.app.state, "mve", None)
    if mve is None or not mve.is_ready:
        return Response(status_code=204)

    last_mvs = mve.last_mvs
    if last_mvs is None:
        return Response(status_code=204)

    dims = [
        DimensionScoreSchema(**d) for d in last_mvs.get("dimensions", [])
    ]

    return VarianceScoreResponse(
        composite=last_mvs["composite"],
        market_state=last_mvs["market_state"],
        vix_value=last_mvs.get("vix_value"),
        created_at=last_mvs["created_at"],
        dimensions=dims,
        temperature_adjustment=last_mvs.get("temperature_adjustment", 0.0),
        directional_bias=last_mvs.get("directional_bias", 0.0),
        band_width_multiplier=last_mvs.get("band_width_multiplier", 1.0),
        signal_threshold=last_mvs.get("signal_threshold", 0.005),
        confidence_override=last_mvs.get("confidence_override"),
    )


@router.get(
    "/dimensions/{name}",
    response_model=DimensionDetailResponse,
    summary="Per-dimension variance detail",
    responses={404: {"description": "Dimension not found"}},
)
async def get_dimension_detail(
    name: str, request: Request
) -> DimensionDetailResponse:
    """Return detailed score data for a single variance dimension.

    Valid dimension names: vix, options, fii_dii, oi, gift_nifty,
    global_markets, macro.
    """
    mve = getattr(request.app.state, "mve", None)
    if mve is None or name not in mve._scores:
        raise HTTPException(
            status_code=404,
            detail=f"Dimension '{name}' not found",
        )

    entry: dict[str, Any] = mve._scores[name]

    # Attempt to extract raw_value from the collector's last successful result
    raw_value: float | None = None
    collector = mve._collectors.get(name)
    if collector is not None:
        last = getattr(collector, "_last_successful_result", None)
        if last is not None:
            raw_value = last.get("raw_value")

    return DimensionDetailResponse(
        name=name,
        score=entry["score"],
        weight=entry["weight"],
        is_stale=entry["is_stale"],
        collected_at=entry["collected_at"],
        raw_value=raw_value,
    )


@router.get(
    "/history",
    response_model=VarianceHistoryResponse,
    summary="Historical MVS entries",
)
async def get_variance_history(
    request: Request,
) -> VarianceHistoryResponse:
    """Return a list of historical MVS entries from Redis.

    Returns an empty list when no history exists or Redis is unavailable.
    The list is capped at 1000 entries with a 24-hour TTL (set by the engine).
    """
    mve_redis = getattr(request.app.state, "mve_redis", None)
    if mve_redis is None:
        return VarianceHistoryResponse(entries=[], total=0)

    try:
        raw_entries = await mve_redis._client.lrange("mve:mvs:history", 0, -1)
    except Exception:
        logger.warning("Failed to fetch MVS history from Redis", exc_info=True)
        return VarianceHistoryResponse(entries=[], total=0)

    entries: list[VarianceScoreResponse] = []
    for raw in raw_entries:
        try:
            mvs_dict = json.loads(raw)
            dims = [
                DimensionScoreSchema(**d)
                for d in mvs_dict.get("dimensions", [])
            ]
            entries.append(
                VarianceScoreResponse(
                    composite=mvs_dict["composite"],
                    market_state=mvs_dict["market_state"],
                    vix_value=mvs_dict.get("vix_value"),
                    created_at=mvs_dict["created_at"],
                    dimensions=dims,
                    temperature_adjustment=mvs_dict.get(
                        "temperature_adjustment", 0.0
                    ),
                    directional_bias=mvs_dict.get("directional_bias", 0.0),
                    band_width_multiplier=mvs_dict.get(
                        "band_width_multiplier", 1.0
                    ),
                    signal_threshold=mvs_dict.get("signal_threshold", 0.005),
                    confidence_override=mvs_dict.get("confidence_override"),
                )
            )
        except (KeyError, json.JSONDecodeError, TypeError):
            logger.warning("Skipping malformed MVS history entry: %s", raw[:80])
            continue

    return VarianceHistoryResponse(entries=entries, total=len(entries))
