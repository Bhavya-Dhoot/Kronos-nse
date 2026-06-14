"""Operating mode management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from api.dependencies import get_dqg, get_operating_mode
from api.helpers import dqg_mode, resolve_universe
from api.schemas import AppMode, ModeChangeRequest, ModeChangeResponse, ModeResponse
from data.quality.gate import DataQualityGate, DQGStatus

router = APIRouter(prefix="/mode", tags=["mode"])


@router.get("", response_model=ModeResponse, summary="Get current operating mode")
async def get_mode(
    mode: Annotated[str, Depends(get_operating_mode)],
) -> ModeResponse:
    """Return the active operating mode."""
    return ModeResponse(mode=mode)


@router.post("", response_model=ModeChangeResponse, summary="Change operating mode")
async def change_mode(
    body: ModeChangeRequest,
    request: Request,
    dqg: Annotated[DataQualityGate, Depends(get_dqg)] = ...,
) -> ModeChangeResponse:
    """Change mode with transition validation rules."""
    current = str(getattr(request.app.state, "operating_mode", "COLLECT")).upper()
    target = body.mode
    messages: list[str] = []

    if target == current:
        return ModeChangeResponse(mode=current, messages=["Already in requested mode."])

    if current == AppMode.COLLECT.value and target == AppMode.VISUAL.value:
        universe = resolve_universe(
            str(
                (getattr(request.app.state.inference, "config", {}) or {})
                .get("collector", {})
                .get("universe", "NIFTY50")
            )
        )
        passed = 0
        for symbol in universe[:5]:
            report = await dqg.run(symbol, "5min", dqg_mode("VISUAL"))
            if report.status == DQGStatus.PASS:
                passed += 1
                break
        if passed == 0:
            raise HTTPException(
                status_code=422,
                detail="COLLECT→VISUAL requires DQG PASS for at least one symbol.",
            )
        messages.append("DQG PASS confirmed for at least one symbol.")

    if current == AppMode.VISUAL.value and target == AppMode.HEADLESS.value:
        universe = resolve_universe(
            str(
                (getattr(request.app.state.inference, "config", {}) or {})
                .get("collector", {})
                .get("universe", "NIFTY50")
            )
        )
        reports = await dqg.run_batch(universe, "5min", dqg_mode("HEADLESS"))
        pass_count = sum(1 for r in reports.values() if r.status == DQGStatus.PASS)
        pct = (pass_count / len(universe) * 100) if universe else 0
        if pct <= 80:
            raise HTTPException(
                status_code=422,
                detail=f"VISUAL→HEADLESS requires DQG PASS for >80% of universe (got {pct:.1f}%).",
            )
        messages.append(
            f"DQG PASS for {pct:.1f}% of universe ({pass_count}/{len(universe)})."
        )

    request.app.state.operating_mode = target
    messages.append(f"Mode changed: {current} → {target}")
    return ModeChangeResponse(mode=target, messages=messages)
