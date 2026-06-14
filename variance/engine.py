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
import random
import time
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, TypedDict

from prometheus_client import CollectorRegistry, Gauge

from data.storage.redis_cache import RedisCache
from variance.aggregators import (
    GlobalDimensionAggregator,
    InstitutionalDimensionAggregator,
)
from variance.base_collector import BaseVarianceCollector
from variance.schemas import DimensionScore, ParseResult
from variance.score import MarketVarianceScore

logger = logging.getLogger(__name__)


class SyntheticCollector(BaseVarianceCollector):
    """Generates realistic synthetic data for dev/CI when real APIs unavailable.

    Produces plausible VIX, options, and other dimension values with
    realistic volatility and correlations.
    """

    def __init__(
        self, name: str, poll_interval: int, base_value: float, volatility: float = 0.1
    ) -> None:
        super().__init__(name=name, poll_interval=poll_interval)
        self._base_value = base_value
        self._volatility = volatility
        self._current_value = base_value

    async def fetch(self) -> Any:
        """Generate synthetic value with mean-reverting random walk."""
        # Mean reversion: drift toward base value
        reversion = 0.1 * (self._base_value - self._current_value)
        # Random shock
        shock = random.gauss(0, self._volatility * self._base_value)
        self._current_value = max(0.1, self._current_value + reversion + shock)
        return {
            "synthetic": True,
            "value": self._current_value,
            "base": self._base_value,
        }

    def parse(self, raw: Any) -> ParseResult:
        value = (
            raw.get("value", self._base_value)
            if isinstance(raw, dict)
            else self._base_value
        )
        return ParseResult(
            raw_value=value,
            normalized=0.0,
            direction=0,
            magnitude=0.0,
            detail={"synthetic": True, "base_value": self._base_value},
            source="synthetic",
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        # Return neutral score for synthetic data
        return 0.0


def _get_ist_now() -> datetime:
    """Return current IST time as a timezone-aware datetime."""
    utc_now = datetime.now(UTC)
    return utc_now + timedelta(hours=5, minutes=30)


class MarketHoursState(Enum):
    """Market hours state for collector scheduling per D-02.

    CLOSED is reserved for future calendar-based holiday detection; the
    timed state machine never returns CLOSED — GLOBAL_ONLY acts as the
    fallback per D-03.
    """

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
    collected_at: str


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_ist_now() -> datetime:
    """Return current IST time as a timezone-aware datetime."""
    utc_now = datetime.now(UTC)
    return utc_now + timedelta(hours=5, minutes=30)


def _get_market_hours_from_config(config: dict[str, Any]) -> tuple[int, int, int, int]:
    """Load market hours from config (with defaults).

    Returns (pre_market_start, market_open, market_close, post_market_end) in minutes since midnight.
    """
    try:
        data_cfg = config.get("data", {})
        open_str = data_cfg.get("market_open", "09:15")
        close_str = data_cfg.get("market_close", "15:30")
        open_h, open_m = map(int, open_str.split(":"))
        close_h, close_m = map(int, close_str.split(":"))
        market_open_min = open_h * 60 + open_m
        market_close_min = close_h * 60 + close_m
        # Pre-market: 15 min before open; Post-market: 30 min after close
        pre_market_start = market_open_min - 15
        post_market_end = market_close_min + 30
        return pre_market_start, market_open_min, market_close_min, post_market_end
    except Exception:
        logger.warning("Failed to load market hours from config, using defaults")
        return 540, 555, 930, 960  # 9:00, 9:15, 15:30, 16:00


def _get_degradation_config(config: dict[str, Any]) -> dict[str, str]:
    """Load degradation contracts from config."""
    defaults = {
        "mve_unavailable": "use_fixed_temperature",
        "redis_unavailable": "skip_cache",
        "db_unavailable": "return_503",
    }
    try:
        deg_cfg = config.get("degradation", {})
        return {k: deg_cfg.get(k, v) for k, v in defaults.items()}
    except Exception:
        return defaults


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
        timescale: Any
        | None = None,  # TimescaleClient for mve_history persistence (DQG-03 / D-16)
    ) -> None:
        self._collectors = collectors
        self._redis = redis_cache
        self._config = config or {}
        self._config_overlay: dict[str, Any] = {}  # Ephemeral runtime overlay per D-05
        self._timescale = (
            timescale  # TimescaleClient for mve_history persistence (DQG-03 / D-16)
        )

        # ── async task tracking ────────────────────────────────────────────
        self._tasks: dict[str, asyncio.Task] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._task_failures: dict[str, int] = {}
        self._active_collector_names: set[str] = set()
        self._running: bool = False
        self._state_watcher_task: asyncio.Task | None = None

        # ── score state ────────────────────────────────────────────────────
        self._scores: dict[str, ScoreEntry] = {}
        self._raw_vix: float | None = None
        self._last_mvs_dict: dict[str, Any] | None = None

        # ── publishing ─────────────────────────────────────────────────────
        self._last_composite: float | None = None
        self._mvs_age_tracker: float = 0.0

        # Load degradation config
        self._degradation = _get_degradation_config(self._config)

        # ── lifecycle state ────────────────────────────────────────────────
        self._start_time: float = 0.0
        self._current_state: MarketHoursState = MarketHoursState.GLOBAL_ONLY
        self._recompute_lock = asyncio.Lock()

        # ── Prometheus metrics (ENG-07 / D-19) ─────────────────────────────
        # Use dedicated registry per engine instance to avoid duplicate registration
        self._prom_registry = CollectorRegistry()
        self._metric_composite = Gauge(
            "mve_composite_score", "Current MVS composite score in [-1, 1]", registry=self._prom_registry
        )
        self._metric_vix = Gauge(
            "mve_vix_value", "Current India VIX raw value", registry=self._prom_registry
        )
        self._metric_collector_up = Gauge(
            "mve_collector_up",
            "Collector health status (1=healthy, 0=circuit-broken)",
            ["collector"],
            registry=self._prom_registry,
        )
        self._metric_mvs_age = Gauge(
            "mve_mvs_age_seconds", "Seconds since last MVS recompute", registry=self._prom_registry
        )

        logger.info(
            "MarketVarianceEngine initialised with %d collectors",
            len(self._collectors),
        )

        # Load market hours from config
        (
            self._pre_market_start,
            self._market_open,
            self._market_close,
            self._post_market_end,
        ) = _get_market_hours_from_config(self._config)

    # ── market state ───────────────────────────────────────────────────────

    def _get_market_state(self) -> MarketHoursState:
        """Determine current market hours state from IST time (D-02).

        Returns
        -------
        MarketHoursState
            PRE_MARKET, MARKET_HOURS, POST_MARKET, or GLOBAL_ONLY.
            CLOSED is never returned by this method (handled externally per D-03).
        """
        ist = _get_ist_now()
        total_minutes = ist.hour * 60 + ist.minute

        if self._pre_market_start <= total_minutes < self._market_open:
            return MarketHoursState.PRE_MARKET
        if self._market_open <= total_minutes <= self._market_close:
            return MarketHoursState.MARKET_HOURS
        if self._market_close < total_minutes < self._post_market_end:
            return MarketHoursState.POST_MARKET
        # After post-market or before pre-market
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
            if (
                isinstance(value, dict)
                and key in merged
                and isinstance(merged[key], dict)
            ):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    @property
    def config_overlay(self) -> dict[str, Any]:
        """Return the current runtime config overlay (read-only view)."""
        return dict(self._config_overlay)

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _maybe_enable_synthetic(self) -> None:
        """Replace missing collectors with synthetic ones if synthetic_mode enabled."""
        synthetic_mode = self._get_config("synthetic_mode", False)
        if not synthetic_mode:
            return

        synthetic_configs = {
            "vix": (300, 15.0, 0.15),  # 60s poll, base VIX 15, 15% vol
            "options": (300, 1.0, 0.2),  # 300s poll, base PCR 1.0, 20% vol
            "fii_dii": (1800, 0.0, 0.1),  # 1800s poll, neutral, 10% vol
            "oi": (300, 0.0, 0.1),  # 300s poll, neutral, 10% vol
            "gift_nifty": (300, 0.0, 0.05),  # 300s poll, neutral, 5% vol
            "global_markets": (300, 0.0, 0.05),
            "macro": (300, 0.0, 0.05),
        }

        for name, (interval, base, vol) in synthetic_configs.items():
            if name not in self._collectors:
                self._collectors[name] = SyntheticCollector(name, interval, base, vol)
                logger.info(
                    "Enabled synthetic collector for '%s' (base=%.2f, vol=%.0f%%)",
                    name,
                    base,
                    vol * 100,
                )

    async def start(self) -> None:
        """Start the engine: launch collector poll tasks (D-15 / D-18).

        Determines the current market state and spawns an async task per
        active collector. Each task periodically polls its data source and
        feeds results into the update pipeline.
        """
        self._running = True
        self._start_time = time.monotonic()
        self._current_state = self._get_market_state()

        # Check Redis availability per degradation contract
        redis_available = True
        try:
            await self._redis.ping()
        except Exception:
            redis_available = False
            if self._degradation.get("redis_unavailable") == "skip_cache":
                logger.warning(
                    "Redis unavailable — running with skip_cache degradation"
                )
            else:
                logger.error(
                    "Redis unavailable and no skip_cache degradation configured"
                )

        # Enable synthetic collectors if configured (before spawning tasks)
        self._maybe_enable_synthetic()

        active = STATE_COLLECTORS.get(self._current_state, set())
        for name in active:
            if name not in self._collectors:
                logger.warning("Collector '%s' not provided — skipping", name)
                continue
            task = asyncio.create_task(self._run_collector(name), name=f"mve-{name}")
            self._tasks[name] = task
            task.add_done_callback(self._make_collector_done_cb(name))

        logger.info(
            "MVE started with %d collectors in %s state (synthetic=%s, redis=%s)",
            len(self._tasks),
            self._current_state.value,
            self._get_config("synthetic_mode", False),
            redis_available,
        )

        # Start background state watcher for collector reconciliation
        self._state_watcher_task = asyncio.create_task(self._state_watcher())

        # Replay MVS history from TimescaleDB to Redis if needed (D-17)
        if redis_available:
            replay_task = asyncio.create_task(self._replay_history_from_timescaledb())
            self._background_tasks.add(replay_task)
            replay_task.add_done_callback(self._background_tasks.discard)
        else:
            logger.info("Skipping MVS history replay due to Redis unavailability")

    async def stop(self) -> None:
        """Stop the engine: cancel all tasks (D-15).

        Uses ``return_exceptions=True`` to prevent cancellation errors
        from propagating through the gather.
        """
        self._running = False

        if self._state_watcher_task is not None:
            self._state_watcher_task.cancel()

        for t in self._background_tasks:
            t.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        if not self._tasks:
            logger.info("MVE stopped (no active tasks)")
            return

        for name, task in self._tasks.items():
            task.cancel()

        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._active_collector_names.clear()
        logger.info("MVE stopped — all tasks cancelled")

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
        self._active_collector_names.add(name)
        collector = self._collectors[name]
        try:
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

                jitter = collector.poll_interval * random.uniform(-0.1, 0.1)
                await asyncio.sleep(collector.poll_interval + jitter)
        finally:
            self._active_collector_names.discard(name)

    def _make_collector_done_cb(self, name: str):
        def _cb(task: asyncio.Task) -> None:
            try:
                exc = task.exception()
                if exc:
                    self._task_failures[name] = self._task_failures.get(name, 0) + 1
                    logger.error(
                        "MVE collector %s failed (%d): %s",
                        name,
                        self._task_failures[name],
                        exc,
                    )
                    self._active_collector_names.discard(name)
                    self._tasks.pop(name, None)
            except (asyncio.CancelledError, ValueError):
                pass

        return _cb

    async def _state_watcher(self) -> None:
        """Periodically reconcile collectors against current market state."""
        try:
            while self._running:
                old_state = self._current_state
                self._current_state = self._get_market_state()
                if self._current_state != old_state:
                    logger.info(
                        "Market state transition: %s -> %s",
                        old_state.value,
                        self._current_state.value,
                    )
                await self._reconcile_collectors()
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            pass

    async def _reconcile_collectors(self) -> None:
        """Spawn any collectors expected in current state but not yet running."""
        expected = STATE_COLLECTORS.get(self._current_state, set())
        missing = expected - self._active_collector_names
        for name in missing:
            if name not in self._collectors:
                logger.warning("Collector '%s' not provided — skipping", name)
                continue
            task = asyncio.create_task(self._run_collector(name), name=f"mve-{name}")
            self._tasks[name] = task
            logger.info(
                "Spawned missing collector '%s' for state %s",
                name,
                self._current_state.value,
            )

    # ── update pipeline ────────────────────────────────────────────────────

    def _is_dimension_stale(self, name: str) -> bool:
        """Check if dimension data is stale based on age vs 2x poll interval."""
        entry = self._scores.get(name)
        if entry is None:
            return True
        age = (
            datetime.now(UTC) - datetime.fromisoformat(entry["collected_at"])
        ).total_seconds()
        collector = self._collectors.get(name)
        expected_interval = collector.poll_interval if collector else 300
        return age > expected_interval * 2

    def _count_active_dimensions(self) -> int:
        """Count dimensions with non-stale data (within 2x poll interval)."""
        return sum(1 for name in self._scores if not self._is_dimension_stale(name))

    async def _on_dimension_update(self, name: str, result: ParseResult) -> None:
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
        # 1. Extract score
        score_val = result.get("normalized", 0.0)

        # 2. Store ScoreEntry with data-age-based staleness
        now = datetime.now(UTC).isoformat()
        self._scores[name] = ScoreEntry(
            score=score_val,
            weight=self._get_dim_weight(name),
            is_stale=False,
            collected_at=now,
        )

        # 3. Track raw VIX value for MarketVarianceScore
        if name == "vix":
            self._raw_vix = result.get("raw_value")

        # 4. Per-dimension Redis cache (D-08) - respects redis_unavailable degradation
        redis_skip = self._degradation.get("redis_unavailable") == "skip_cache"
        if not redis_skip:
            try:
                await self._redis.set_mve(name, dict(self._scores[name]), ttl=60)
            except Exception:
                logger.warning("Failed to cache dimension '%s' to Redis", name)
        else:
            logger.debug(
                "Skipping Redis cache for '%s' (redis_unavailable=skip_cache)", name
            )

        # 5. Ready gate — real-time check (D-11 / D-12)
        active_count = self._count_active_dimensions()

        # 6. Degraded mode — real-time check (D-13 / D-14)
        elapsed = time.monotonic() - self._start_time
        if elapsed > 30.0 and active_count < 3:
            logger.warning(
                "MVE degraded — %d active dimensions after %.0fs",
                active_count,
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
        async with self._recompute_lock:
            await self._do_recompute_mvs()

    async def _do_recompute_mvs(self) -> None:
        """Unlocked inner recompute, called under _recompute_lock."""
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
            fii_dii_stale=self._scores.get("fii_dii", {}).get("is_stale", True),
            oi_stale=self._scores.get("oi", {}).get("is_stale", True),
        )
        dims.append(inst_result)

        # ── Global (aggregated) ─────────────────────────────────────────────
        gift_score = self._scores.get("gift_nifty", {}).get("score")
        gm_score = self._scores.get("global_markets", {}).get("score")
        mc_score = self._scores.get("macro", {}).get("score")

        # Pre-combine global_markets + macro into a single global sub-score
        global_raw: list[float] = [s for s in [gm_score, mc_score] if s is not None]
        global_combined = sum(global_raw) / len(global_raw) if global_raw else None

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
        mvs_dict = mvs.to_dict()
        self._mvs_age_tracker = time.monotonic()

        # 1 % publish threshold (D-09)
        if self._last_composite is not None:
            last = self._last_composite
            denom = max(abs(last), 0.01)
            change = abs(mvs.composite - last) / denom
            if change <= 0.01:
                self._last_mvs_dict = mvs_dict
                return  # Change too small — skip publish

        # ── Publish to Redis (ENG-02 / D-10) ────────────────────────────────
        redis_skip = self._degradation.get("redis_unavailable") == "skip_cache"
        if not redis_skip:
            try:
                await self._redis.set_mve("mvs", mvs_dict, ttl=60)
                await self._redis.publish_mvs(mvs_dict)
            except Exception:
                logger.exception("Failed to publish MVS to Redis")
        else:
            logger.debug("Skipping Redis MVS publish (redis_unavailable=skip_cache)")

        # ── Persistent mve_history write (DQG-03 / D-16) ──────────────────────
        if self._timescale is not None and mvs_dict is not None:
            try:
                await self._timescale.insert_mve_history(mvs_dict)
            except Exception:
                logger.exception("Failed to persist mve_history entry to TimescaleDB")

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

    # ── TimescaleDB replay ─────────────────────────────────────────────────

    async def _replay_history_from_timescaledb(self) -> None:
        """Replay MVS history from TimescaleDB to Redis if Redis cache is empty (D-17).

        Called during engine start() when Redis mve:mvs:history is empty.
        Replays the last 1000 entries.
        """
        if self._timescale is None:
            return

        try:
            # Check if Redis history is empty
            history_len = await self._redis.llen("mve:mvs:history")
            if history_len is not None and history_len > 0:
                logger.info(
                    "Redis mve:mvs:history has %d entries — skipping TimescaleDB replay",
                    history_len,
                )
                return

            entries = await self._timescale.get_mve_history(limit=1000)
            if not entries:
                logger.info("No mve_history entries to replay from TimescaleDB")
                return

            import json

            history_key = "mve:mvs:history"

            for entry in entries:
                await self._redis._client.rpush(history_key, json.dumps(entry))

            # Trim to 1000 and set 24h TTL (matches D-10 pattern)
            await self._redis._client.ltrim(history_key, -1000, -1)
            await self._redis._client.expire(history_key, 86400)

            logger.info(
                "Replayed %d mve_history entries from TimescaleDB to Redis",
                len(entries),
            )
        except Exception:
            logger.exception("Failed to replay mve_history from TimescaleDB")

    # ── public properties ──────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """Return True when at least 3 sub-dimensions have fresh data (D-11)."""
        elapsed = time.monotonic() - self._start_time
        return elapsed > 30.0 and self._count_active_dimensions() >= 3

    @property
    def is_degraded(self) -> bool:
        """Return True when fewer than 3 active dimensions after 30 s (D-13)."""
        elapsed = time.monotonic() - self._start_time
        return elapsed > 30.0 and self._count_active_dimensions() < 3

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
            "ready": self.is_ready,
            "degraded": self.is_degraded,
            "active_dimensions": len(self._scores),
            "collectors": {
                name: col.is_available for name, col in self._collectors.items()
            },
        }
