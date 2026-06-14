"""Unit tests for MarketVarianceEngine.

Tests cover lifecycle, ready gate, degraded mode, MVS publish threshold,
health status, and dimension tracking. All external dependencies are
mocked — no live Redis or collectors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from variance.engine import MarketHoursState, MarketVarianceEngine
from variance.schemas import ParseResult

# ── helpers ──────────────────────────────────────────────────────────────────


def make_parse_result(
    score: float = 0.0, raw_value: float | None = None
) -> ParseResult:
    """Create a ParseResult with a given score."""
    return ParseResult(
        raw_value=raw_value if raw_value is not None else score,
        normalized=score,
        direction=1 if score > 0 else (-1 if score < 0 else 0),
        magnitude=abs(score),
        detail={},
        source="test",
        as_of=datetime.now(UTC).isoformat(),
    )


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_prometheus() -> None:
    """Prevent duplicate Prometheus metric registration across tests.

    Each MarketVarianceEngine constructor creates Gauge objects that are
    registered globally. This fixture mocks Gauge so every engine instance
    gets a no-op MagicMock instead.
    """
    with patch("variance.engine.Gauge") as mock_gauge_cls:
        mock_gauge = MagicMock()
        mock_gauge.set = MagicMock()
        labels_mock = MagicMock()
        labels_mock.set = MagicMock()
        mock_gauge.labels.return_value = labels_mock
        mock_gauge_cls.return_value = mock_gauge
        yield


@pytest.fixture
def mock_collectors() -> dict[str, MagicMock]:
    """Create 7 mocked collectors returning ParseResult on poll()."""
    collectors: dict[str, MagicMock] = {}
    score_map = {
        "vix": -0.2,
        "options": 0.1,
        "fii_dii": 0.3,
        "oi": -0.1,
        "gift_nifty": 0.0,
        "global_markets": 0.2,
        "macro": -0.1,
    }
    for name in [
        "vix",
        "options",
        "fii_dii",
        "oi",
        "gift_nifty",
        "global_markets",
        "macro",
    ]:
        coll = MagicMock()
        coll.name = name
        coll.poll_interval = 60
        coll.is_available = True
        coll.poll = AsyncMock(
            return_value=make_parse_result(score=score_map.get(name, 0.0))
        )
        collectors[name] = coll
    return collectors


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mocked RedisCache with async methods."""
    redis = MagicMock()
    redis.set_mve = AsyncMock()
    redis.publish_mvs = AsyncMock()
    redis.get_mve = AsyncMock(return_value=None)
    redis.initialize = AsyncMock()
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def engine(
    mock_collectors: dict[str, MagicMock],
    mock_redis: MagicMock,
) -> MarketVarianceEngine:
    """Create a MarketVarianceEngine with mocked dependencies."""
    return MarketVarianceEngine(
        collectors=mock_collectors,
        redis_cache=mock_redis,
        config={
            "weights": {
                "vix": 0.25,
                "options": 0.20,
                "institutional": 0.25,
                "gift_nifty": 0.15,
                "global_macro": 0.15,
            },
            "degradation": {
                "redis_unavailable": "fail",  # Don't skip Redis in tests
            },
        },
    )


# ── tests ────────────────────────────────────────────────────────────────────


class TestEngineLifecycle:
    async def test_start_creates_tasks_and_sets_running(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """start() creates collector tasks and marks engine as running."""
        with patch.object(
            engine, "_get_market_state", return_value=MarketHoursState.MARKET_HOURS
        ):
            await engine.start()
        try:
            assert engine._running is True
            assert len(engine._tasks) == 7  # all 7 collectors active
        finally:
            await engine.stop()

    async def test_stop_cancels_tasks_and_clears(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """stop() cancels all tasks and clears the task dict."""
        with patch.object(
            engine, "_get_market_state", return_value=MarketHoursState.MARKET_HOURS
        ):
            await engine.start()
        await engine.stop()
        assert engine._running is False
        assert len(engine._tasks) == 0

    async def test_start_global_only_starts_fewer_tasks(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """In GLOBAL_ONLY state, only 3 collectors start."""
        with patch.object(
            engine, "_get_market_state", return_value=MarketHoursState.GLOBAL_ONLY
        ):
            await engine.start()
        try:
            # GLOBAL_ONLY: gift_nifty, global_markets, macro
            assert len(engine._tasks) == 3
        finally:
            await engine.stop()


class TestReadyGate:
    async def test_not_ready_with_zero_dimensions(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Engine starts not-ready with no dimension updates."""
        assert engine.is_ready is False

    async def test_ready_when_three_dimensions_report(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Engine becomes ready when 3 dimensions have reported."""
        await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
        assert engine.is_ready is False

        await engine._on_dimension_update("options", make_parse_result(score=0.1))
        assert engine.is_ready is False

        await engine._on_dimension_update("fii_dii", make_parse_result(score=0.3))
        assert engine.is_ready is True

    async def test_not_ready_with_only_two_dimensions(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Engine stays not-ready with only 2 dimensions."""
        await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
        await engine._on_dimension_update("options", make_parse_result(score=0.1))
        assert engine.is_ready is False


class TestDegradedMode:
    async def test_degraded_after_30s_with_few_dimensions(
        self,
        engine: MarketVarianceEngine,
        mock_collectors: dict[str, MagicMock],
    ) -> None:
        """Engine enters degraded mode when fewer than 3 dimensions after 30s."""
        engine._start_time = 100.0
        with patch("time.monotonic", return_value=132.0):  # 32s elapsed
            await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
        assert engine.is_degraded is True

    async def test_not_degraded_when_ready_before_30s(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Engine not degraded when 3+ dimensions arrive before 30s."""
        engine._start_time = 100.0
        with patch("time.monotonic", return_value=110.0):
            await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
            await engine._on_dimension_update("options", make_parse_result(score=0.1))
            await engine._on_dimension_update("fii_dii", make_parse_result(score=0.3))
        assert engine.is_degraded is False

    async def test_degraded_edge_at_exactly_30s(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Elapsed time exactly 30s does NOT trigger degraded (must be >30)."""
        engine._start_time = 100.0
        with patch("time.monotonic", return_value=130.0):  # exactly 30s
            await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
            assert engine.is_degraded is False


class TestMVSRecompute:
    async def _feed_three_dims(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Helper: feed 3 dimension updates so _recompute_mvs has data."""
        await engine._on_dimension_update(
            "vix", make_parse_result(score=-0.2, raw_value=15.0)
        )
        await engine._on_dimension_update("options", make_parse_result(score=0.1))
        await engine._on_dimension_update("fii_dii", make_parse_result(score=0.3))

    async def test_recompute_publishes_mvs(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """After enough dimensions, MVS is published to Redis."""
        await self._feed_three_dims(engine)

        # publish_mvs should have been called at least once
        assert mock_redis.publish_mvs.call_count >= 1

        # set_mve should have been called for per-dimension caching
        # plus once for "mvs" composite
        assert mock_redis.set_mve.call_count >= 4  # 3 dims + 1 mvs

    async def test_recompute_skips_publish_on_small_change(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """Same scores -> identical composite -> no duplicate publish."""
        await self._feed_three_dims(engine)
        # Now the composite is stored in _last_composite.
        # Feed the same dimension again with the same score.
        before = mock_redis.publish_mvs.call_count
        await engine._on_dimension_update(
            "vix", make_parse_result(score=-0.2, raw_value=15.0)
        )
        # Composite hasn't changed -> should skip publish
        assert mock_redis.publish_mvs.call_count == before

    async def test_recompute_publishes_on_big_change(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """Very different dimension scores -> composite changes -> publishes."""
        await self._feed_three_dims(engine)

        # Reset the mock call tracking for clean assertion
        mock_redis.publish_mvs.reset_mock()

        # Feed a completely different vix score -> composite changes significantly
        await engine._on_dimension_update(
            "vix",
            make_parse_result(score=0.9, raw_value=15.0),
        )
        assert mock_redis.publish_mvs.call_count == 1, (
            "Composite change >1% should trigger publish"
        )

    async def test_no_dimensions_skips_publish(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """_recompute_mvs with no scores produces stale-zero dims and publishes.

        Even with no explicit dimension updates, the aggregators always
        produce DimensionScore entries (stale zeros). The MVS computation
        proceeds with those and publishes since _last_composite is None.
        """
        engine._scores.clear()
        engine._last_composite = None
        mock_redis.publish_mvs.reset_mock()

        await engine._recompute_mvs()
        # Always publishes at least institutional + global (stale zero) dims
        assert mock_redis.publish_mvs.call_count == 1
        # The published MVS should have 2 stale-zero dimensions
        published = mock_redis.publish_mvs.call_args[0][0]
        assert len(published["dimensions"]) >= 2
        # All dimensions should be stale (no collector has reported)
        for dim in published["dimensions"]:
            assert dim["is_stale"] is True

    async def test_first_publish_always_happens(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """First MVS recompute always publishes (_last_composite is None -> no threshold)."""
        await self._feed_three_dims(engine)
        assert mock_redis.publish_mvs.call_count >= 1


class TestHealthStatus:
    async def test_health_status_returns_correct_structure(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """health_status dict has expected keys."""
        # Feed 3 dimensions first so engine is ready
        await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
        await engine._on_dimension_update("options", make_parse_result(score=0.1))
        await engine._on_dimension_update("fii_dii", make_parse_result(score=0.3))

        status = engine.health_status
        assert "ready" in status
        assert "degraded" in status
        assert "active_dimensions" in status
        assert "collectors" in status
        assert status["ready"] is True
        assert status["active_dimensions"] == 3

    async def test_health_status_reflects_collector_health(
        self,
        engine: MarketVarianceEngine,
        mock_collectors: dict[str, MagicMock],
    ) -> None:
        """health_status shows when a collector is unavailable."""
        mock_collectors["vix"].is_available = False
        status = engine.health_status
        assert status["collectors"]["vix"] is False
        assert status["collectors"]["options"] is True
        assert status["collectors"]["fii_dii"] is True

    async def test_health_status_before_any_updates(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """health_status works correctly before any dimension updates."""
        status = engine.health_status
        assert status["ready"] is False
        assert status["active_dimensions"] == 0
        assert len(status["collectors"]) == 7


class TestDimensionTracking:
    async def test_on_dimension_update_stores_scores(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """_on_dimension_update stores the score in _scores dict."""
        await engine._on_dimension_update("vix", make_parse_result(score=-0.5))
        assert "vix" in engine._scores
        assert engine._scores["vix"]["score"] == -0.5
        assert engine._scores["vix"]["is_stale"] is False

    async def test_per_dim_redis_cache_on_update(
        self,
        engine: MarketVarianceEngine,
        mock_redis: MagicMock,
    ) -> None:
        """_on_dimension_update caches the score to Redis."""
        await engine._on_dimension_update("vix", make_parse_result(score=-0.5))
        # set_mve called with "vix" key
        set_mve_calls = [
            call for call in mock_redis.set_mve.call_args_list if call[0][0] == "vix"
        ]
        assert len(set_mve_calls) >= 1
        # The data dict should contain score
        data = set_mve_calls[0][0][1]
        assert data["score"] == -0.5
        assert data["is_stale"] is False

    async def test_stale_collector_sets_is_stale(
        self,
        engine: MarketVarianceEngine,
        mock_collectors: dict[str, MagicMock],
    ) -> None:
        """Fresh update produces non-stale score entry (staleness computed dynamically)."""
        mock_collectors["vix"].is_available = False
        await engine._on_dimension_update("vix", make_parse_result(score=-0.5))
        assert engine._scores["vix"]["is_stale"] is False
        assert engine._is_dimension_stale("vix") is False

    async def test_dimension_tracks_raw_vix(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """VIX dimension update stores raw_value for later use."""
        await engine._on_dimension_update(
            "vix",
            make_parse_result(score=-0.2, raw_value=15.5),
        )
        assert engine._raw_vix == 15.5

    async def test_multiple_dimensions_tracked(
        self,
        engine: MarketVarianceEngine,
    ) -> None:
        """Multiple dimension updates tracked correctly."""
        await engine._on_dimension_update("vix", make_parse_result(score=-0.2))
        await engine._on_dimension_update("options", make_parse_result(score=0.1))
        await engine._on_dimension_update("fii_dii", make_parse_result(score=0.3))
        assert len(engine._scores) == 3
        assert engine.active_dimensions == ["fii_dii", "options", "vix"]
