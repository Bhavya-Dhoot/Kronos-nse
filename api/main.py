"""FastAPI application factory for Kronos NSE."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.helpers import dqg_report_to_response
from api.routes import data_quality, model_info, modes, predictions, variance as variance_routes, variance_config, websocket
from api.schemas import HealthResponse
from data.quality.gate import DQGFailureError
from model.factory import InferenceContext, build_inference_context, close_inference_context
from model.predictor import PredictionError

import yaml
from data.storage.redis_cache import RedisCache
from variance.collectors import (
    FIIDIICollector, GIFTNiftyCollector, GlobalMarketsCollector,
    MacroCollector, OICollector, OptionsCollector, VIXCollector,
)
from variance.engine import MarketVarianceEngine

REFRESH_TASK: asyncio.Task | None = None

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS cannot contain '*' when allow_credentials=True")
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown: wire inference stack, data refresh, optional headless runner."""
    global REFRESH_TASK
    ctx: InferenceContext | None = getattr(app.state, "inference", None)
    owns_context = ctx is None

    try:
        if owns_context:
            ctx = await build_inference_context()
            app.state.inference = ctx

        mode = os.getenv("APP_MODE", "VISUAL").upper()
        app.state.operating_mode = mode

        model_version = None
        try:
            model_version = ctx.registry.get_production_paths()["version"]
        except FileNotFoundError:
            logger.warning("No production model registered at startup")

        # ── MVE engine initialization (all modes) ─────────────────────────────
        mve: MarketVarianceEngine | None = None
        try:
            with open("config/base.yaml") as f:
                raw_cfg = yaml.safe_load(f)
            variance_cfg = raw_cfg.get("variance", {})

            redis = RedisCache()
            await redis.initialize()

            collectors = {
                "vix": VIXCollector(),
                "options": OptionsCollector(),
                "fii_dii": FIIDIICollector(),
                "oi": OICollector(),
                "gift_nifty": GIFTNiftyCollector(),
                "global_markets": GlobalMarketsCollector(),
                "macro": MacroCollector(),
            }

            mve = MarketVarianceEngine(
                collectors=collectors,
                redis_cache=redis,
                config=variance_cfg,
                timescale=ctx.db,  # Pass TimescaleClient for mve_history persistence (DQG-03)
            )
            await mve.start()
            app.state.mve = mve
            app.state.mve_redis = redis
            logger.info("MVE started (ready=%s, degraded=%s)", mve.is_ready, mve.is_degraded)
        except Exception:
            logger.exception("MVE startup failed — continuing without MVE")
            app.state.mve = None
            app.state.mve_redis = None

        # ── MVS history listener (D-10) ──────────────────────────────────────
        _history_task: asyncio.Task | None = None
        if app.state.mve_redis is not None:
            try:
                _history_task = asyncio.create_task(_variance_history_listener())
                logger.info("MVS history listener started")
            except Exception:
                logger.exception("Failed to start MVS history listener")

        async def _refresh_loop():
            """Periodically fetch fresh Angel One data into TimescaleDB."""
            try:
                from data.collector.angel_client import AngelOneClient
                from data.collector.historical_fetcher import HistoricalFetcher
                from data.storage.timescale import TimescaleClient

                collector_cfg = ctx.config.get("collector") or {}
                universe = collector_cfg.get("universe", "NIFTY50")
                timeframes = collector_cfg.get("timeframes", ["5min", "1day"])
                interval_min = int(collector_cfg.get("incremental_interval_minutes", 5))

                angel_cfg = {**ctx.config.get("angel", {}), **ctx.config}
                client = AngelOneClient(angel_cfg)
                client.authenticate()
                db = TimescaleClient(ctx.config["database_url"])
                await db.initialize()
                fetcher = HistoricalFetcher(client, db, ctx.config)

                while True:
                    t0 = time.monotonic()
                    try:
                        for u_name in [universe, "INDICES", "CONTEXT"]:
                            result = await fetcher.incremental_update(u_name, timeframes)
                            total = sum(v for d in result.values() for v in d.values())
                            if total:
                                logger.info("Refresh %s: %d candles", u_name, total)
                    except Exception:
                        logger.exception("Background refresh failed")
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(interval_min * 60 - elapsed, 60))
            except asyncio.CancelledError:
                pass

        async def _variance_history_listener() -> None:
            """Listen on mve:mvs:updates and persist to mve:mvs:history list.

            Each MVS update is RPUSH-ed to the Redis list, then LTRIM-ed to 1000
            entries. A 24-hour TTL is SETEX on every write (D-10).
            """
            mve_redis_local = getattr(app.state, "mve_redis", None)
            if mve_redis_local is None:
                logger.warning("MVE Redis not available — history listener disabled")
                return
            try:
                pubsub = mve_redis_local.pubsub()
                await pubsub.subscribe("mve:mvs:updates")
                history_key = "mve:mvs:history"
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if not message or message.get("type") != "message":
                        continue
                    try:
                        payload_str = message["data"]
                        # Per D-10: RPUSH, LTRIM to 1000, set TTL 24h
                        await mve_redis_local._client.rpush(
                            history_key, payload_str
                        )
                        await mve_redis_local._client.ltrim(
                            history_key, -1000, -1
                        )
                        await mve_redis_local._client.expire(
                            history_key, 86400
                        )
                    except Exception:
                        logger.exception("Failed to persist MVS history entry")
            except Exception:
                logger.exception("Variance history listener failed — disabling")
            finally:
                try:
                    await pubsub.unsubscribe("mve:mvs:updates")
                    await pubsub.aclose()
                except Exception:
                    pass

        if mode == "VISUAL":
            REFRESH_TASK = asyncio.create_task(_refresh_loop())
            logger.info("Background data refresh started")

        logger.info("Kronos NSE API ready mode=%s model_version=%s", mode, model_version)

        yield
    finally:
        if REFRESH_TASK is not None:
            REFRESH_TASK.cancel()
            REFRESH_TASK = None

        if _history_task is not None:
            _history_task.cancel()
            _history_task = None
            logger.info("MVS history listener stopped")

        # ── MVE shutdown ─────────────────────────────────────────────────────
        mve_shutdown: MarketVarianceEngine | None = getattr(app.state, "mve", None)
        if mve_shutdown is not None:
            await mve_shutdown.stop()
            logger.info("MVE stopped")
        redis_shutdown = getattr(app.state, "mve_redis", None)
        if redis_shutdown is not None:
            await redis_shutdown.close()

        if owns_context and ctx is not None:
            await close_inference_context(ctx)
            app.state.inference = None


def create_app(*, inference_override: InferenceContext | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Kronos NSE",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    if inference_override is not None:
        app.state.inference = inference_override

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DQGFailureError)
    async def dqg_failure_handler(_request: Request, exc: DQGFailureError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "DQG_FAIL",
                "report": dqg_report_to_response(exc.report).model_dump(),
            },
        )

    @app.exception_handler(PredictionError)
    async def prediction_failure_handler(_request: Request, exc: PredictionError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": "PREDICTION_FAILED", "detail": str(exc)},
        )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health(request: Request) -> HealthResponse:
        mode = str(getattr(request.app.state, "operating_mode", "COLLECT"))
        model_version = None
        ctx = getattr(request.app.state, "inference", None)
        if ctx is not None:
            try:
                model_version = ctx.registry.get_production_paths()["version"]
            except FileNotFoundError:
                model_version = None
        return HealthResponse(status="ok", mode=mode.upper(), model_version=model_version)

    app.include_router(predictions.router, prefix="/api/v1")
    app.include_router(data_quality.router, prefix="/api/v1")
    app.include_router(model_info.router, prefix="/api/v1")
    app.include_router(modes.router, prefix="/api/v1")
    app.include_router(websocket.router)
    app.include_router(variance_routes.router, prefix="/api/v1")
    app.include_router(variance_config.router, prefix="/api/v1")

    return app


app = create_app()
