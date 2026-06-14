"""Bootstrap inference stack: config, DB, Redis, registry, DQG, engine."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data.collector.context import load_config
from data.quality.gate import DataQualityGate
from data.storage.redis_cache import RedisCache
from data.storage.timescale import TimescaleClient
from model.context_builder import ContextBuilder
from model.engine import KronosEngine
from model.registry import ModelRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InferenceContext:
    """Wired dependencies for inference and API serving."""

    config: dict[str, Any]
    db: TimescaleClient
    redis: RedisCache
    registry: ModelRegistry
    dqg: DataQualityGate
    context_builder: ContextBuilder
    engine: KronosEngine
    owns_db: bool = True
    owns_redis: bool = True


_REQUIRED_CONFIG_KEYS = [
    ("database_url", "postgresql://postgres:kronos@localhost:5432/kronos_nse"),
    ("redis_url", "redis://localhost:6379"),
]


def _validate_config(config: dict[str, Any]) -> None:
    for key, default in _REQUIRED_CONFIG_KEYS:
        val = config.get(key) or os.getenv(key.upper())
        if not val:
            raise RuntimeError(
                f"Missing required config: {key!r}. "
                f"Set the {key.upper()} environment variable or add it to config/base.yaml. "
                f"Default: {default}"
            )


async def build_inference_context(
    *,
    config: dict[str, Any] | None = None,
    db: TimescaleClient | None = None,
    redis: RedisCache | None = None,
    run_migrations: bool = False,
    bootstrap_registry: bool = False,
) -> InferenceContext:
    """Initialize DB, Redis, model registry, DQG, and KronosEngine."""
    config = config or load_config()
    _validate_config(config)
    owns_db = db is None
    owns_redis = redis is None

    if db is None:
        db = TimescaleClient(str(config["database_url"]))
        migrations_dir = None
        if run_migrations:
            migrations_dir = str(
                Path(__file__).resolve().parents[1] / "data" / "storage" / "migrations"  # noqa: ASYNC240
            )
        await db.initialize(migrations_dir=migrations_dir)

    if redis is None:
        redis = RedisCache(config["redis_url"])
        await redis.initialize()

    checkpoint_dir = os.getenv(
        "CHECKPOINT_DIR",
        (config.get("model") or {}).get("checkpoint_dir", "./checkpoints"),
    )
    registry = ModelRegistry(checkpoint_dir)

    if bootstrap_registry and not registry.has_production():
        logger.warning(
            "No production checkpoint found at %s — call registry.bootstrap_from_huggingface() "
            "or register a checkpoint manually.",
            checkpoint_dir,
        )

    dqg = DataQualityGate(config=config, db=db, redis_cache=redis)
    context_builder = ContextBuilder(db, config)

    if not registry.has_production():
        logger.warning(
            "No production checkpoint found at %s — continuing without engine. "
            "Run scripts/bootstrap_checkpoint.py or use DEV_CHECKPOINT=1 for dev stubs.",
            checkpoint_dir,
        )
        engine = None
    else:
        try:
            engine = KronosEngine(
                config=config,
                registry=registry,
                redis_cache=redis,
                dqg=dqg,
                context_builder=context_builder,
                db=db,
            )
        except Exception:
            logger.warning("Engine init failed — continuing without engine")
            engine = None

    return InferenceContext(
        config=config,
        db=db,
        redis=redis,
        registry=registry,
        dqg=dqg,
        context_builder=context_builder,
        engine=engine,
        owns_db=owns_db,
        owns_redis=owns_redis,
    )


async def close_inference_context(ctx: InferenceContext) -> None:
    """Release inference stack resources."""
    errors: list[Exception] = []
    try:
        if ctx.engine is not None:
            await ctx.engine.close()
    except Exception as exc:
        errors.append(exc)
    try:
        if ctx.owns_redis:
            await ctx.redis.close()
    except Exception as exc:
        errors.append(exc)
    try:
        if ctx.owns_db:
            await ctx.db.close()
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise RuntimeError(
            f"close_inference_context encountered {len(errors)} error(s): {'; '.join(str(e) for e in errors)}"
        ) from errors[0]
