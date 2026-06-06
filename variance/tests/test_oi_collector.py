"""Unit tests for OICollector.

All AngelOneClient calls are mocked via _angel module patching.
No live Smart API required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from variance.collectors.oi_collector import (
    OICollector,
    TRACKED_SYMBOLS,
)
from variance.schemas import ParseResult


@pytest.fixture
def collector() -> OICollector:
    return OICollector()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oi_response(symbol: str, oi: float = 100000, ltp: float = 22000.0) -> dict:
    """Simulate AngelOneClient.get_futures_oi() response."""
    return {
        "symbol": symbol,
        "open_interest": oi,
        "ltp": ltp,
        "change": 0.0,
        "source": "angel_ltp",
    }


def _empty_oi_response() -> dict:
    """Simulate empty response from get_futures_oi()."""
    return {}


# ---------------------------------------------------------------------------
# TestFetch
# ---------------------------------------------------------------------------

class TestFetch:

    @pytest.mark.asyncio
    @patch("variance.collectors.oi_collector._get_angel_client")
    async def test_fetch_calls_get_futures_oi_for_each_symbol(
        self, mock_get_angel, collector
    ):
        """fetch() should call get_futures_oi() for each tracked symbol."""
        mock_angel = MagicMock()
        mock_angel.get_futures_oi = MagicMock(side_effect=[
            _oi_response("NIFTY", 100000),
            _oi_response("BANKNIFTY", 50000),
        ])
        mock_get_angel.return_value = mock_angel

        result = await collector.fetch()

        assert mock_angel.get_futures_oi.call_count == 2
        assert mock_angel.get_futures_oi.call_args_list[0][0][0] == "NIFTY"
        assert mock_angel.get_futures_oi.call_args_list[1][0][0] == "BANKNIFTY"
        assert isinstance(result, dict)
        assert "NIFTY" in result
        assert "BANKNIFTY" in result

    @pytest.mark.asyncio
    @patch("variance.collectors.oi_collector._get_angel_client")
    async def test_fetch_handles_api_error_per_symbol(
        self, mock_get_angel, collector
    ):
        """fetch() should return empty dict for a symbol on error."""
        mock_angel = MagicMock()
        mock_angel.get_futures_oi = MagicMock(side_effect=[
            _oi_response("NIFTY", 100000),
            Exception("API failure"),
        ])
        mock_get_angel.return_value = mock_angel

        result = await collector.fetch()

        assert result["NIFTY"] == _oi_response("NIFTY", 100000)
        assert result["BANKNIFTY"] == {}


# ---------------------------------------------------------------------------
# TestParse
# ---------------------------------------------------------------------------

class TestParse:

    def test_parse_extracts_total_oi(self, collector):
        raw = {
            "NIFTY": _oi_response("NIFTY", 100000),
            "BANKNIFTY": _oi_response("BANKNIFTY", 50000),
        }
        result = collector.parse(raw)
        assert result["raw_value"] == pytest.approx(150000.0)
        assert result["detail"]["total_oi"] == pytest.approx(150000.0)
        assert result["detail"]["symbols_with_data"] == 2
        assert result["detail"]["tracked_count"] == 2

    def test_parse_extracts_symbol_level_oi(self, collector):
        raw = {
            "NIFTY": _oi_response("NIFTY", 200000, 22500.0),
            "BANKNIFTY": _oi_response("BANKNIFTY", 80000, 48000.0),
        }
        result = collector.parse(raw)
        symbols = result["detail"]["symbols"]
        assert symbols["NIFTY"]["open_interest"] == pytest.approx(200000.0)
        assert symbols["NIFTY"]["ltp"] == pytest.approx(22500.0)
        assert symbols["NIFTY"]["has_data"] is True
        assert symbols["BANKNIFTY"]["open_interest"] == pytest.approx(80000.0)
        assert symbols["BANKNIFTY"]["ltp"] == pytest.approx(48000.0)
        assert symbols["BANKNIFTY"]["has_data"] is True

    def test_parse_partial_data(self, collector):
        """One symbol has data, other returns empty dict."""
        raw = {
            "NIFTY": _oi_response("NIFTY", 100000),
            "BANKNIFTY": _empty_oi_response(),
        }
        result = collector.parse(raw)
        assert result["raw_value"] == pytest.approx(100000.0)
        assert result["detail"]["symbols_with_data"] == 1
        assert result["detail"]["symbols"]["NIFTY"]["has_data"] is True
        assert result["detail"]["symbols"]["BANKNIFTY"]["has_data"] is False

    def test_parse_empty_data_raises(self, collector):
        raw = {"NIFTY": {}, "BANKNIFTY": {}}
        with pytest.raises(ValueError, match="No OI data received"):
            collector.parse(raw)

    def test_parse_non_dict_raises(self, collector):
        with pytest.raises(ValueError, match="Unexpected OI data type"):
            collector.parse("not a dict")

    def test_parse_detail_keys(self, collector):
        raw = {
            "NIFTY": _oi_response("NIFTY", 100000),
            "BANKNIFTY": _oi_response("BANKNIFTY", 50000),
        }
        result = collector.parse(raw)
        assert "symbols" in result["detail"]
        assert "total_oi" in result["detail"]
        assert "symbols_with_data" in result["detail"]
        assert "tracked_count" in result["detail"]
        assert "NIFTY" in result["detail"]["symbols"]
        assert "BANKNIFTY" in result["detail"]["symbols"]

    def test_parse_source_angel(self, collector):
        raw = {
            "NIFTY": _oi_response("NIFTY", 100000),
            "BANKNIFTY": _oi_response("BANKNIFTY", 50000),
        }
        result = collector.parse(raw)
        assert result["source"] == "angel"
        assert "as_of" in result


# ---------------------------------------------------------------------------
# TestScore
# ---------------------------------------------------------------------------

class TestScore:

    def test_score_zero_change(self, collector):
        parsed: ParseResult = {
            "raw_value": 0.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": 0.0},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed) == pytest.approx(0.0)

    def test_score_three_pct_buildup(self, collector):
        """3% OI buildup -> 0.3."""
        parsed: ParseResult = {
            "raw_value": 103000.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": 3.0},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed) == pytest.approx(0.3)

    def test_score_three_pct_unwind(self, collector):
        """-3% OI unwind -> -0.3."""
        parsed: ParseResult = {
            "raw_value": 97000.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": -3.0},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed) == pytest.approx(-0.3)

    def test_score_beyond_three_pct_clamps(self, collector):
        """OI change beyond 3% stays clamped at 0.3/-0.3."""
        parsed_buildup: ParseResult = {
            "raw_value": 110000.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": 10.0},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        parsed_unwind: ParseResult = {
            "raw_value": 90000.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": -10.0},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed_buildup) == pytest.approx(0.3)
        assert collector.score(parsed_unwind) == pytest.approx(-0.3)

    @pytest.mark.parametrize("change_pct,expected", [
        (0.0, 0.0),
        (1.0, 0.1),
        (-1.0, -0.1),
        (2.0, 0.2),
        (-2.0, -0.2),
    ])
    def test_score_linear_interpolation(self, collector, change_pct, expected):
        """Below 3%, score = change_pct / 10.0."""
        parsed: ParseResult = {
            "raw_value": 0.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {"oi_change_pct": change_pct},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed) == pytest.approx(expected)

    def test_score_no_change_pct_defaults_zero(self, collector):
        """When detail has no oi_change_pct key, default to 0.0."""
        parsed: ParseResult = {
            "raw_value": 0.0,
            "normalized": 0.0,
            "direction": 0,
            "magnitude": 0.0,
            "detail": {},
            "source": "angel",
            "as_of": "2026-06-04T00:00:00Z",
        }
        assert collector.score(parsed) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestPollWithBaseline
# ---------------------------------------------------------------------------

class TestPollWithBaseline:

    @pytest.mark.asyncio
    @patch("variance.collectors.oi_collector._get_angel_client")
    async def test_first_poll_returns_zero_change(self, mock_get_angel, collector):
        """First poll without baseline should return 0.0% change."""
        mock_angel = MagicMock()
        mock_angel.get_futures_oi = MagicMock(side_effect=[
            _oi_response("NIFTY", 100000),
            _oi_response("BANKNIFTY", 50000),
        ])
        mock_get_angel.return_value = mock_angel

        mock_redis = AsyncMock()
        mock_redis.get_mve = AsyncMock(return_value=None)

        result = await collector.poll_with_baseline(mock_redis)

        assert result["detail"]["oi_change_pct"] == pytest.approx(0.0)
        assert result["normalized"] == pytest.approx(0.0)
        assert result["direction"] == 0
        assert result["magnitude"] == pytest.approx(0.0)
        # Should have stored baseline
        assert mock_redis.set_mve.call_count >= 1

    @pytest.mark.asyncio
    @patch("variance.collectors.oi_collector._get_angel_client")
    async def test_second_poll_computes_change(self, mock_get_angel, collector):
        """Second poll with existing baseline should compute % change."""
        mock_angel = MagicMock()
        # First poll values
        mock_angel.get_futures_oi = MagicMock(side_effect=[
            _oi_response("NIFTY", 110000),
            _oi_response("BANKNIFTY", 55000),
        ])
        mock_get_angel.return_value = mock_angel

        mock_redis = AsyncMock()
        # Simulate previous baseline
        mock_redis.get_mve = AsyncMock(side_effect=[
            {"total_oi": 150000.0, "as_of": "2026-06-04T00:00:00Z"},  # baseline:total
            None,  # baseline:NIFTY (no per-symbol baseline)
            None,  # baseline:BANKNIFTY
        ])

        result = await collector.poll_with_baseline(mock_redis)

        # New total = 110000 + 55000 = 165000, previous = 150000
        # Change = (165000 - 150000) / 150000 * 100 = 10.0%
        expected_change = 10.0
        assert result["detail"]["oi_change_pct"] == pytest.approx(expected_change)
        assert result["detail"]["total_oi"] == pytest.approx(165000.0)
        # score: 10% -> clamped at 0.3
        assert result["normalized"] == pytest.approx(0.3)
        assert result["direction"] == 1
        assert result["magnitude"] == pytest.approx(0.3)

    @pytest.mark.asyncio
    @patch("variance.collectors.oi_collector._get_angel_client")
    async def test_no_redis_returns_zero_change(self, mock_get_angel, collector):
        """poll_with_baseline with redis=None should return 0.0% change."""
        mock_angel = MagicMock()
        mock_angel.get_futures_oi = MagicMock(side_effect=[
            _oi_response("NIFTY", 100000),
            _oi_response("BANKNIFTY", 50000),
        ])
        mock_get_angel.return_value = mock_angel

        result = await collector.poll_with_baseline(None)

        assert result["detail"]["oi_change_pct"] == pytest.approx(0.0)
        # Should still populate score fields
        assert result["normalized"] == pytest.approx(0.0)
        assert result["direction"] == 0
        assert result["magnitude"] == pytest.approx(0.0)
