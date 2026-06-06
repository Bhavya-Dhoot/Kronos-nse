"""TimescaleDB async client for Kronos NSE using asyncpg.

All queries use parameterized statements. Timestamps are returned
in Asia/Kolkata timezone. Bulk inserts use executemany in batches of 1000.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import asyncpg
import pandas as pd

logger = logging.getLogger(__name__)

_IST = "Asia/Kolkata"
_BULK_BATCH = 1000


class TimescaleClient:
    """Async TimescaleDB client backed by an asyncpg connection pool."""

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def initialize(self, migrations_dir: str | None = None) -> None:
        """Create the connection pool and optionally run migrations."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=30,
        )
        logger.info("TimescaleDB pool created (min=%d, max=%d)", self._min_size, self._max_size)

        if migrations_dir:
            await self._run_migrations(migrations_dir)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _run_migrations(self, migrations_dir: str) -> None:
        """Execute all .sql files in migrations_dir in lexicographic order."""
        import os

        files = sorted(
            f for f in os.listdir(migrations_dir) if f.endswith(".sql")
        )
        async with self._pool.acquire() as conn:
            for fname in files:
                path = os.path.join(migrations_dir, fname)
                with open(path, encoding="utf-8") as fh:
                    sql = fh.read()
                await conn.execute(sql)
                logger.info("Migration applied: %s", fname)

    # ── candles ──────────────────────────────────────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles for a symbol/timeframe.

        Uses the candles_5min continuous aggregate view for 5m/15m queries.
        Returns a DataFrame with DatetimeIndex in Asia/Kolkata timezone.
        """
        assert self._pool, "call initialize() first"

        # Query base hypertable; continuous aggregates may lag until refreshed.
        table = "candles"
        tf_filter = "timeframe = $2"
        params: list[Any] = [symbol, timeframe]

        param_idx = len(params) + 1
        where_clauses = [f"symbol = $1"]
        if tf_filter:
            where_clauses.append(tf_filter)

        if start_date:
            where_clauses.append(f"time >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            where_clauses.append(f"time <= ${param_idx}")
            params.append(end_date)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)
        params.append(limit)

        query = f"""
            SELECT time, open, high, low, close, volume
            FROM {table}
            WHERE {where_sql}
            ORDER BY time DESC
            LIMIT ${param_idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(_IST)
        df = df.set_index("time").sort_index()
        return df

    async def bulk_insert_candles(self, candles: list[dict[str, Any]]) -> int:
        """Insert candles in batches of 1000 using executemany.

        Returns total rows inserted.
        """
        assert self._pool, "call initialize() first"

        sql = """
            INSERT INTO candles
                (time, symbol, timeframe, open, high, low, close, volume, is_adjusted, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (symbol, timeframe, time) DO UPDATE SET
                open        = EXCLUDED.open,
                high        = EXCLUDED.high,
                low         = EXCLUDED.low,
                close       = EXCLUDED.close,
                volume      = EXCLUDED.volume,
                is_adjusted = EXCLUDED.is_adjusted,
                source      = EXCLUDED.source
        """

        def _row(c: dict[str, Any]) -> tuple:
            return (
                c["time"], c["symbol"], c["timeframe"],
                float(c["open"]), float(c["high"]), float(c["low"]),
                float(c["close"]), max(float(c.get("volume", 0)), 0.0),
                bool(c.get("is_adjusted", False)),
                str(c.get("source", "angel_one")),
            )

        total = 0
        failed_batches = 0
        batches = math.ceil(len(candles) / _BULK_BATCH)
        async with self._pool.acquire() as conn:
            for i in range(batches):
                batch = candles[i * _BULK_BATCH : (i + 1) * _BULK_BATCH]
                rows = [_row(c) for c in batch]
                try:
                    await conn.executemany(sql, rows)
                    total += len(rows)
                except Exception as exc:
                    failed_batches += 1
                    logger.warning(
                        "bulk_insert_candles: batch %d/%d failed (%d rows): %s",
                        i + 1, batches, len(rows), exc,
                    )
                    # Fall back to row-by-row insert for this batch
                    for row in rows:
                        try:
                            await conn.execute(sql, *row)
                            total += 1
                        except Exception:
                            pass  # skip individual bad rows silently
                logger.debug("bulk_insert_candles: batch %d/%d (%d rows)", i + 1, batches, len(rows))

        if failed_batches:
            logger.warning(
                "bulk_insert_candles: %d/%d batches had errors (inserted %d total)",
                failed_batches, batches, total,
            )
        return total

    async def get_latest_timestamp(
        self, symbol: str, timeframe: str
    ) -> pd.Timestamp | None:
        """Return the most recent candle timestamp for a symbol/timeframe, or None."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT MAX(time) FROM candles
            WHERE symbol = $1 AND timeframe = $2
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query, symbol, timeframe)

        if result is None:
            return None
        return pd.Timestamp(result).tz_convert(_IST)

    # ── prediction ledger ────────────────────────────────────────────────────

    async def store_prediction(self, prediction: dict[str, Any]) -> int:
        """Insert a prediction row and return its ledger id."""
        assert self._pool, "call initialize() first"

        sql = """
            INSERT INTO prediction_ledger
                (symbol, timeframe, mode,
                 pred_open, pred_high, pred_low, pred_close, pred_volume,
                 pred_timestamps, model_version, generated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """
        async with self._pool.acquire() as conn:
            row_id = await conn.fetchval(
                sql,
                prediction["symbol"],
                prediction["timeframe"],
                prediction["mode"],
                list(prediction.get("pred_open", [])),
                list(prediction.get("pred_high", [])),
                list(prediction.get("pred_low", [])),
                list(prediction.get("pred_close", [])),
                list(prediction.get("pred_volume", [])),
                list(prediction.get("pred_timestamps", [])),
                prediction["model_version"],
                prediction.get("generated_at", datetime.utcnow()),
            )
        return int(row_id)

    async def resolve_prediction(
        self,
        ledger_id: int,
        actual_close_array: list[float],
        *,
        actual_high: list[float] | None = None,
        actual_low: list[float] | None = None,
    ) -> None:
        """Fill in actuals, compute mae and directional accuracy, mark resolved."""
        assert self._pool, "call initialize() first"

        sql = """
            UPDATE prediction_ledger SET
                actual_close    = $2,
                actual_high     = COALESCE($3, actual_high),
                actual_low      = COALESCE($4, actual_low),
                resolved_at     = NOW(),
                mae             = (
                    SELECT AVG(ABS(p - a))
                    FROM UNNEST($2::float8[], pred_close) AS t(a, p)
                ),
                directional_acc = (
                    SELECT AVG(
                        CASE WHEN SIGN(p - pred_close[1]) = SIGN(a - pred_close[1])
                             THEN 1.0 ELSE 0.0 END
                    )
                    FROM UNNEST($2::float8[], pred_close) AS t(a, p)
                )
            WHERE id = $1
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                ledger_id,
                actual_close_array,
                actual_high,
                actual_low,
            )

    async def get_unresolved_predictions(
        self,
        symbol: str,
        older_than_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return prediction ledger rows for symbol that are not yet resolved."""
        return await self.get_unresolved(symbol, older_than_hours=older_than_hours)

    async def get_unresolved(
        self,
        symbol: str,
        *,
        older_than_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return unresolved predictions for a symbol older than N hours."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT id, symbol, timeframe, mode, pred_close, pred_timestamps,
                   model_version, generated_at
            FROM prediction_ledger
            WHERE symbol = $1
              AND resolved_at IS NULL
              AND generated_at < NOW() - ($2 || ' hours')::INTERVAL
            ORDER BY generated_at ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, str(older_than_hours))
        return [dict(r) for r in rows]

    async def get_recent_resolved(self, symbol: str, days: int = 7) -> pd.DataFrame:
        """Return recent resolved predictions for drift and analytics."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT generated_at, mae, directional_acc, model_version
            FROM prediction_ledger
            WHERE symbol = $1
              AND resolved_at IS NOT NULL
              AND resolved_at >= NOW() - ($2 || ' days')::INTERVAL
            ORDER BY generated_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, str(days))

        if not rows:
            return pd.DataFrame(columns=["generated_at", "mae", "directional_acc", "model_version"])
        return pd.DataFrame([dict(r) for r in rows])

    async def store_signal(self, signal: dict[str, Any]) -> int:
        """Insert a headless signal row."""
        assert self._pool, "call initialize() first"

        sql = """
            INSERT INTO signals
                (symbol, timeframe, direction, confidence, expected_move_pct,
                 last_close, pred_close, model_version, mode, generated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, COALESCE($10::timestamptz, NOW()))
            RETURNING id
        """
        async with self._pool.acquire() as conn:
            row_id = await conn.fetchval(
                sql,
                signal["symbol"],
                signal.get("timeframe", "5min"),
                signal["direction"],
                signal["confidence"],
                signal.get("expected_move_pct"),
                signal.get("last_close"),
                signal.get("pred_close"),
                signal.get("model_version"),
                signal.get("mode", "HEADLESS"),
                signal.get("generated_at"),
            )
        return int(row_id)

    async def store_paper_trade(self, trade: dict[str, Any]) -> int:
        """Log a paper trade."""
        assert self._pool, "call initialize() first"

        sql = """
            INSERT INTO paper_trades (symbol, direction, entry_price, quantity, signal_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """
        async with self._pool.acquire() as conn:
            row_id = await conn.fetchval(
                sql,
                trade["symbol"],
                trade["direction"],
                trade["entry_price"],
                trade.get("quantity", 1.0),
                trade.get("signal_id"),
            )
        return int(row_id)

    async def get_resolved_predictions(
        self,
        *,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Return resolved prediction ledger rows from the last N days."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT id, symbol, timeframe, pred_close, actual_close,
                   mae, directional_acc, generated_at, resolved_at
            FROM prediction_ledger
            WHERE resolved_at IS NOT NULL
              AND resolved_at >= NOW() - ($1 || ' days')::INTERVAL
            ORDER BY resolved_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, str(days))
        return [dict(r) for r in rows]

    async def count_candles_since(self, since: datetime) -> int:
        """Count candle rows with timestamp since the given time."""
        assert self._pool, "call initialize() first"

        query = "SELECT COUNT(*) FROM candles WHERE time >= $1"
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(query, since)
        return int(count or 0)

    async def get_last_registry_created_at(self) -> datetime | None:
        """Return created_at of the most recent model_registry row."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT created_at FROM model_registry
            ORDER BY created_at DESC
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query)
        return result

    async def upsert_model_registry_row(
        self,
        version: str,
        *,
        val_mae: float | None,
        val_directional_acc: float | None,
        train_symbols: list[str],
        timeframe: str,
        is_production: bool = False,
    ) -> None:
        """Insert or update a model_registry metadata row."""
        assert self._pool, "call initialize() first"

        sql = """
            INSERT INTO model_registry
                (version, val_mae, val_directional_acc, train_symbols, timeframe, is_production)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (version) DO UPDATE SET
                val_mae = EXCLUDED.val_mae,
                val_directional_acc = EXCLUDED.val_directional_acc,
                train_symbols = EXCLUDED.train_symbols,
                timeframe = EXCLUDED.timeframe
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                version,
                val_mae,
                val_directional_acc,
                train_symbols,
                timeframe,
                is_production,
            )

    async def get_dqg_history(
        self,
        symbol: str,
        *,
        limit: int = 50,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return recent DQG reports for a symbol within the last N hours."""
        assert self._pool, "call initialize() first"

        query = """
            SELECT symbol, timeframe, mode, status, coverage_pct, days_collected,
                   checks, recommendation, created_at
            FROM dqg_reports
            WHERE symbol = $1
              AND created_at >= NOW() - ($2 || ' hours')::INTERVAL
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, str(hours), limit)

        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            results.append(item)
        return results

    # ── mve_history ──────────────────────────────────────────────────────────

    async def insert_mve_history(self, mvs_dict: dict[str, Any]) -> None:
        """Insert a single MVS recompute entry into the mve_history hypertable (D-16).

        Parameters
        ----------
        mvs_dict : dict
            The MVS dict from MarketVarianceScore.to_dict().
        """
        if self._pool is None:
            logger.warning("TimescaleDB pool not available — skipping mve_history insert")
            return

        import json

        sql = """
            INSERT INTO mve_history
                (time, composite, market_state, vix_value, dimensions,
                 temperature_adjustment, directional_bias, band_width_multiplier,
                 signal_threshold)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
        """

        dims = mvs_dict.get("dimensions", [])
        # Prune dimensions to core fields to keep JSONB compact
        pruned = [
            {
                "name": d.get("name"),
                "score": d.get("score"),
                "weight": d.get("weight"),
                "is_stale": d.get("is_stale", False),
            }
            for d in dims
        ]

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    sql,
                    mvs_dict.get("created_at"),           # time
                    mvs_dict["composite"],                 # composite
                    mvs_dict["market_state"],               # market_state
                    mvs_dict.get("vix_value"),              # vix_value
                    json.dumps(pruned),                    # dimensions
                    mvs_dict.get("temperature_adjustment", 0.0),    # temperature_adjustment
                    mvs_dict.get("directional_bias", 0.0),          # directional_bias
                    mvs_dict.get("band_width_multiplier", 1.0),     # band_width_multiplier
                    mvs_dict.get("signal_threshold", 0.005),        # signal_threshold
                )
        except Exception:
            logger.exception("Failed to insert mve_history entry")

    async def get_mve_history(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Fetch recent MVS entries from the mve_history hypertable (D-17).

        Used on engine startup to replay history to Redis when Redis cache
        is empty.

        Parameters
        ----------
        limit : int
            Maximum number of entries to return (default 1000).

        Returns
        -------
        list[dict[str, Any]]
            Recent MVS entries ordered by time DESC, converted to MVS dict shape.
        """
        if self._pool is None:
            logger.warning("TimescaleDB pool not available — cannot fetch mve_history")
            return []

        import json

        sql = """
            SELECT time, composite, market_state, vix_value, dimensions,
                   temperature_adjustment, directional_bias, band_width_multiplier,
                   signal_threshold
            FROM mve_history
            ORDER BY time DESC
            LIMIT $1
        """

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, limit)

            entries = []
            for row in rows:
                dims_raw = row["dimensions"]
                if isinstance(dims_raw, str):
                    dims_raw = json.loads(dims_raw)
                entries.append({
                    "composite": float(row["composite"]),
                    "market_state": str(row["market_state"]),
                    "vix_value": float(row["vix_value"]) if row["vix_value"] is not None else None,
                    "created_at": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
                    "dimensions": dims_raw if isinstance(dims_raw, list) else [],
                    "temperature_adjustment": float(row["temperature_adjustment"]),
                    "directional_bias": float(row["directional_bias"]),
                    "band_width_multiplier": float(row["band_width_multiplier"]),
                    "signal_threshold": float(row["signal_threshold"]),
                })

            # Return in chronological order for replay
            return list(reversed(entries))
        except Exception:
            logger.exception("Failed to fetch mve_history")
            return []

    # ── health ───────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the pool can execute a trivial query."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            logger.exception("TimescaleDB health check failed")
            return False
