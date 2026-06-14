"""Async integration tests for MVE lifecycle (DQG-05).

These tests use direct engine control per D-25 — create MarketVarianceEngine
with mocked collectors, inject dimension updates manually via
_on_dimension_update(). All collectors are MagicMock-based, no live APIs.

Async integration tests (not TestClient) per D-23.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import prometheus_client
import pytest

from data.quality.checks import check_mve_health
from variance.engine import MarketVarianceEngine
from variance.modifier import PredictionModifier

# ── Mock helpers ──────────────────────────────────────────────────────────────


def _make_mock_collector(
    name: str,
    poll_interval: int = 1,
    score: float = 0.0,
    available: bool = True,
    poll_result: dict | None = None,
) -> MagicMock:
    """Create a mock BaseVarianceCollector with controlled behavior.

    Parameters
    ----------
    name : str
        Collector name (vix, options, etc.)
    poll_interval : int
        poll_interval property value (seconds).
    score : float
        Normalized score returned in poll() result.
    available : bool
        is_available property value.
    poll_result : dict | None
        Full poll() return value. If None, builds a default from score.
    """
    collector = MagicMock()
    collector.name = name
    collector.poll_interval = poll_interval
    collector.is_available = available

    if poll_result is None:
        poll_result = {
            "normalized": score,
            "raw_value": None if name != "vix" else 15.0,
            "detail": {},
        }

    collector.poll = AsyncMock(return_value=poll_result)
    return collector


class MockRedis:
    """Minimal mock RedisCache for engine tests.

    Provides just enough interface for the engine to work without
    a real Redis connection.  Tracks publish_mvs calls for test assertions.
    """

    def __init__(self) -> None:
        self.publish_calls: list[dict] = []
        self._client = AsyncMock()
        self._client.lrange = AsyncMock(return_value=[])
        self._client.rpush = AsyncMock()
        self._client.ltrim = AsyncMock()
        self._client.expire = AsyncMock()
        self._client.llen = AsyncMock(return_value=0)

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def set_mve(self, key: str, value: dict, ttl: int = 60) -> None:
        pass

    async def publish_mvs(self, mvs_dict: dict) -> None:
        self.publish_calls.append(mvs_dict)


class MockTimescale:
    """Minimal mock TimescaleClient for engine tests.

    Records inserts for later assertion.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def insert_mve_history(self, mvs_dict: dict) -> None:
        self.entries.append(mvs_dict)

    async def get_mve_history(self, limit: int = 1000) -> list[dict]:
        return []


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_collectors() -> dict[str, MagicMock]:
    """Create a full set of 7 mocked collectors, all healthy."""
    return {
        "vix": _make_mock_collector(
            "vix",
            poll_interval=1,
            score=-0.15,
            poll_result={
                "normalized": -0.15,
                "raw_value": 15.0,
                "detail": {},
            },
        ),
        "options": _make_mock_collector("options", poll_interval=1, score=0.42),
        "fii_dii": _make_mock_collector("fii_dii", poll_interval=1, score=0.55),
        "oi": _make_mock_collector("oi", poll_interval=1, score=-0.22),
        "gift_nifty": _make_mock_collector("gift_nifty", poll_interval=1, score=0.18),
        "global_markets": _make_mock_collector(
            "global_markets", poll_interval=1, score=0.30
        ),
        "macro": _make_mock_collector("macro", poll_interval=1, score=-0.10),
    }


@pytest.fixture
def mock_redis() -> MockRedis:
    return MockRedis()


@pytest.fixture
def mock_timescale() -> MockTimescale:
    return MockTimescale()


@pytest.fixture
def base_config() -> dict:
    """Minimal config matching config/base.yaml §variance structure."""
    return {
        "weights": {
            "vix": 0.25,
            "options": 0.20,
            "institutional": 0.25,
            "gift_nifty": 0.15,
            "global_macro": 0.15,
        },
        "modification": {
            "temperature_base": 0.015,
            "vix_baseline": 15,
            "temperature_cap": 0.3,
            "band_width_per_vix_point": 0.008,
            "signal_base_threshold": 0.005,
            "signal_threshold_per_vix_point": 0.0002,
        },
        "engine": {
            "global_combined_weight": 0.30,
        },
        "mve_history": {
            "retention_days": 30,
        },
        "degradation": {
            "redis_unavailable": "fail",  # Don't skip Redis in tests
        },
    }


@pytest.fixture
def sample_prediction() -> dict:
    """A minimal prediction result dict for modifier tests."""
    return {
        "symbol": "NIFTY",
        "pred_open": [19500.0],
        "pred_high": [19600.0],
        "pred_low": [19400.0],
        "pred_close": [19550.0],
        "pred_volume": [100000.0],
        "pred_timestamps": [datetime.now(UTC).isoformat()],
        "temperature": 0.7,
        "confidence": "MEDIUM",
    }


# ── Autouse fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_prometheus_registry() -> None:
    """Clear MVE-specific Prometheus metrics between tests.

    MarketVarianceEngine.__init__() registers 4 prometheus_client.Gauge
    metrics (``mve_*``) with the global REGISTRY.  Creating multiple engines
    in the same process raises ``ValueError: Duplicated timeseries`` without
    this fixture.

    Only MVE-prefixed collectors are removed — default process/platform/GC
    collectors remain untouched.
    """
    registry = prometheus_client.REGISTRY
    # Collect MVE-specific names (copied to avoid mutation during iteration)
    mve_names = [
        name for name in registry._names_to_collectors if name.startswith("mve_")
    ]
    if not mve_names:
        yield
        return

    # Find the collectors that own these names and unregister them
    collectors_to_remove = set()
    for name in mve_names:
        collector = registry._names_to_collectors.get(name)
        if collector is not None:
            collectors_to_remove.add(collector)

    for collector in collectors_to_remove:
        try:
            registry.unregister(collector)
        except (KeyError, ValueError):
            pass
    yield


# ── Lifecycle Tests (DQG-05 / D-24) ──────────────────────────────────────────


@pytest.mark.asyncio
class TestMVELifecycle:
    """Full MVE lifecycle integration tests.

    Each test creates a MarketVarianceEngine with mocked collectors,
    exercises specific lifecycle scenarios, and verifies outcomes.
    Per D-25: direct engine control with mocked collectors.
    """

    async def test_engine_start_dimension_arrives_mvs_computed(
        self, mock_collectors, mock_redis, base_config
    ):
        """D-24: Engine start → dimension arrives → MVS computed and published.

        Start the engine with mocked collectors, inject dimension updates
        manually, verify MVS is computed when 3+ dimensions arrive.
        """
        engine = MarketVarianceEngine(
            collectors=mock_collectors,
            redis_cache=mock_redis,
            config=base_config,
        )

        # Inject first dimension and verify state stored correctly
        await engine._on_dimension_update(
            "vix",
            {
                "normalized": -0.2,
                "raw_value": 18.0,
                "detail": {},
            },
        )
        assert "vix" in engine._scores
        assert engine._scores["vix"]["score"] == -0.2
        assert engine._raw_vix == 18.0

        # Not yet ready — only 1 dimension polled
        assert engine.is_ready is False

        # Add 2 more dimensions to trigger ready gate (3 needed per D-11)
        for name, score in [("options", 0.3), ("fii_dii", 0.5)]:
            await engine._on_dimension_update(
                name,
                {
                    "normalized": score,
                    "raw_value": None,
                    "detail": {},
                },
            )

        assert engine.is_ready is True  # 3 dimensions = ready
        assert engine.last_mvs is not None
        assert "composite" in engine.last_mvs
        assert "market_state" in engine.last_mvs
        assert "dimensions" in engine.last_mvs

    async def test_fear_state_raises_signal_threshold(
        self, mock_collectors, mock_redis, base_config
    ):
        """D-24: Fear state raises signal_threshold.

        Mock all dimension scores to push composite to fear range
        (VIX > 22 and composite < -0.4). Verify the resulting MVS
        has elevated signal_threshold.
        """
        engine = MarketVarianceEngine(
            collectors=mock_collectors,
            redis_cache=mock_redis,
            config=base_config,
        )

        # Inject dimensions that push to fear state: VIX=25 with negative scores
        # Scores must be aggressive enough to produce composite < -0.4
        fear_scores = {
            "vix": -0.7,
            "options": -0.6,
            "fii_dii": -0.8,
            "oi": -0.5,
            "gift_nifty": -0.5,
            "global_markets": -0.5,
            "macro": -0.4,
        }

        for name, score in fear_scores.items():
            await engine._on_dimension_update(
                name,
                {
                    "normalized": score,
                    "raw_value": 25.0 if name == "vix" else None,
                    "detail": {},
                },
            )

        assert engine.is_ready is True
        assert engine.last_mvs is not None
        mvs = engine.last_mvs

        # Verify fear state — should be at least FEAR with VIX=25
        assert mvs["market_state"] in ("fear", "panic"), (
            f"Expected fear/panic state, got {mvs['market_state']}"
        )

        # signal_threshold should be elevated above base
        # base: 0.005, VIX=25 → signal_threshold = 0.005 + (25-15)*0.0002 = 0.007
        expected_threshold = 0.005 + (25 - 15) * 0.0002
        assert mvs["signal_threshold"] == pytest.approx(
            expected_threshold, abs=0.001
        ), (
            f"Expected signal_threshold ~{expected_threshold}, got {mvs['signal_threshold']}"
        )

    async def test_degraded_mode_continues_serving_last_mvs(
        self, mock_redis, base_config
    ):
        """D-24: Degraded mode — engine continues serving last MVS.

        Start collectors, inject enough dimensions for a good MVS, then
        simulate collector failures (clear scores, set start_time to 35s
        ago, inject just 1 dimension). Engine should be is_degraded=True
        but last_mvs remains available (is_ready is one-way per D-11).
        """
        engine = MarketVarianceEngine(
            collectors={},  # No collectors — nothing can poll
            redis_cache=mock_redis,
            config=base_config,
        )

        # First, inject 3+ dimensions so a good MVS is computed and stored
        for name, score in [("vix", -0.1), ("options", 0.3), ("fii_dii", 0.5)]:
            await engine._on_dimension_update(
                name,
                {
                    "normalized": score,
                    "raw_value": 15.0 if name == "vix" else None,
                    "detail": {},
                },
            )

        assert engine.is_ready is True
        assert engine.last_mvs is not None

        # Now simulate collector failures: set start time to 35s ago
        engine._start_time = engine._start_time - 35  # push past 30s threshold
        # Clear scores to simulate all collectors failing
        engine._scores.clear()

        # Inject just 1 dimension — triggers degraded check (< 3 dims, > 30s)
        await engine._on_dimension_update(
            "vix",
            {
                "normalized": 0.0,
                "raw_value": 15.0,
                "detail": {},
            },
        )

        # Verify degraded state
        # Note: is_ready is one-way (never reverts once 3+ dims polled per D-11).
        # The degraded flag signals that the engine is operating with reduced
        # data sources — the API should still serve MVS data.
        assert engine.is_degraded is True

        # last_mvs should still be available (serving the last computed value)
        assert engine.last_mvs is not None
        assert "composite" in engine.last_mvs
        assert "market_state" in engine.last_mvs

    async def test_engine_injection_modifier_reads_mvs(
        self, mock_collectors, mock_redis, base_config, sample_prediction
    ):
        """D-24: Engine injection — PredictionModifier reads MVS from running engine.

        Start engine with mocked collectors, inject dimensions to generate MVS,
        create PredictionModifier with the engine, verify modifier reads and
        applies MVS correctly.
        """
        engine = MarketVarianceEngine(
            collectors=mock_collectors,
            redis_cache=mock_redis,
            config=base_config,
        )

        # Inject enough dimensions for MVS computation
        for name in ["vix", "options", "fii_dii", "gift_nifty", "global_markets"]:
            coll = mock_collectors[name]
            await engine._on_dimension_update(
                name,
                {
                    "normalized": coll.poll.return_value["normalized"],
                    "raw_value": coll.poll.return_value["raw_value"],
                    "detail": {},
                },
            )

        assert engine.is_ready is True
        assert engine.last_mvs is not None

        # Create PredictionModifier with the running engine
        modifier = PredictionModifier(mve=engine)

        # Verify pre-inference modification works
        orig_temp = 0.7
        adjusted_temp = modifier.modify_pre_inference(orig_temp)
        # Should be >= orig_temp (temperature can only increase per D-05)
        assert adjusted_temp >= orig_temp

        # Verify post-inference modification works
        modified = modifier.modify_post_inference(sample_prediction)
        assert modified is not None
        # pred_close should be in the result
        assert "pred_close" in modified

    async def test_check_mve_health_healthy_degraded_states(
        self, mock_collectors, mock_redis, base_config
    ):
        """D-24: check_mve_health() returns correct data for healthy/degraded.

        Test both healthy (3+ dimensions active) and degraded states
        where some collectors are circuit-broken.
        """
        engine = MarketVarianceEngine(
            collectors=mock_collectors,
            redis_cache=mock_redis,
            config=base_config,
        )

        # ── Test healthy state ──────────────────────────────────────────────
        # Inject 3+ dimensions
        for name in ["vix", "options", "fii_dii"]:
            await engine._on_dimension_update(
                name,
                {
                    "normalized": 0.1,
                    "raw_value": 15.0 if name == "vix" else None,
                    "detail": {},
                },
            )

        health = check_mve_health(engine)
        assert health["passed"] is True
        assert health["critical"] is False  # warning-level per D-01
        assert "active_dimensions" in health
        assert isinstance(health["active_dimensions"], (str, int))
        # active_dimensions is a string like "3/7" in normal case
        active_str = str(health["active_dimensions"])
        parts = active_str.split("/")
        assert int(parts[0]) >= 3, f"Expected at least 3 active dims, got {active_str}"

        # ── Test degraded state with circuit-broken dimensions ──────────────
        # Mark some collectors as unavailable
        for name in ["vix", "options"]:
            mock_collectors[name].is_available = False

        health_degraded = check_mve_health(engine)
        assert health_degraded["passed"] is True  # warning-level still passes
        assert health_degraded["critical"] is False

        # Should report circuit-broken dimensions (those with is_available=False)
        circuit_broken = health_degraded.get("circuit_broken_dimensions", [])
        assert "vix" in circuit_broken
        assert "options" in circuit_broken

    async def test_mve_history_dual_write(
        self, mock_collectors, mock_redis, mock_timescale, base_config
    ):
        """D-24 / D-16: Engine writes MVS to both Redis and TimescaleDB.

        Verify that _recompute_mvs() triggers TimescaleDB insert and
        Redis publish.
        """
        engine = MarketVarianceEngine(
            collectors=mock_collectors,
            redis_cache=mock_redis,
            timescale=mock_timescale,
            config=base_config,
        )

        # Inject dimensions to trigger MVS computation
        for name in ["vix", "options", "fii_dii", "oi", "gift_nifty"]:
            coll = mock_collectors[name]
            await engine._on_dimension_update(
                name,
                {
                    "normalized": coll.poll.return_value["normalized"],
                    "raw_value": coll.poll.return_value["raw_value"],
                    "detail": {},
                },
            )

        # Verify Redis publish was called (tracked by MockRedis.publish_calls)
        assert len(mock_redis.publish_calls) > 0, (
            "Expected at least one Redis publish_mvs call"
        )
        last_redis = mock_redis.publish_calls[-1]
        assert "composite" in last_redis
        assert "market_state" in last_redis

        # Verify mock TimescaleDB received entries
        assert len(mock_timescale.entries) > 0, (
            "Expected at least one TimescaleDB insert"
        )
        last_entry = mock_timescale.entries[-1]
        assert "composite" in last_entry
        assert "market_state" in last_entry
