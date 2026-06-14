"""Integration tests for variance API endpoints (REST + WS)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


def _sample_mvs_dict() -> dict:
    """Return a realistic MVS dict matching MarketVarianceScore.to_dict() output."""
    return {
        "composite": 0.35,
        "market_state": "bull_run",
        "vix_value": 14.2,
        "created_at": datetime.now(UTC).isoformat(),
        "dimensions": [
            {
                "name": "vix",
                "score": -0.15,
                "weight": 0.2,
                "is_stale": False,
                "detail": {},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "options",
                "score": 0.42,
                "weight": 0.2,
                "is_stale": False,
                "detail": {"pcr": 1.2},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "fii_dii",
                "score": 0.55,
                "weight": 0.175,
                "is_stale": False,
                "detail": {},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "oi",
                "score": -0.22,
                "weight": 0.075,
                "is_stale": True,
                "detail": {},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "gift_nifty",
                "score": 0.18,
                "weight": 0.15,
                "is_stale": False,
                "detail": {"gap_pct": 0.35},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "global_markets",
                "score": 0.30,
                "weight": 0.15,
                "is_stale": False,
                "detail": {},
                "collected_at": datetime.now(UTC).isoformat(),
            },
            {
                "name": "macro",
                "score": -0.10,
                "weight": 0.05,
                "is_stale": False,
                "detail": {},
                "collected_at": datetime.now(UTC).isoformat(),
            },
        ],
        "temperature_adjustment": 0.0,
        "directional_bias": 0.35,
        "band_width_multiplier": 1.0,
        "signal_threshold": 0.005,
        "confidence_override": None,
    }


def _score_entries() -> dict:
    """Return mock _scores entries as present on MarketVarianceEngine."""
    now = datetime.now(UTC).isoformat()
    return {
        "vix": {
            "score": -0.15,
            "weight": 0.2,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
        "options": {
            "score": 0.42,
            "weight": 0.2,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
        "fii_dii": {
            "score": 0.55,
            "weight": 0.175,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
        "oi": {
            "score": -0.22,
            "weight": 0.075,
            "is_stale": True,
            "first_poll": True,
            "collected_at": now,
        },
        "gift_nifty": {
            "score": 0.18,
            "weight": 0.15,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
        "global_markets": {
            "score": 0.30,
            "weight": 0.15,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
        "macro": {
            "score": -0.10,
            "weight": 0.05,
            "is_stale": False,
            "first_poll": True,
            "collected_at": now,
        },
    }


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient with mocked MVE engine and Redis."""
    app = create_app()

    # ── Mock MarketVarianceEngine ────────────────────────────────────────
    mve = MagicMock()
    mve.is_ready = True
    mve.is_degraded = False
    mve.last_mvs = _sample_mvs_dict()
    mve._scores = (
        _score_entries()
    )  # dict, not PropertyMock — avoids MagicMock class pollution
    mve._collectors = {}  # avoid auto-MagicMock for .get() returning mock objects
    mve.active_dimensions = list(_score_entries().keys())
    mve.health_status = {
        "ready": True,
        "degraded": False,
        "active_dimensions": 7,
        "collectors": {name: True for name in _score_entries()},
    }

    # ── Mock RedisCache ──────────────────────────────────────────────────
    mve_redis = MagicMock()
    mve_redis.lrange = AsyncMock(return_value=[])
    mve_redis.pubsub = MagicMock()
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.get_message = AsyncMock(return_value=None)
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    mve_redis.pubsub.return_value = pubsub

    app.state.mve = mve
    app.state.mve_redis = mve_redis
    app.state.operating_mode = "VISUAL"

    return TestClient(app)


class TestVarianceScore:
    """GET /api/v1/variance/score"""

    def test_score_returns_200_with_mvs(self, client: TestClient):
        resp = client.get("/api/v1/variance/score")
        assert resp.status_code == 200
        body = resp.json()
        assert body["composite"] == 0.35
        assert body["market_state"] == "bull_run"
        assert body["vix_value"] == 14.2
        assert "dimensions" in body
        assert len(body["dimensions"]) == 7
        assert body["temperature_adjustment"] == 0.0
        assert body["directional_bias"] == 0.35
        assert body["signal_threshold"] == 0.005

    def test_score_returns_204_when_not_ready(self, client: TestClient):
        client.app.state.mve.is_ready = False
        client.app.state.mve.last_mvs = None
        resp = client.get("/api/v1/variance/score")
        assert resp.status_code == 204

    def test_score_returns_204_when_mve_none(self, client: TestClient):
        client.app.state.mve = None
        resp = client.get("/api/v1/variance/score")
        assert resp.status_code == 204

    def test_score_returns_204_when_last_mvs_none(self, client: TestClient):
        client.app.state.mve.last_mvs = None
        resp = client.get("/api/v1/variance/score")
        assert resp.status_code == 204


class TestVarianceDimensions:
    """GET /api/v1/variance/dimensions/{name}"""

    def test_dimension_returns_detail(self, client: TestClient):
        resp = client.get("/api/v1/variance/dimensions/vix")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "vix"
        assert body["score"] == -0.15
        assert "weight" in body
        assert "is_stale" in body
        assert "collected_at" in body

    def test_dimension_returns_404_for_unknown(self, client: TestClient):
        resp = client.get("/api/v1/variance/dimensions/invalid_dim")
        assert resp.status_code == 404

    def test_dimension_returns_404_when_mve_none(self, client: TestClient):
        client.app.state.mve = None
        resp = client.get("/api/v1/variance/dimensions/vix")
        assert resp.status_code == 404


class TestVarianceHistory:
    """GET /api/v1/variance/history"""

    def test_history_returns_empty_list(self, client: TestClient):
        resp = client.get("/api/v1/variance/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert body["total"] == 0

    def test_history_returns_entries_when_redis_has_data(self, client: TestClient):
        import json

        entry = _sample_mvs_dict()
        client.app.state.mve_redis.lrange = AsyncMock(return_value=[json.dumps(entry)])
        resp = client.get("/api/v1/variance/history")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["entries"]) >= 1
        assert body["total"] >= 1
        assert "composite" in body["entries"][0]

    def test_history_returns_empty_when_redis_none(self, client: TestClient):
        client.app.state.mve_redis = None
        resp = client.get("/api/v1/variance/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert body["total"] == 0


class TestVarianceWebSocket:
    """WS /ws/variance

    NOTE: These tests work around a Starlette/httpx limitation where
    ``asyncio.create_task()`` inside a FastAPI WebSocket handler fails when
    called through the sync httpx TestClient transport. The workaround:
      - ``start_redis_listener`` is patched to a no-op (avoids ``create_task``)
      - For the MVS update test, the message is injected via
        ``ws_manager.broadcast()`` directly instead of relying on the Redis
        pub/sub listener task.
    """

    def test_ws_connects_and_receives_ping(self, client: TestClient):
        from unittest.mock import patch

        from api.ws_manager import ws_manager

        with patch.object(ws_manager, "start_redis_listener"):
            with client.websocket_connect("/ws/variance") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "ping"

    def test_ws_receives_mvs_update_on_redis_message(self, client: TestClient):
        from unittest.mock import patch

        from api.ws_manager import ws_manager

        entry = _sample_mvs_dict()

        with patch.object(ws_manager, "start_redis_listener"):
            with client.websocket_connect("/ws/variance") as ws:
                # First message is the ping from ws_manager.connect()
                ping = ws.receive_json()
                assert ping["type"] == "ping"

                # Inject the MVS update onto the TestClient's event loop
                # via ws.portal.call (the underlying anyio portal).
                ws.portal.call(
                    ws_manager.broadcast,
                    "variance:all",
                    {"type": "mvs_update", "payload": entry},
                )

                # Second message should be the transformed MVS update
                update = ws.receive_json()
                assert update["type"] == "mvs_update"
                assert "payload" in update
                assert update["payload"]["composite"] == 0.35
                assert update["payload"]["market_state"] == "bull_run"

    def test_ws_errors_when_mve_not_available(self, client: TestClient):
        client.app.state.mve_redis = None
        with client.websocket_connect("/ws/variance") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "MVE not available" in msg["detail"]
