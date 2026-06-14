"""Unit tests for MacroCollector.

All yfinance calls are mocked via _compute_change_pct patching.
No live Yahoo Finance API required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from variance.collectors.macro_collector import MACRO_TICKERS, MacroCollector


@pytest.fixture
def collector() -> MacroCollector:
    return MacroCollector()


def _all_zeros() -> dict[str, float | None]:
    return {t: 0.0 for t in MACRO_TICKERS}


class TestFetch:
    @pytest.mark.asyncio
    @patch("variance.collectors.macro_collector._compute_change_pct")
    async def test_fetch_returns_all_tickers(self, mock_compute, collector):
        mock_compute.return_value = 0.0

        result = await collector.fetch()

        assert len(result) == len(MACRO_TICKERS)
        for ticker in MACRO_TICKERS:
            assert ticker in result


class TestParse:
    def test_parse_all_neutral(self, collector):
        result = collector.parse(_all_zeros())
        assert result["raw_value"] == pytest.approx(0.0, abs=0.001)
        assert result["direction"] == 0

    def test_parse_all_rising_inverts_to_negative(self, collector):
        raw = {t: 1.0 for t in MACRO_TICKERS}
        result = collector.parse(raw)
        assert result["direction"] == -1
        assert result["raw_value"] < 0
        assert result["detail"]["raw_composite"] > 0

    def test_parse_all_falling_inverts_to_positive(self, collector):
        raw = {t: -1.0 for t in MACRO_TICKERS}
        result = collector.parse(raw)
        assert result["direction"] == 1
        assert result["raw_value"] > 0
        assert result["detail"]["raw_composite"] < 0

    def test_parse_excludes_failed_tickers(self, collector):
        raw = _all_zeros()
        raw["USDINR=X"] = 0.5
        raw["CL=F"] = None
        result = collector.parse(raw)
        assert result["detail"]["included_count"] == 3
        assert result["detail"]["tickers"]["CL=F"]["included"] is False

    def test_parse_all_failed_returns_zero(self, collector):
        raw = {t: None for t in MACRO_TICKERS}
        result = collector.parse(raw)
        assert result["raw_value"] == pytest.approx(0.0, abs=0.001)
        assert result["detail"]["included_count"] == 0

    def test_parse_detail_has_expected_keys(self, collector):
        result = collector.parse(_all_zeros())
        detail = result["detail"]
        assert "tickers" in detail
        assert "raw_composite" in detail
        assert "included_count" in detail
        assert "total_tickers" in detail
        assert detail["total_tickers"] == len(MACRO_TICKERS)
        assert result["source"] == "yfinance"

    def test_parse_weighted_values(self, collector):
        raw = _all_zeros()
        raw["USDINR=X"] = 1.0
        raw["CL=F"] = 2.0
        raw["GC=F"] = 0.0
        raw["^TNX"] = 0.0
        result = collector.parse(raw)
        expected_raw = (1.0 * 0.35 + 2.0 * 0.30) / (0.35 + 0.30 + 0.15 + 0.20)
        expected = -expected_raw
        assert result["raw_value"] == pytest.approx(round(expected, 4), abs=0.01)


class TestScore:
    def test_score_neutral(self, collector):
        parsed = collector.parse(_all_zeros())
        assert collector.score(parsed) == pytest.approx(0.0, abs=0.001)

    def test_score_clamps_above_1(self, collector):
        raw = {t: 10.0 for t in MACRO_TICKERS}
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        assert score >= -1.0
        assert score <= 1.0

    def test_score_clamps_below_neg1(self, collector):
        raw = {t: -10.0 for t in MACRO_TICKERS}
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        assert score >= -1.0
        assert score <= 1.0


class TestIntegration:
    @pytest.mark.asyncio
    @patch("variance.collectors.macro_collector._compute_change_pct")
    async def test_poll_returns_parse_result(self, mock_compute, collector):
        mock_compute.return_value = 0.0

        result = await collector.poll()

        assert "normalized" in result
        assert result["source"] == "yfinance"
        assert "as_of" in result
