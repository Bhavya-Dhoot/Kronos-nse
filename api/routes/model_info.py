"""Model metadata and registry endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_model_registry
from api.schemas import ModelCompareResponse, ModelInfoResponse, ModelVersionListItem
from model.registry import ModelRegistry

router = APIRouter(prefix="/model", tags=["model"])


def _train_symbols(metrics: dict) -> list[str]:
    raw = metrics.get("train_symbols")
    if isinstance(raw, list):
        return [str(s) for s in raw]
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


@router.get(
    "/current", response_model=ModelInfoResponse, summary="Production model info"
)
async def get_current_model(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> ModelInfoResponse:
    """Return metadata for the active production model."""
    try:
        paths = registry.get_production_paths()
        version = paths["version"]
        meta = next(
            (v for v in registry.get_all_versions() if v.get("version") == version),
            {"version": version},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    metrics = meta.get("metrics") or {}
    return ModelInfoResponse(
        version=str(meta.get("version", paths["version"])),
        created_at=meta.get("created_at"),
        is_production=True,
        metrics=metrics,
        train_symbols=_train_symbols(metrics),
    )


@router.get(
    "/versions", response_model=list[ModelVersionListItem], summary="All model versions"
)
async def list_model_versions(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> list[ModelVersionListItem]:
    """Return all registered versions sorted by created_at descending."""
    return [
        ModelVersionListItem(
            version=v.get("version", ""),
            created_at=v.get("created_at"),
            is_production=bool(v.get("is_production")),
            metrics=v.get("metrics") or {},
            promoted_at=v.get("promoted_at"),
        )
        for v in registry.get_all_versions()
    ]


@router.get(
    "/compare", response_model=ModelCompareResponse, summary="Compare two versions"
)
async def compare_models(
    v1: str = Query(..., description="Baseline version"),
    v2: str = Query(..., description="Comparison version"),
    registry: Annotated[ModelRegistry, Depends(get_model_registry)] = ...,
) -> ModelCompareResponse:
    """Return metric deltas between two registered model versions."""
    try:
        result = registry.compare(v1, v2)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ModelCompareResponse(v1=result["v1"], v2=result["v2"], delta=result["delta"])
