"""Prediction ledger wrapper for headless operations."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class PredictionLedger:
    """Thin async wrapper around TimescaleDB prediction_ledger operations."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def record(self, prediction: dict[str, Any]) -> int:
        """Persist a prediction result dict and return ledger id."""
        return await self._db.store_prediction(prediction)

    def record_fire_and_forget(self, prediction: dict[str, Any]) -> None:
        """Non-blocking ledger write."""

        async def _write() -> None:
            try:
                await self.record(prediction)
            except Exception:
                logger.exception(
                    "Failed to record prediction for %s", prediction.get("symbol")
                )

        asyncio.create_task(_write())

    async def resolve(
        self,
        ledger_id: int,
        actual_close: list[float],
        actual_high: list[float] | None = None,
        actual_low: list[float] | None = None,
    ) -> None:
        """Resolve a ledger row with actual OHLC arrays."""
        await self._db.resolve_prediction(
            ledger_id,
            actual_close,
            actual_high=actual_high,
            actual_low=actual_low,
        )

    async def get_unresolved(
        self,
        symbol: str,
        older_than_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return unresolved predictions for a symbol."""
        return await self._db.get_unresolved_predictions(
            symbol, older_than_hours=older_than_hours
        )

    async def get_recent_resolved(self, symbol: str, days: int = 7) -> pd.DataFrame:
        """Return recent resolved predictions as a DataFrame."""
        return await self._db.get_recent_resolved(symbol, days=days)

    @staticmethod
    def prediction_from_engine_result(result: dict[str, Any]) -> dict[str, Any]:
        """Normalize KronosEngine output for ledger storage."""
        generated = result.get("generated_at")
        if isinstance(generated, str):
            try:
                generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            except ValueError:
                generated_at = datetime.now(UTC)
        else:
            generated_at = datetime.now(UTC)

        return {
            "symbol": result["symbol"],
            "timeframe": result.get("timeframe", "5min"),
            "mode": result.get("mode", "HEADLESS"),
            "pred_open": result.get("pred_open", []),
            "pred_high": result.get("pred_high", []),
            "pred_low": result.get("pred_low", []),
            "pred_close": result.get("pred_close", []),
            "pred_volume": result.get("pred_volume", []),
            "pred_timestamps": result.get("pred_timestamps", []),
            "model_version": result.get("model_version", "unknown"),
            "generated_at": generated_at,
        }
