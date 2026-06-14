"""Multi-target signal emission (Redis, webhook, CSV, DB)."""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_SCALAR_FIELDS = (
    "symbol",
    "timeframe",
    "mode",
    "direction",
    "confidence",
    "expected_move_pct",
    "last_close",
    "pred_close",
    "model_version",
    "generated_at",
)


class SignalEmitter:
    """Emits trading signals to configured targets concurrently."""

    def __init__(
        self, config: dict[str, Any], redis_cache: Any, *, db: Any | None = None
    ) -> None:
        self._config = config
        self._redis = redis_cache
        self._db = db
        headless_cfg = config.get("headless") or {}
        self._targets: list[str] = list(headless_cfg.get("emit_targets", ["redis"]))
        self._webhook_url = str(headless_cfg.get("webhook_url") or "").strip()
        self._csv_path = Path(
            str(headless_cfg.get("csv_output_path", "./data/signals.csv"))
        )
        self._csv_lock = asyncio.Lock()
        self._csv_header_written = (
            self._csv_path.exists() and self._csv_path.stat().st_size > 0
        )

    async def emit(self, signal: dict[str, Any]) -> None:
        """Fire all configured emission targets; errors are logged per target."""
        handlers = {
            "redis": self._emit_redis,
            "webhook": self._emit_webhook,
            "csv": self._emit_csv,
            "db": self._emit_db,
        }
        tasks = []
        for target in self._targets:
            handler = handlers.get(target)
            if handler is None:
                logger.warning("Unknown emit target: %s", target)
                continue
            tasks.append(self._safe_emit(target, handler, signal))
        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_emit(self, name: str, handler: Any, signal: dict[str, Any]) -> None:
        try:
            await handler(signal)
            logger.debug("Signal emitted via %s for %s", name, signal.get("symbol"))
        except Exception:
            logger.exception(
                "Signal emission failed via %s for %s", name, signal.get("symbol")
            )

    async def _emit_redis(self, signal: dict[str, Any]) -> None:
        await self._redis.publish_signal(signal["symbol"], signal)

    async def _emit_webhook(self, signal: dict[str, Any]) -> None:
        if not self._webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(self._webhook_url, json=signal)
        except httpx.TimeoutException:
            logger.warning("Webhook timeout for %s", signal.get("symbol"))
        except Exception:
            logger.exception("Webhook error for %s", signal.get("symbol"))

    async def _emit_csv(self, signal: dict[str, Any]) -> None:
        row = {k: signal.get(k) for k in _SCALAR_FIELDS if k in signal}
        async with self._csv_lock:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self._csv_header_written
            with self._csv_path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=list(_SCALAR_FIELDS), extrasaction="ignore"
                )
                if write_header:
                    writer.writeheader()
                    self._csv_header_written = True
                writer.writerow(row)

    async def _emit_db(self, signal: dict[str, Any]) -> None:
        if self._db is None:
            return

        async def _insert() -> None:
            try:
                await self._db.store_signal(signal)
            except Exception:
                logger.exception("Failed to store signal for %s", signal.get("symbol"))

        asyncio.create_task(_insert())
