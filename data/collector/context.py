"""Shared wiring for DB, Redis, Angel client, and fetchers."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from data.collector.angel_client import AngelOneClient
from data.collector.historical_fetcher import HistoricalFetcher
from data.storage.redis_cache import RedisCache
from data.storage.timescale import TimescaleClient

_angel_lock = asyncio.Lock()


@dataclass(slots=True)
class CollectorContext:
    config: dict[str, Any]
    db: TimescaleClient
    redis: RedisCache
    client: AngelOneClient
    fetcher: HistoricalFetcher


def _resolve_env(val: Any) -> Any:
    """Recursively resolve ${VAR:DEFAULT} patterns in config values."""
    import re

    pattern = re.compile(r"\$\{(\w+):([^}]*)\}")
    if isinstance(val, str):
        m = pattern.fullmatch(val)
        if m:
            return os.getenv(m.group(1), m.group(2))
        return val
    if isinstance(val, dict):
        return {k: _resolve_env(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_resolve_env(v) for v in val]
    return val


def load_config() -> dict[str, Any]:
    load_dotenv()
    base_path = Path(__file__).resolve().parents[2] / "config" / "base.yaml"
    cfg: dict[str, Any] = {}
    if base_path.exists():
        with open(base_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}

    cfg = _resolve_env(cfg)

    angel = {
        "api_key": os.getenv("ANGEL_API_KEY"),
        "client_id": os.getenv("ANGEL_CLIENT_ID"),
        "password": os.getenv("ANGEL_PASSWORD") or os.getenv("ANGEL_PIN"),
        "totp_secret": os.getenv("ANGEL_TOTP_SECRET"),
    }
    cfg["angel"] = angel
    cfg["database_url"] = os.getenv(
        "DATABASE_URL",
        (cfg.get("database") or {}).get(
            "url", "postgresql://postgres:kronos@localhost:5432/kronos_nse"
        ),
    )
    cfg["redis_url"] = os.getenv(
        "REDIS_URL",
        (cfg.get("redis") or {}).get("url", "redis://localhost:6379"),
    )
    return cfg


async def build_collector_context(
    *,
    run_migrations: bool = False,
    authenticate: bool = True,
) -> CollectorContext:
    """Initialize storage + Angel client for collection tasks."""
    config = load_config()
    db = TimescaleClient(config["database_url"])
    migrations_dir = None
    if run_migrations:
        migrations_dir = str(
            Path(__file__).resolve().parents[1] / "storage" / "migrations"
        )  # noqa: ASYNC240
    await db.initialize(migrations_dir=migrations_dir)

    redis = RedisCache(config["redis_url"])
    await redis.initialize()

    angel_cfg = {**config.get("angel", {}), **config}
    # Use the shared MVE Angel client singleton to avoid duplicate auth / rate-limit races
    async with _angel_lock:
        from variance.collectors._angel import _get_angel_client, _set_angel_config

        _set_angel_config(angel_cfg)
        client = _get_angel_client()
    if authenticate and not client.authenticate():
        raise RuntimeError("Angel One authentication failed; check .env credentials.")

    fetcher = HistoricalFetcher(client=client, db=db, config=config)
    return CollectorContext(
        config=config, db=db, redis=redis, client=client, fetcher=fetcher
    )


async def close_collector_context(ctx: CollectorContext) -> None:
    errors: list[Exception] = []
    try:
        ctx.client.stop_websocket()
    except Exception as exc:
        errors.append(exc)
    try:
        await ctx.redis.close()
    except Exception as exc:
        errors.append(exc)
    try:
        await ctx.db.close()
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise RuntimeError(
            f"close_collector_context encountered {len(errors)} error(s): {'; '.join(str(e) for e in errors)}"
        ) from errors[0]
