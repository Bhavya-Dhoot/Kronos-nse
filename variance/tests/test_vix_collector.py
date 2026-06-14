"""Unit tests for VIXCollector.

All NseIndiaApi calls are mocked via _nse module patching.
No live NSE API required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from variance.collectors.vix_collector import VIXCollector


@pytest.fixture
def collector() -> VIXCollector:
    return VIXCollector()


def _mock_indices(vix_value: float) -> list[dict]:
    return [
        {"key": "NIFTY", "value": 23456.0},
        {"key": "INDIAVIX", "value": vix_value},
        {"key": "BANKNIFTY", "value": 49876.0},
    ]


class TestFetch:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.vix_collector._fetch_all_indices", new_callable=AsyncMock
    )
    async def test_fetch_calls_nse_api(self, mock_fetch, collector):
        mock_fetch.return_value = _mock_indices(15.0)
        result = await collector.fetch()
        mock_fetch.assert_awaited_once()
        assert isinstance(result, list)
        assert len(result) == 3


class TestParse:
    def test_parse_extracts_vix_value(self, collector):
        raw = _mock_indices(15.2)
        result = collector.parse(raw)
        assert result["raw_value"] == 15.2
        assert result["source"] == "nse"
        assert "as_of" in result
        assert "vix_raw" in result["detail"]

    def test_parse_raises_on_missing_vix(self, collector):
        raw = [{"key": "NIFTY", "value": 100.0}]
        with pytest.raises(ValueError, match="INDIAVIX not found"):
            collector.parse(raw)

    def test_parse_empty_list_raises(self, collector):
        with pytest.raises(ValueError, match="INDIAVIX not found"):
            collector.parse([])


class TestScore:
    @pytest.mark.parametrize(
        "vix,expected",
        [
            (30.0, -1.0),
            (20.0, -0.3),
            (15.0, 0.0),
            (10.0, 0.8),
        ],
    )
    def test_anchor_points(self, collector, vix, expected):
        parsed = collector.parse(_mock_indices(vix))
        score = collector.score(parsed)
        assert score == pytest.approx(expected, abs=0.01)

    @pytest.mark.parametrize(
        "vix,expected",
        [
            (5.0, 0.8),
            (40.0, -1.0),
        ],
    )
    def test_clamping(self, collector, vix, expected):
        parsed = collector.parse(_mock_indices(vix))
        score = collector.score(parsed)
        assert score == pytest.approx(expected, abs=0.01)

    def test_interpolation(self, collector):
        parsed = collector.parse(_mock_indices(12.5))
        score = collector.score(parsed)
        assert score == pytest.approx(0.4, abs=0.01)

        parsed25 = collector.parse(_mock_indices(25.0))
        score25 = collector.score(parsed25)
        assert score25 == pytest.approx(-0.65, abs=0.01)

    def test_direction_from_vix(self, collector):
        parsed_high = collector.parse(_mock_indices(25.0))
        assert parsed_high["direction"] == -1

        parsed_low = collector.parse(_mock_indices(10.0))
        assert parsed_low["direction"] == 1


class TestIntegration:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.vix_collector._fetch_all_indices", new_callable=AsyncMock
    )
    async def test_poll_returns_parse_result_with_score(self, mock_fetch, collector):
        mock_fetch.return_value = _mock_indices(20.0)
        result = await collector.poll()
        assert result["normalized"] == pytest.approx(-0.3, abs=0.01)
        assert result["raw_value"] == 20.0
        assert result["source"] == "nse"
        assert "as_of" in result
