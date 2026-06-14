"""Unit tests for GlobalMarketsCollector.

All yfinance calls are mocked via _compute_change_pct patching.
No live Yahoo Finance API required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from variance.collectors.global_markets_collector import (
    GLOBAL_TICKERS,
    GlobalMarketsCollector,
)


@pytest.fixture
def collector() -> GlobalMarketsCollector:
    return GlobalMarketsCollector()


def _all_zeros() -> dict[str, float | None]:
    return {t: 0.0 for t in GLOBAL_TICKERS}


class TestFetch:
    @pytest.mark.asyncio
    @patch("variance.collectors.global_markets_collector._compute_change_pct")
    async def test_fetch_returns_all_tickers(self, mock_compute, collector):
        mock_compute.return_value = 0.0

        result = await collector.fetch()

        assert len(result) == len(GLOBAL_TICKERS)
        for ticker in GLOBAL_TICKERS:
            assert ticker in result


class TestParse:
    def test_parse_all_neutral(self, collector):
        result = collector.parse(_all_zeros())
        assert result["raw_value"] == pytest.approx(0.0, abs=0.001)
        assert result["direction"] == 0

    def test_parse_bullish_all_positive(self, collector):
        raw = {t: 1.0 for t in GLOBAL_TICKERS}
        result = collector.parse(raw)
        assert result["direction"] == 1
        assert result["raw_value"] > 0

    def test_parse_bearish_all_negative(self, collector):
        raw = {t: -1.0 for t in GLOBAL_TICKERS}
        result = collector.parse(raw)
        assert result["direction"] == -1
        assert result["raw_value"] < 0

    def test_parse_dxy_negative_weight_reduces_score(self, collector):
        raw = _all_zeros()
        raw["ES=F"] = 1.0
        raw["DX-Y.NYB"] = 1.0
        result = collector.parse(raw)

        raw2 = _all_zeros()
        raw2["ES=F"] = 1.0
        raw2["DX-Y.NYB"] = -1.0
        result2 = collector.parse(raw2)

        assert result["raw_value"] < result2["raw_value"]

    def test_parse_dxy_negative_weight_verified(self, collector):
        raw = _all_zeros()
        raw["DX-Y.NYB"] = 1.0
        result = collector.parse(raw)
        assert result["raw_value"] < 0

    def test_parse_excludes_failed_tickers(self, collector):
        raw = _all_zeros()
        raw["ES=F"] = 1.0
        raw["^HSI"] = None
        raw["000001.SS"] = None
        result = collector.parse(raw)
        assert result["detail"]["included_count"] == len(GLOBAL_TICKERS) - 2
        assert result["raw_value"] > 0

    def test_parse_all_failed_returns_zero(self, collector):
        raw = {t: None for t in GLOBAL_TICKERS}
        result = collector.parse(raw)
        assert result["raw_value"] == pytest.approx(0.0, abs=0.001)
        assert result["detail"]["included_count"] == 0

    def test_parse_detail_has_expected_keys(self, collector):
        result = collector.parse(_all_zeros())
        detail = result["detail"]
        assert "tickers" in detail
        assert "included_count" in detail
        assert "total_tickers" in detail
        assert detail["total_tickers"] == len(GLOBAL_TICKERS)
        assert result["source"] == "yfinance"

    def test_parse_partial_tickers(self, collector):
        raw = _all_zeros()
        raw["ES=F"] = 1.0
        raw["NQ=F"] = 0.5
        raw["^N225"] = None
        raw["^HSI"] = None
        raw["000001.SS"] = None
        raw["^KS11"] = None
        raw["YM=F"] = None
        raw["DX-Y.NYB"] = None
        result = collector.parse(raw)
        assert result["detail"]["included_count"] == 2
        ticker_detail = result["detail"]["tickers"]["ES=F"]
        assert ticker_detail["included"] is True
        assert ticker_detail["change_pct"] == 1.0


class TestScore:
    def test_score_neutral(self, collector):
        parsed = collector.parse(_all_zeros())
        assert collector.score(parsed) == pytest.approx(0.0, abs=0.001)

    def test_score_clamps_above_1(self, collector):
        raw = {t: 10.0 for t in GLOBAL_TICKERS}
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        assert score <= 1.0
        assert score >= -1.0

    def test_score_clamps_below_neg1(self, collector):
        raw = {t: -10.0 for t in GLOBAL_TICKERS}
        parsed = collector.parse(raw)
        score = collector.score(parsed)
        assert score >= -1.0


class TestIntegration:
    @pytest.mark.asyncio
    @patch("variance.collectors.global_markets_collector._compute_change_pct")
    async def test_poll_returns_parse_result(self, mock_compute, collector):
        mock_compute.return_value = 0.0

        result = await collector.poll()

        assert "normalized" in result
        assert result["source"] == "yfinance"
        assert "as_of" in result
