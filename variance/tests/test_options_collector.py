"""Unit tests for OptionsCollector.

All NseIndiaApi calls are mocked. No live NSE API required.
Uses realistic option chain data shapes matching NseIndiaApi output.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from variance.collectors.options_collector import OptionsCollector


@pytest.fixture
def collector() -> OptionsCollector:
    return OptionsCollector()


def _make_option(
    strike: float,
    ce_oi: float,
    pe_oi: float,
    ce_iv: float | None = 0.12,
    pe_iv: float | None = 0.14,
) -> dict:
    entry: dict = {"strikePrice": strike}
    ce: dict = {"openInterest": ce_oi}
    pe: dict = {"openInterest": pe_oi}
    if ce_iv is not None:
        ce["impliedVolatility"] = ce_iv
    if pe_iv is not None:
        pe["impliedVolatility"] = pe_iv
    entry["CE"] = ce
    entry["PE"] = pe
    return entry


def _mock_option_chain(
    underlying: float = 18200.0,
    strikes: list[tuple[float, float, float, float | None, float | None]] | None = None,
) -> dict:
    if strikes is None:
        strikes = [
            (18000, 500000, 300000, 0.15, 0.18),
            (18100, 400000, 450000, 0.14, 0.17),
            (18200, 300000, 600000, 0.12, 0.15),
            (18300, 600000, 350000, 0.13, 0.16),
            (18400, 350000, 200000, 0.16, 0.19),
            (18500, 200000, 150000, 0.17, 0.20),
        ]
    data = [
        _make_option(s, ce_oi, pe_oi, ce_iv, pe_iv)
        for s, ce_oi, pe_oi, ce_iv, pe_iv in strikes
    ]
    return {"records": {"data": data, "underlyingValue": underlying}}


class TestFetch:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.options_collector._fetch_option_chain",
        new_callable=AsyncMock,
    )
    async def test_fetch_calls_nse_api(self, mock_fetch, collector):
        mock_fetch.return_value = _mock_option_chain()
        result = await collector.fetch()
        mock_fetch.assert_awaited_once_with("NIFTY")
        assert "records" in result


class TestParse:
    def test_parse_computes_pcr(self, collector):
        raw = _mock_option_chain()
        result = collector.parse(raw)
        assert result["raw_value"] == pytest.approx(0.8723, abs=0.01)

    def test_parse_computes_max_pain(self, collector):
        raw = _mock_option_chain()
        result = collector.parse(raw)
        detail = result["detail"]
        # Strike 18300 has CE 600k + PE 350k = 950k total (highest)
        assert detail["max_pain"] == 18300.0

    def test_parse_computes_atm_iv(self, collector):
        raw = _mock_option_chain(underlying=18200.0)
        result = collector.parse(raw)
        detail = result["detail"]
        assert detail["iv_ce"] == pytest.approx(12.0, abs=0.1)
        assert detail["iv_pe"] == pytest.approx(15.0, abs=0.1)

    def test_parse_computes_oi_concentration(self, collector):
        raw = _mock_option_chain()
        result = collector.parse(raw)
        detail = result["detail"]
        assert detail["oi_concentration"] == pytest.approx(0.9205, abs=0.01)

    def test_parse_spot_vs_max_pain(self, collector):
        raw = _mock_option_chain(underlying=18500.0)
        result = collector.parse(raw)
        detail = result["detail"]
        # Max pain = 18300 (highest total OI). Spot 18500.
        # spot_vs_max_pain_pct = (18500 - 18300) / 18300 * 100 ≈ 1.09%
        assert detail["spot_vs_max_pain_pct"] == pytest.approx(1.09, abs=0.01)

    def test_parse_raises_on_empty_data(self, collector):
        raw = {"records": {"data": [], "underlyingValue": 18200.0}}
        with pytest.raises(ValueError, match="No option chain data"):
            collector.parse(raw)

    def test_parse_detail_has_all_expected_keys(self, collector):
        raw = _mock_option_chain()
        result = collector.parse(raw)
        detail = result["detail"]
        expected_keys = {
            "pcr",
            "max_pain",
            "underlying_value",
            "iv_ce",
            "iv_pe",
            "oi_concentration",
            "spot_vs_max_pain_pct",
            "strike_count",
        }
        assert expected_keys.issubset(detail.keys())
        assert detail["strike_count"] == 6

    def test_parse_direction_from_pcr(self, collector):
        raw_bullish = _mock_option_chain(underlying=18200.0)
        result = collector.parse(raw_bullish)
        assert result["direction"] == -1

        bearish_strikes = [
            (18000, 300000, 500000, 0.15, 0.18),
            (18200, 200000, 800000, 0.12, 0.15),
            (18400, 250000, 400000, 0.16, 0.19),
        ]
        raw_bearish = _mock_option_chain(underlying=18200.0, strikes=bearish_strikes)
        result_bearish = collector.parse(raw_bearish)
        assert result_bearish["direction"] == 1


class TestScore:
    def test_pcr_1p0_is_neutral_with_pin(self, collector):
        strikes = [
            (18000, 100, 100, 0.15, 0.18),
            (18200, 500, 500, 0.12, 0.15),
            (18400, 100, 100, 0.16, 0.19),
        ]
        raw = _mock_option_chain(underlying=18200.0, strikes=strikes)
        result = collector.parse(raw)
        score = collector.score(result)
        # PCR = 1.0 → 0.0 base, max pain = 18200, spot = 18200, within 0.5% → -0.15
        assert score == pytest.approx(-0.15, abs=0.01)

    def test_max_pain_proximity_adjusts_bearish(self, collector):
        strikes = [
            (18000, 100, 50, 0.15, 0.18),
            (18200, 100, 100, 0.12, 0.15),
            (18400, 50, 100, 0.16, 0.19),
        ]
        raw = _mock_option_chain(underlying=18200.0, strikes=strikes)
        result = collector.parse(raw)
        score = collector.score(result)
        assert score == pytest.approx(-0.15, abs=0.01)

    def test_spot_above_max_pain_adjusts_bullish(self, collector):
        strikes = [
            (18000, 500, 500, 0.15, 0.18),
            (18200, 100, 100, 0.12, 0.15),
            (18400, 100, 100, 0.16, 0.19),
        ]
        raw = _mock_option_chain(underlying=18500.0, strikes=strikes)
        result = collector.parse(raw)
        score = collector.score(result)
        assert score == pytest.approx(0.15, abs=0.01)

    def test_low_pcr_is_bearish(self, collector):
        low_pcr_strikes = [
            (18000, 100, 12, 0.15, 0.18),
            (18200, 100, 2, 0.12, 0.15),
        ]
        raw = _mock_option_chain(underlying=18200.0, strikes=low_pcr_strikes)
        result = collector.parse(raw)
        score = collector.score(result)
        assert score == pytest.approx(-0.6, abs=0.01)


class TestIntegration:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.options_collector._fetch_option_chain",
        new_callable=AsyncMock,
    )
    async def test_poll_returns_parse_result_with_score(self, mock_fetch, collector):
        mock_fetch.return_value = _mock_option_chain(underlying=18200.0)
        result = await collector.poll()
        assert "normalized" in result
        assert result["source"] == "nse"
        assert "as_of" in result
        detail = result["detail"]
        assert "pcr" in detail
        assert "max_pain" in detail
        assert "oi_concentration" in detail
