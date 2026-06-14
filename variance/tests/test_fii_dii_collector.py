"""Unit tests for FIIDIICollector.

All NseIndiaApi calls are mocked via _nse module patching.
No live NSE API required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from variance.collectors.fii_dii_collector import FIIDIICollector


@pytest.fixture
def collector() -> FIIDIICollector:
    return FIIDIICollector()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _simple_fii_dii(fii_net: float = 1000.0, dii_net: float = -500.0) -> dict:
    """Return a simple flat FII/DII dict."""
    return {"fii_net": fii_net, "dii_net": dii_net}


def _nested_fii_dii(fii_net: float = 800.0, dii_net: float = -300.0) -> dict:
    """Return a nested FII/DII dict."""
    return {
        "fii": {"net": fii_net},
        "dii": {"net": dii_net},
        "date": "2026-06-04",
    }


# ---------------------------------------------------------------------------
# TestFetch
# ---------------------------------------------------------------------------


class TestFetch:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.fii_dii_collector._fetch_fii_dii_data",
        new_callable=AsyncMock,
    )
    async def test_fetch_calls_fii_dii_api(self, mock_fetch, collector):
        mock_fetch.return_value = _simple_fii_dii()
        result = await collector.fetch()
        mock_fetch.assert_awaited_once()
        assert isinstance(result, dict)
        assert "fii_net" in result


# ---------------------------------------------------------------------------
# TestParse
# ---------------------------------------------------------------------------


class TestParse:
    def test_parse_simple_dict(self, collector):
        raw = _simple_fii_dii(fii_net=2000.0, dii_net=-800.0)
        result = collector.parse(raw)
        expected_combined = 2000.0 * 0.7 + (-800.0) * 0.3
        assert result["raw_value"] == pytest.approx(expected_combined)
        assert result["source"] == "nse"
        assert result["detail"]["fii_net"] == 2000.0
        assert result["detail"]["dii_net"] == -800.0

    def test_parse_nested_dict(self, collector):
        raw = _nested_fii_dii(fii_net=1500.0, dii_net=-600.0)
        result = collector.parse(raw)
        expected_combined = 1500.0 * 0.7 + (-600.0) * 0.3
        assert result["raw_value"] == pytest.approx(expected_combined)

    def test_parse_missing_data_returns_neutral(self, collector):
        result = collector.parse({"date": "2026-06-04", "other": 123})
        assert result["raw_value"] == 0.0
        assert result["normalized"] == 0.0
        assert result["direction"] == 0
        assert result["detail"]["available"] is False

    def test_parse_non_dict_raises(self, collector):
        with pytest.raises(ValueError, match="Expected dict"):
            collector.parse("not a dict")

    def test_parse_empty_dict_returns_neutral(self, collector):
        result = collector.parse({})
        assert result["raw_value"] == 0.0
        assert result["normalized"] == 0.0
        assert result["direction"] == 0
        assert result["detail"]["available"] is False

    def test_direction_positive(self, collector):
        raw = _simple_fii_dii(fii_net=5000.0, dii_net=1000.0)
        result = collector.parse(raw)
        assert result["direction"] == 1

    def test_direction_negative(self, collector):
        raw = _simple_fii_dii(fii_net=-5000.0, dii_net=-1000.0)
        result = collector.parse(raw)
        assert result["direction"] == -1

    def test_direction_zero(self, collector):
        raw = _simple_fii_dii(fii_net=0.0, dii_net=0.0)
        result = collector.parse(raw)
        assert result["direction"] == 0

    def test_magnitude_scaling(self, collector):
        # combined = 8000*0.7 + 2000*0.3 = 6200 -> min(1.0, 6200/4000) = 1.0
        raw = _simple_fii_dii(fii_net=8000.0, dii_net=2000.0)
        result = collector.parse(raw)
        assert result["magnitude"] == 1.0

    def test_magnitude_partial(self, collector):
        # combined = 1000*0.7 + 500*0.3 = 850 -> 850/4000 = 0.2125
        raw = _simple_fii_dii(fii_net=1000.0, dii_net=500.0)
        result = collector.parse(raw)
        assert result["magnitude"] == pytest.approx(850.0 / 4000.0)

    @pytest.mark.parametrize(
        "fii_net,dii_net",
        [
            (100.0, None),
            (None, 100.0),
            (None, None),
        ],
    )
    def test_parse_none_values_return_neutral(self, collector, fii_net, dii_net):
        raw = {"fii_net": fii_net, "dii_net": dii_net}
        result = collector.parse(raw)
        assert result["raw_value"] == 0.0
        assert result["normalized"] == 0.0
        assert result["detail"]["available"] is False


# ---------------------------------------------------------------------------
# TestScore
# ---------------------------------------------------------------------------


class TestScore:
    @pytest.mark.parametrize(
        "fii_net,dii_net,expected",
        [
            # Neutral: FII +4000, DII 0 -> combined=2800 -> 2800/4000=0.7
            (4000.0, 0.0, 0.7),
            # Mixed: FII -3000, DII 1000 -> combined=-1800 -> -1800/4000=-0.45
            (-3000.0, 1000.0, -0.45),
            # Both positive: 2000, 1000 -> combined=1700 -> 1700/4000=0.425
            (2000.0, 1000.0, 0.425),
            # Both negative: -5000, -2000 -> combined=-4100 -> -4100/4000=-1.025 -> clamp -1.0
            (-5000.0, -2000.0, -1.0),
            # Large positive: 6000, 3000 -> combined=5100 -> 5100/4000=1.275 -> clamp 1.0
            (6000.0, 3000.0, 1.0),
            # Zero: 0, 0 -> 0
            (0.0, 0.0, 0.0),
            # Extreme positive: 10000, 5000 -> 8500/4000=2.125 -> clamp 1.0
            (10000.0, 5000.0, 1.0),
            # Extreme negative: -8000, -5000 -> -7100/4000=-1.775 -> clamp -1.0
            (-8000.0, -5000.0, -1.0),
        ],
    )
    def test_score_parametrized(self, collector, fii_net, dii_net, expected):
        raw = _simple_fii_dii(fii_net=fii_net, dii_net=dii_net)
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        assert score == pytest.approx(expected, abs=0.001)

    def test_score_with_nested(self, collector):
        raw = _nested_fii_dii(fii_net=4000.0, dii_net=0.0)
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        # combined = 4000*0.7 = 2800 -> 2800/4000 = 0.7
        assert score == pytest.approx(0.7, abs=0.001)


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.fii_dii_collector._fetch_fii_dii_data",
        new_callable=AsyncMock,
    )
    async def test_poll_returns_parse_result_with_score(self, mock_fetch, collector):
        mock_fetch.return_value = _simple_fii_dii(fii_net=2000.0, dii_net=-500.0)
        result = await collector.poll()
        expected_combined = 2000.0 * 0.7 + (-500.0) * 0.3
        expected_score = expected_combined / 4000.0
        assert result["normalized"] == pytest.approx(expected_score, abs=0.001)
        assert result["raw_value"] == pytest.approx(expected_combined)
        assert result["source"] == "nse"
        assert "as_of" in result
        assert result["detail"]["fii_net"] == 2000.0
        assert result["detail"]["dii_net"] == -500.0
