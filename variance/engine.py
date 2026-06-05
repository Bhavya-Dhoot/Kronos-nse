"""MarketVarianceEngine — orchestrates all MVE dimension collectors in async loops.

The engine manages the lifecycle of 7 sub-dimension collectors (vix, options,
fii_dii, oi, gift_nifty, global_markets, macro), determines which collectors
are active based on market hours, aggregates sub-dimensions into a composite
Market Variance Score (MVS), publishes to Redis + pub/sub, and exposes
Prometheus metrics for monitoring.

Per D-15: Engine lives in variance/engine.py as a single class with organized methods.
Per D-18: Importable standalone via ``from variance.engine import MarketVarianceEngine``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TypedDict

from prometheus_client import Gauge

from data.storage.redis_cache import RedisCache
from variance.aggregators import (
    GlobalDimensionAggregator,
    InstitutionalDimensionAggregator,
)
from variance.base_collector import BaseVarianceCollector
from variance.schemas import DimensionScore, ParseResult
from variance.score import MarketVarianceScore

logger = logging.getLogger(__name__)


class MarketHoursState(Enum):
    """Market hours state for collector scheduling per D-02.

    CLOSED is reserved for future calendar-based holiday detection; the
    timed state machine never returns CLOSED — GLOBAL_ONLY acts as the
    fallback per D-03.
    """

    CLOSED = "closed"
    PRE_MARKET = "pre_market"  # 9:00–9:15 IST → GIFT + Global only
    MARKET_HOURS = "market_hours"  # 9:15–15:30 IST → all collectors
    POST_MARKET = "post_market"  # 15:30–16:00 IST → all collectors
    GLOBAL_ONLY = "global_only"  # 16:00–9:00 IST → GIFT + Global only


# Active collector names per market state per D-02.
# CLOSED not included — it has no active collectors by definition.
STATE_COLLECTORS: dict[MarketHoursState, set[str]] = {
    MarketHoursState.GLOBAL_ONLY: {"gift_nifty", "global_markets", "macro"},
    MarketHoursState.PRE_MARKET: {"gift_nifty", "global_markets", "macro"},
    MarketHoursState.MARKET_HOURS: {
        "vix",
        "options",
        "fii_dii",
        "oi",
        "gift_nifty",
        "global_markets",
        "macro",
    },
    MarketHoursState.POST_MARKET: {
        "vix",
        "options",
        "fii_dii",
        "oi",
        "gift_nifty",
        "global_markets",
        "macro",
    },
}


class ScoreEntry(TypedDict):
    """Per sub-dimension score tracked by the engine."""

    score: float
    weight: float
    is_stale: bool
    first_poll: bool  # True when first poll completes
    collected_at: str


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_ist_now() -> datetime:
    """Return current IST time as a timezone-aware datetime."""
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=5, minutes=30)


# ── engine ───────────────────────────────────────────────────────────────────


class MarketVarianceEngine:
    """Central orchestrator for all MVE dimension collectors.

    Parameters
    ----------
    collectors : dict[str, BaseVarianceCollector]
        Sub-dimension collectors keyed by name (vix, options, fii_dii, oi,
        gift_nifty, global_markets, macro).
    redis_cache : RedisCache
        Async Redis client for storing per-dimension scores and publishing MVS.
    config : dict[str, Any] | None
        Variance section of the application config (poll intervals, weights, …).
        Defaults to empty dict if None.
    """

    def __init__(
        self,
        collectors: dict[str, BaseVarianceCollector],
        redis_cache: RedisCache,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._collectors = collectors
        self._redis = redis_cache
        self._config = config or {}
        self._config_overlay: dict[str, Any] = {}  # Ephemeral runtime overlay per D-05

        # ── async task tracking ────────────────────────────────────────────
        self._tasks: dict[str, asyncio.Task] = {}
        self._running: bool = False

        # ── score state ────────────────────────────────────────────────────
        self._scores: dict[str, ScoreEntry] = {}
        self._raw_vix: float | None = None
        self._last_mvs_dict: dict[str, Any] | None = None

        # ── publishing ─────────────────────────────────────────────────────
        self._last_composite: float | None = None
        self._mvs_age_tracker: float = 0.0

        # ── lifecycle state ────────────────────────────────────────────────
        self._start_time: float = 0.0
        self._ready: bool = False
        self._degraded: bool = False
        self._current_state: MarketHoursState = MarketHoursState.GLOBAL_ONLY

        # ── Prometheus metrics (ENG-07 / D-19) ─────────────────────────────
        self._metric_composite = Gauge(
            "mve_composite_score", "Current MVS composite score in [-1, 1]"
        )
        self._metric_vix = Gauge(
            "mve_vix_value", "Current India VIX raw value"
        )
        self._metric_collector_up = Gauge(
            "mve_collector_up",
            "Collector health status (1=healthy, 0=circuit-broken)",
            ["collector"],
        )
        self._metric_mvs_age = Gauge(
            "mve_mvs_age_seconds", "Seconds since last MVS recompute"
        )

        logger.info(
            "MarketVarianceEngine initialised with %d collectors",
            len(self._collectors),
        )

    # ── market state ───────────────────────────────────────────────────────

    @staticmethod
    def _get_market_state() -> MarketHoursState:
        """Determine current market hours state from IST time (D-02).

        Returns
        -------
        MarketHoursState
            PRE_MARKET, MARKET_HOURS, POST_MARKET, or GLOBAL_ONLY.
            CLOSED is never returned by this method (handled externally per D-03).
        """
        ist = _get_ist_now()
        total_minutes = ist.hour * 60 + ist.minute

        if 540 <= total_minutes < 555:  # 9:00–9:14
            return MarketHoursState.PRE_MARKET
        if 555 <= total_minutes <= 930:  # 9:15–15:30
            return MarketHoursState.MARKET_HOURS
        if 930 < total_minutes < 960:  # 15:31–15:59
            return MarketHoursState.POST_MARKET
        # 16:00+ or before 9:00
        return MarketHoursState.GLOBAL_ONLY

    # ── config helpers ─────────────────────────────────────────────────────

    def _get_dim_weight(self, name: str) -> float:
        """Return the config weight for a sub-dimension.

        Maps collector names to the top-level weight keys defined in the
        config's ``weights`` section. Sub-dimensions that are part of an
        aggregated group (e.g. fii_dii, oi) use the parent dimension's weight.
        """
        weights = self._config.get("weights", {})
        weight_map: dict[str, str] = {
            "vix": "vix",
            "options": "options",
            "fii_dii": "institutional",
            "oi": "institutional",
            "gift_nifty": "gift_nifty",
            "global_markets": "global_macro",
            "macro": "global_macro",
        }
        key = weight_map.get(name, name)
        return weights.get(key, 0.2)

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Get a config value, checking the runtime overlay first (D-05/D-10).

        Parameters
        ----------
        key : str
            Dot-separated config key, e.g. "weights.vix" or "modification.temperature_base".
        default : Any
            Fallback value if key not found in overlay or base config.

        Returns
        -------
        Any
            Value from overlay if present, else from base config, else default.
        """
        parts = key.split(".")
        # Check overlay first
        overlay_val = self._config_overlay
        for part in parts:
            if isinstance(overlay_val, dict):
                overlay_val = overlay_val.get(part)
            else:
                overlay_val = None
                break
        if overlay_val is not None:
            return overlay_val
        # Fallback to base config
        base_val = self._config
        for part in parts:
            if isinstance(base_val, dict):
                base_val = base_val.get(part)
            else:
                base_val = None
                break
        return base_val if base_val is not None else default

    def apply_config_overlay(self, overlay: dict[str, Any]) -> None:
        """Apply a runtime config overlay (D-05).

        Merges the overlay into self._config_overlay. Does NOT write to YAML.
        Restart restores defaults.

        Parameters
        ----------
        overlay : dict[str, Any]
            Config sections to override (e.g. {"weights": {"vix": 0.30}}).
        """
        for key, value in overlay.items():
            if isinstance(value, dict) and key in self._config_overlay:
                self._config_overlay[key].update(value)
            else:
                self._config_overlay[key] = value

    def get_merged_config(self) -> dict[str, Any]:
        """Return the full merged config (base + overlay) for API response (D-08).

        Returns a deep copy to prevent mutation of internal state. Overlay keys
        replace base keys at the top level.
        """
        import copy

        merged = copy.deepcopy(self._config)
        for key, value in self._config_overlay.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    @property
    def config_overlay(self) -> dict[str, Any]:
        """Return the current runtime config overlay (read-only view)."""
        return dict(self._config_overlay)

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the engine: launch collector poll tasks (D-15 / D-18).

        Determines the current market state and spawns an async task per
        active collector. Each task periodically polls its data source and
        feeds results into the update pipeline.
        """
        self._running = True
        self._start_time = time.monotonic()
        self._current_state = self._get_market_state()

        active = STATE_COLLECTORS.get(self._current_state, set())
        for name in active:
            if name not in self._collectors:
                logger.warning("Collector '%s' not provided — skipping", name)
                continue
            task = asyncio.create_task(
                self._run_collector(name), name=f"mve-{name}"
            )
            self._tasks[name] = task

        logger.info(
            "MVE started with %d collectors in %s state",
            len(self._tasks),
            self._current_state.value,
        )

    async def stop(self) -> None:
        """Stop the engine: cancel all collector tasks (D-15).

        Uses ``return_exceptions=True`` to prevent cancellation errors
        from propagating through the gather.
        """
        self._running = False
        if not self._tasks:
            logger.info("MVE stopped (no active tasks)")
            return

        for name, task in self._tasks.items():
            task.cancel()

        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("MVE stopped — all collector tasks cancelled")

    async def _run_collector(self, name: str) -> None:
        """Async loop: poll a collector at its interval when market state permits.

        Checks the current market state before each poll. If the collector
        is not active in the current state the sleep is skipped so that the
        check happens again on the next interval cycle.

        Parameters
        ----------
        name : str
            Collector key in ``self._collectors``.
        """
        collector = self._collectors[name]
        while self._running:
            # Re-check market state before every poll cycle
            self._current_state = self._get_market_state()

            if name in STATE_COLLECTORS.get(self._current_state, set()):
                try:
                    result = await collector.poll()
                    await self._on_dimension_update(name, result)
                except Exception:
                    logger.exception(
                        "Collector '%s' poll raised unhandled error", name
                    )

            await asyncio.sleep(collector.poll_interval)

    # ── update pipeline ────────────────────────────────────────────────────

    async def _on_dimension_update(
        self, name: str, result: ParseResult
    ) -> None:
        """Process a single poll result from a sub-dimension collector.

        Stores the dimension score, persists to Redis, checks the ready gate
        (D-11 / D-12), evaluates degraded mode (D-13 / D-14), and triggers
        a composite MVS recompute.

        Parameters
        ----------
        name : str
            Collector / sub-dimension name.
        result : ParseResult
            Structured poll result from ``BaseVarianceCollector.poll()``.
        """
        # 1. Extract score and check circuit-breaker
        score_val = result.get("normalized", 0.0)
        collector = self._collectors.get(name)
        is_stale = not collector.is_available if collector else True

        # 2. Store ScoreEntry
        now = datetime.now(timezone.utc).isoformat()
        self._scores[name] = ScoreEntry(
            score=score_val,
            weight=self._get_dim_weight(name),
            is_stale=is_stale,
            first_poll=True,
            collected_at=now,
        )

        # 3. Track raw VIX value for MarketVarianceScore
        if name == "vix":
            self._raw_vix = result.get("raw_value")

        # 4. Per-dimension Redis cache (D-08)
        try:
            await self._redis.set_mve(
                name, dict(self._scores[name]), ttl=60
            )
        except Exception:
            logger.warning("Failed to cache dimension '%s' to Redis", name)

        # 5. Ready gate — count sub-dimensions with first_poll (D-11 / D-12)
        polled = sum(
            1 for entry in self._scores.values() if entry["first_poll"]
        )
        if polled >= 3 and not self._ready:
            self._ready = True
            logger.info(
                "MVE ready — %d sub-dimensions have polled", polled
            )

        # 6. Degraded mode check (D-13 / D-14)
        elapsed = time.monotonic() - self._start_time
        if elapsed > 30.0 and polled < 3 and not self._degraded:
            self._degraded = True
            logger.warning(
                "MVE in degraded mode — %d dimensions after %.0fs",
                polled,
                elapsed,
            )

        # 7. GLOBAL_ONLY auto-activation hint (D-03)
        #    Detect NSE-based collectors returning no data on weekends/holidays.
        #    Logged for visibility; the scoring pipeline handles missing data
        #    gracefully via stale dimension handling.
        if name in {"vix", "options", "fii_dii"}:
            detail = result.get("detail", {})
            raw_val = result.get("raw_value")
            if raw_val is None or detail.get("error") is not None:
                logger.info(
                    "'%s' returned no data — GLOBAL_ONLY state likely",
                    name,
                )

        # 8. Recompute composite MVS
        await self._recompute_mvs()

    async def _recompute_mvs(self) -> None:
        """Recompute the composite MVS and publish if threshold exceeded.

        Builds 4 DimensionScore objects (VIX, Options, Institutional via
        aggregator, Global via aggregator), constructs the MVS, checks the
        1 % publish threshold (D-09), and publishes to Redis + pub/sub (D-10).

        Prometheus metrics are updated on every recompute (ENG-07 / D-19).
        """
        dims: list[DimensionScore] = []

        # ── VIX ─────────────────────────────────────────────────────────────
        if "vix" in self._scores:
            dims.append(
                DimensionScore(
                    name="vix",
                    score=self._scores["vix"]["score"],
                    weight=self._scores["vix"]["weight"],
                    is_stale=self._scores["vix"]["is_stale"],
                    detail={},
                    collected_at=self._scores["vix"]["collected_at"],
                )
            )

        # ── Options ─────────────────────────────────────────────────────────
        if "options" in self._scores:
            dims.append(
                DimensionScore(
                    name="options",
                    score=self._scores["options"]["score"],
                    weight=self._scores["options"]["weight"],
                    is_stale=self._scores["options"]["is_stale"],
                    detail={},
                    collected_at=self._scores["options"]["collected_at"],
                )
            )

        # ── Institutional (aggregated) ──────────────────────────────────────
        inst_result = InstitutionalDimensionAggregator().compute(
            fii_dii_score=self._scores.get("fii_dii", {}).get("score"),
            oi_score=self._scores.get("oi", {}).get("score"),
            fii_dii_stale=self._scores.get("fii_dii", {}).get(
                "is_stale", True
            ),
            oi_stale=self._scores.get("oi", {}).get("is_stale", True),
        )
        dims.append(inst_result)

        # ── Global (aggregated) ─────────────────────────────────────────────
        gift_score = self._scores.get("gift_nifty", {}).get("score")
        gm_score = self._scores.get("global_markets", {}).get("score")
        mc_score = self._scores.get("macro", {}).get("score")

        # Pre-combine global_markets + macro into a single global sub-score
        global_raw: list[float] = [
            s for s in [gm_score, mc_score] if s is not None
        ]
        global_combined = (
            sum(global_raw) / len(global_raw) if global_raw else None
        )

        global_result = GlobalDimensionAggregator().compute(
            gift_score=gift_score,
            global_score=global_combined,
        )
        dims.append(global_result)

        # ── Build MVS ───────────────────────────────────────────────────────
        if not dims:
            return  # No dimensions yet — nothing to publish

        vix_value = self._raw_vix
        mvs = MarketVarianceScore.build(dims, vix_value=vix_value)
        self._mvs_age_tracker = time.monotonic()

        # 1 % publish threshold (D-09)
        if self._last_composite is not None:
            last = self._last_composite
            denom = max(abs(last), 0.01)
            change = abs(mvs.composite - last) / denom
            if change <= 0.01:
                return  # Change too small — skip publish

        # ── Publish to Redis (ENG-02 / D-10) ────────────────────────────────
        mvs_dict = mvs.to_dict()
        try:
            await self._redis.set_mve("mvs", mvs_dict, ttl=60)
            await self._redis.publish_mvs(mvs_dict)
        except Exception:
            logger.exception("Failed to publish MVS to Redis")

        self._last_composite = mvs.composite
        self._last_mvs_dict = mvs_dict

        # ── Update Prometheus metrics (ENG-07 / D-19) ───────────────────────
        self._metric_composite.set(mvs.composite)
        if vix_value is not None:
            self._metric_vix.set(vix_value)
        for cname, col in self._collectors.items():
            self._metric_collector_up.labels(collector=cname).set(
                1.0 if col.is_available else 0.0
            )
        self._metric_mvs_age.set(time.monotonic() - self._mvs_age_tracker)

    # ── public properties ──────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """Return True when at least 3 sub-dimensions have polled (D-11)."""
        return self._ready

    @property
    def is_degraded(self) -> bool:
        """Return True when fewer than 3 dimensions after 30 s (D-13)."""
        return self._degraded

    @property
    def last_mvs(self) -> dict[str, Any] | None:
        """Return the last published MVS dict, or None if not yet computed.

        Used by FastAPI routes to serve the current composite score.
        """
        return self._last_mvs_dict

    @property
    def active_dimensions(self) -> list[str]:
        """Return sorted list of sub-dimension names that have polled.

        Used by the DQG health check to report active data sources.
        """
        return sorted(self._scores.keys())

    @property
    def health_status(self) -> dict[str, Any]:
        """Return a snapshot of engine health for DQG and API consumption.

        Includes ready/degraded flags, active dimension count, and per-collector
        circuit-breaker status.
        """
        return {
            "ready": self._ready,
            "degraded": self._degraded,
            "active_dimensions": len(self._scores),
            "collectors": {
                name: col.is_available
                for name, col in self._collectors.items()
            },
        }
