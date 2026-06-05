"""Runtime MVE configuration endpoint — ephemeral overlay per D-05."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies import get_mve_engine
from api.schemas import MveConfigResponse, VarianceConfigUpdate
from variance.engine import MarketVarianceEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/variance", tags=["variance-config"])


def _validate_config_update(update: VarianceConfigUpdate) -> list[str]:
    """Validate config field values before applying (D-07).

    Returns a list of error messages. Empty list means valid.
    """
    errors: list[str] = []

    if update.weights is not None:
        for name, weight in update.weights.items():
            if not isinstance(weight, (int, float)) or weight <= 0:
                errors.append(f"weights.{name}: must be a positive number, got {weight}")
            elif weight > 1.0:
                errors.append(f"weights.{name}: must be <= 1.0, got {weight}")

    if update.modification is not None:
        for key, value in update.modification.items():
            if key in (
                "temperature_base",
                "temperature_cap",
                "band_width_per_vix_point",
                "signal_base_threshold",
                "signal_threshold_per_vix_point",
            ):
                if not isinstance(value, (int, float)) or value < 0:
                    errors.append(
                        f"modification.{key}: must be a non-negative number, got {value}"
                    )
            if key == "temperature_cap" and isinstance(value, (int, float)) and value > 1.0:
                errors.append(f"modification.temperature_cap: must be <= 1.0, got {value}")
            if key in ("vix_baseline",) and isinstance(value, (int, float)) and value < 0:
                errors.append(f"modification.{key}: must be non-negative, got {value}")

    if update.poll_interval_seconds is not None:
        for name, interval in update.poll_interval_seconds.items():
            if not isinstance(interval, int) or interval < 10:
                errors.append(
                    f"poll_interval_seconds.{name}: must be >= 10s, got {interval}"
                )

    return errors


@router.patch(
    "/config",
    response_model=MveConfigResponse,
    summary="Update MVE runtime configuration (ephemeral overlay)",
    responses={
        422: {"description": "Validation error"},
        503: {"description": "MVE not available"},
    },
)
async def patch_variance_config(
    request: Request,
    update: VarianceConfigUpdate,
    mve: MarketVarianceEngine | None = Depends(get_mve_engine),
) -> MveConfigResponse:
    """Update MVE runtime configuration via ephemeral overlay.

    Changes apply immediately and are NOT persisted to YAML — restart
    restores defaults from config/base.yaml (D-05).

    Accepts partial updates — only the fields sent are overridden (D-07,
    Claude's discretion: partial updates allowed). Validates all fields
    before applying any (D-07).

    Returns the full merged config snapshot (base + overlay) per D-08.
    """
    if mve is None:
        raise HTTPException(status_code=503, detail="MVE not available")

    # Validate before applying per D-07
    errors = _validate_config_update(update)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    # Build overlay dict from non-None fields
    overlay: dict[str, Any] = {}
    if update.weights is not None:
        overlay["weights"] = update.weights
    if update.modification is not None:
        overlay["modification"] = update.modification
    if update.poll_interval_seconds is not None:
        overlay["poll_interval_seconds"] = update.poll_interval_seconds

    # Apply overlay
    mve.apply_config_overlay(overlay)

    # Return merged config per D-08
    merged = mve.get_merged_config()
    return MveConfigResponse(
        weights=merged.get("weights", {}),
        modification=merged.get("modification", {}),
        poll_interval_seconds=merged.get("poll_interval_seconds", {}),
        engine=merged.get("engine", {}),
        mve_history=merged.get("mve_history", {}),
    )
