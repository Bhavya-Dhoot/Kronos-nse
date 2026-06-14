"""FastAPI application factory for Kronos NSE."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import yaml
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False
    structlog = None  # type: ignore

from api.helpers import dqg_report_to_response
from api.routes import (
    data_quality,
    model_info,
    modes,
    predictions,
    variance_config,
    websocket,
)
from api.routes import variance as variance_routes
from api.schemas import HealthResponse
from data.quality.gate import DQGFailureError
from data.storage.redis_cache import RedisCache
from model.factory import (
    InferenceContext,
    build_inference_context,
    close_inference_context,
)
from model.predictor import PredictionError
from variance.collectors import (
    FIIDIICollector,
    GIFTNiftyCollector,
    GlobalMarketsCollector,
    MacroCollector,
    OICollector,
    OptionsCollector,
    VIXCollector,
)
from variance.collectors._angel import _set_angel_config
from variance.engine import MarketVarianceEngine

REFRESH_TASK: asyncio.Task | None = None

logger = logging.getLogger(__name__)


def _configure_structured_logging(config: dict[str, Any] | None = None) -> None:
    """Configure structured logging with structlog if available."""
    obs_cfg = (config or {}).get("observability", {})
    log_format = obs_cfg.get("log_format", "json")
    log_level = obs_cfg.get("log_level", "INFO")

    # Configure stdlib logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )

    if not _HAS_STRUCTLOG:
        logger.info("structlog not available, using standard logging")
        return

    # Configure structlog
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    if log_format == "json":
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger.info("Structured logging configured", format=log_format, level=log_level)


_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "storage",
    "migrations",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        logger.warning("CORS_ORIGINS contains '*'; falling back to localhost")
        return ["http://localhost:3000", "http://127.0.0.1:3000"]
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown: wire inference stack, data refresh, optional headless runner."""
    global REFRESH_TASK

    # Configure structured logging early (before any other logs)
    try:
        with open("config/base.yaml") as f:  # noqa: ASYNC230
            raw_cfg = yaml.safe_load(f)
        _configure_structured_logging(raw_cfg)
    except Exception:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    ctx: InferenceContext | None = getattr(app.state, "inference", None)
    owns_context = ctx is None

    _history_task: asyncio.Task | None = None

    try:
        if owns_context:
            ctx = await build_inference_context(run_migrations=True)
            app.state.inference = ctx
        else:
            await ctx.db.run_migrations(_MIGRATIONS_DIR)

        mode = os.getenv("APP_MODE", "VISUAL").upper()
        app.state.operating_mode = mode

        model_version = None
        try:
            model_version = ctx.registry.get_production_paths()["version"]
        except FileNotFoundError:
            logger.warning("No production model registered at startup")

        # ── MVE engine initialization (feature-gated) ──────────────────────────
        mve: MarketVarianceEngine | None = None
        features = ctx.config.get("features", {})
        if features.get("mve_enabled", True):
            try:
                with open("config/base.yaml") as f:  # noqa: ASYNC230
                    raw_cfg = yaml.safe_load(f)
                variance_cfg = raw_cfg.get("variance", {})
                # Pass synthetic_mode from data config
                variance_cfg["synthetic_mode"] = ctx.config.get("data", {}).get(
                    "synthetic_mode", False
                )

                redis = RedisCache()
                await redis.initialize()

                # Store Redis client on app state for rate limit middleware
                app.state.rate_limit_redis = redis

                angel_cfg = ctx.config.get("angel", {})
                if angel_cfg.get("client_id") and angel_cfg.get("api_key"):
                    _set_angel_config(angel_cfg)

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
                logger.info(
                    "MVE started (ready=%s, degraded=%s, synthetic=%s)",
                    mve.is_ready,
                    mve.is_degraded,
                    variance_cfg.get("synthetic_mode", False),
                )
            except Exception:
                logger.exception("MVE startup failed — continuing without MVE")
                app.state.mve = None
                app.state.mve_redis = None
        else:
            logger.info("MVE disabled via features.mve_enabled=false")
            app.state.mve = None
            app.state.mve_redis = None

        _history_task: asyncio.Task | None = None
        features = ctx.config.get("features", {})

        # ── MVS history listener (D-10) ──────────────────────────────────────
        if features.get(
            "structured_logging", True
        ):  # Only run if observability enabled

            async def _variance_history_listener() -> None:
                """Listen on mve:mvs:updates and persist to mve:mvs:history list.

                Each MVS update is RPUSH-ed to the Redis list, then LTRIM-ed to 1000
                entries. A 24-hour TTL is SETEX on every write (D-10).
                """
                mve_redis_local = getattr(app.state, "mve_redis", None)
                if mve_redis_local is None:
                    logger.warning(
                        "MVE Redis not available — history listener disabled"
                    )
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
                            await mve_redis_local.rpush(history_key, payload_str)
                            await mve_redis_local.ltrim(history_key, -1000, -1)
                            await mve_redis_local.expire(history_key, 86400)
                        except Exception:
                            logger.exception("Failed to persist MVS history entry")
                except Exception:
                    logger.exception("Variance history listener failed — disabling")
                finally:
                    try:
                        await pubsub.unsubscribe("mve:mvs:updates")
                        await pubsub.aclose()
                    except Exception:
                        logger.debug("Pubsub cleanup ignored")

        if app.state.mve_redis is not None:
            try:
                _history_task = asyncio.create_task(_variance_history_listener())
                logger.info("MVS history listener started")
            except Exception:
                logger.exception("Failed to start MVS history listener")

        async def _refresh_loop():
            """Periodically fetch fresh Angel One data into TimescaleDB (shares MVE's Angel client).

            Skips entirely when market is closed and data already exists, to avoid
            unnecessary DB scans and API calls outside trading hours.
            """
            try:
                from data.collector.historical_fetcher import HistoricalFetcher
                from scripts.seed_instruments import is_market_open
                from variance.collectors._angel import _get_angel_client

                collector_cfg = ctx.config.get("collector") or {}
                universe = collector_cfg.get("universe", "NIFTY50")
                timeframes = collector_cfg.get("timeframes", ["5min", "1day"])
                interval_min = int(collector_cfg.get("incremental_interval_minutes", 5))

                import pandas as _pd

                angel = _get_angel_client()
                # Use shared DB pool from inference context (avoids creating duplicate pools)
                fetcher = HistoricalFetcher(angel, ctx.db, ctx.config)

                while True:
                    # Skip the entire DB scan when market is closed — no new data
                    if not is_market_open(_pd.Timestamp.now(tz="Asia/Kolkata")):
                        await asyncio.sleep(interval_min * 60)
                        continue
                    t0 = time.monotonic()
                    try:
                        for u_name in [universe, "INDICES", "CONTEXT"]:
                            result = await fetcher.incremental_update(
                                u_name, timeframes
                            )
                            total = sum(v for d in result.values() for v in d.values())
                            if total:
                                logger.info("Refresh %s: %d candles", u_name, total)
                    except Exception:
                        logger.exception("Background refresh failed")
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(interval_min * 60 - elapsed, 60))
            except asyncio.CancelledError:
                pass

        # Background data refresh (feature-gated, VISUAL mode only)
        if mode == "VISUAL" and features.get("adaptive_tui_refresh", True):
            REFRESH_TASK = asyncio.create_task(_refresh_loop())
            logger.info("Background data refresh started")

        logger.info(
            "Kronos NSE API ready mode=%s model_version=%s", mode, model_version
        )

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


class _RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request state and response header."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class _AuthMiddleware(BaseHTTPMiddleware):
    """API Key authentication middleware.

    Skips auth for /health, /docs, /redoc, /openapi.json, and websocket endpoints.
    Expects X-API-Key header with valid key from config.
    If no API keys are configured, auth is disabled (dev mode).
    """

    def __init__(self, app, api_keys: set[str] | None = None):
        super().__init__(app)
        self._api_keys = api_keys or set()
        self._exempt_paths = {
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/ws/ping",
            "/ws/predictions",
            "/ws/ticks",
            "/ws/dqg",
            "/ws/signals",
            "/ws/variance",
        }
        self._enabled = len(self._api_keys) > 0

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Skip auth if disabled (no API keys configured)
        if not self._enabled:
            return await call_next(request)

        # Skip auth for exempt paths
        if request.url.path in self._exempt_paths:
            return await call_next(request)

        # Skip auth for websocket upgrade requests
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check for API key
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key not in self._api_keys:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "UNAUTHORIZED",
                    "detail": "Valid X-API-Key header required",
                },
            )

        return await call_next(request)


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting per API key.

    Uses Redis for distributed rate limiting. Configurable via:
    - rate_limit.requests_per_minute
    - rate_limit.burst
    """

    def __init__(self, app, redis_client: Any = None, rpm: int = 60, burst: int = 10):
        super().__init__(app)
        self._redis = redis_client
        self._rpm = rpm
        self._burst = burst
        self._exempt_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

    def _get_redis(self, request: Request) -> Any:
        """Get Redis client from app state (set after lifespan init)."""
        return getattr(request.app.state, "rate_limit_redis", self._redis)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in self._exempt_paths:
            return await call_next(request)

        redis = self._get_redis(request)
        if redis is None:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or "anonymous"
        key = f"ratelimit:{api_key}"

        try:
            # Token bucket: refill 1 token per 60/rpm seconds
            now = time.time()

            pipe = redis._client.pipeline()
            pipe.hgetall(key)
            results = await pipe.execute()
            bucket = results[0] if results else {}

            tokens = float(bucket.get("tokens", self._burst))
            last_refill = float(bucket.get("last_refill", now))

            # Refill tokens
            elapsed = now - last_refill
            tokens = min(self._burst, tokens + elapsed * (self._rpm / 60.0))

            if tokens >= 1:
                tokens -= 1
                await redis._client.hset(
                    key,
                    mapping={
                        "tokens": str(tokens),
                        "last_refill": str(now),
                    },
                )
                await redis._client.expire(key, 60)
                return await call_next(request)
            else:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "RATE_LIMITED",
                        "detail": f"Rate limit exceeded ({self._rpm} req/min)",
                    },
                    headers={"Retry-After": "1"},
                )
        except Exception:
            # Fail open - allow request if Redis unavailable
            logger.warning("Rate limit check failed, allowing request")
            return await call_next(request)


REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))


class _TimeoutMiddleware(BaseHTTPMiddleware):
    """Raise HTTP 503 if a handler exceeds the configured timeout."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        try:
            return await asyncio.wait_for(call_next(request), timeout=REQUEST_TIMEOUT)
        except TimeoutError:
            logger.warning(
                "Request timeout for %s %s", request.method, request.url.path
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "REQUEST_TIMEOUT",
                    "detail": f"Exceeded {REQUEST_TIMEOUT}s",
                },
            )


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

    # Load auth/rate-limit and features config (sync, runs once at startup)
    try:
        with open("config/base.yaml") as f:  # noqa: ASYNC230
            raw_cfg = yaml.safe_load(f)
        api_cfg = raw_cfg.get("api", {})
        api_keys = set(api_cfg.get("api_keys", []))
        rate_limit_cfg = api_cfg.get("rate_limit", {})
        rpm = rate_limit_cfg.get("requests_per_minute", 60)
        burst = rate_limit_cfg.get("burst", 10)
        features = raw_cfg.get("features", {})
    except Exception:
        api_keys = set()
        rpm = 60
        burst = 10
        features = {}

    app.add_middleware(_RequestIDMiddleware)
    app.add_middleware(
        _TimeoutMiddleware,
    )
    # Auth middleware (runs before CORS) - feature-gated
    if features.get("api_auth_enabled", True):
        app.add_middleware(_AuthMiddleware, api_keys=api_keys)
    # Rate limit middleware (runs after auth) - feature-gated
    if features.get("api_rate_limit_enabled", True):
        app.add_middleware(
            _RateLimitMiddleware,
            redis_client=None,  # Will be set in lifespan after Redis init
            rpm=rpm,
            burst=burst,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DQGFailureError)
    async def dqg_failure_handler(
        _request: Request, exc: DQGFailureError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "DQG_FAIL",
                "report": dqg_report_to_response(exc.report).model_dump(),
            },
        )

    @app.exception_handler(PredictionError)
    async def prediction_failure_handler(
        _request: Request, exc: PredictionError
    ) -> JSONResponse:
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
                paths = ctx.registry.get_production_paths()
                if asyncio.iscoroutine(paths):
                    paths = await paths
                model_version = paths["version"]
            except FileNotFoundError:
                model_version = None
        return HealthResponse(
            status="ok", mode=mode.upper(), model_version=model_version
        )

    app.include_router(predictions.router, prefix="/api/v1")
    app.include_router(data_quality.router, prefix="/api/v1")
    app.include_router(model_info.router, prefix="/api/v1")
    app.include_router(modes.router, prefix="/api/v1")
    app.include_router(websocket.router)
    app.include_router(variance_routes.router, prefix="/api/v1")
    app.include_router(variance_config.router, prefix="/api/v1")

    # Prometheus metrics endpoint (feature-gated)
    if features.get("metrics_endpoint", True):

        @app.get("/metrics", tags=["system"])
        async def metrics(request: Request) -> Response:
            try:
                from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

                return Response(
                    content=generate_latest(), media_type=CONTENT_TYPE_LATEST
                )
            except Exception:
                return Response(
                    content=b"# Metrics unavailable", media_type="text/plain"
                )

    return app


app = create_app()
