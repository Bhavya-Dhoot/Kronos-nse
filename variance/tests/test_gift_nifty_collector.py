"""Unit tests for GIFTNiftyCollector.

All browser and AngelOneClient calls are mocked.
No live Playwright browser or Angel One API required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from variance.collectors.gift_nifty_collector import GIFTNiftyCollector


@pytest.fixture
def collector() -> GIFTNiftyCollector:
    return GIFTNiftyCollector()


def _mock_page(text: str = "23500.50") -> MagicMock:
    mock_locator = MagicMock()
    mock_locator.text_content = AsyncMock(return_value=text)
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.locator.return_value = mock_locator
    mock_page.close = AsyncMock()
    return mock_page


def _mock_browser(page: MagicMock | None = None) -> MagicMock:
    if page is None:
        page = _mock_page()
    mock_browser = MagicMock()
    mock_browser.new_page = AsyncMock(return_value=page)
    return mock_browser


SAMPLE_FETCH_OK = {
    "value": 23500.5,
    "source": "groww",
    "url": "https://groww.in/markets/gift-nifty",
}


class TestFetch:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.gift_nifty_collector._get_browser", new_callable=AsyncMock
    )
    async def test_fetch_returns_value_and_source(self, mock_get_browser):
        page = _mock_page("23500.50")
        mock_get_browser.return_value = _mock_browser(page)

        result = await GIFTNiftyCollector().fetch()

        assert result["value"] == 23500.5
        assert result["source"] == "groww"
        page.close.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "variance.collectors.gift_nifty_collector._get_browser", new_callable=AsyncMock
    )
    async def test_fetch_fallback_on_empty_primary(self, mock_get_browser):
        primary_page = _mock_page("")
        fallback_page = _mock_page("23600.75")
        mock_browser = MagicMock()
        mock_browser.new_page = AsyncMock(side_effect=[primary_page, fallback_page])
        mock_get_browser.return_value = mock_browser

        result = await GIFTNiftyCollector().fetch()

        assert result["value"] == 23600.75
        assert result["source"] == "niftytrader"

    @pytest.mark.asyncio
    @patch(
        "variance.collectors.gift_nifty_collector._get_browser", new_callable=AsyncMock
    )
    async def test_fetch_raises_on_all_failures(self, mock_get_browser):
        empty_page = _mock_page("")
        mock_browser = MagicMock()
        mock_browser.new_page = AsyncMock(return_value=empty_page)
        mock_get_browser.return_value = mock_browser

        with pytest.raises(ValueError, match="both primary and fallback"):
            await GIFTNiftyCollector().fetch()


class TestParse:
    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_computes_gap(self, mock_get_angel):
        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = 23500.0
        mock_get_angel.return_value = mock_angel

        result = GIFTNiftyCollector().parse(SAMPLE_FETCH_OK)

        assert result["raw_value"] == 23500.5
        assert result["detail"]["gap_pct"] == pytest.approx(0.0021, abs=0.001)
        assert result["detail"]["prev_close"] == 23500.0
        assert result["direction"] == 1

    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_negative_gap(self, mock_get_angel):
        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = 24000.0
        mock_get_angel.return_value = mock_angel

        result = GIFTNiftyCollector().parse(SAMPLE_FETCH_OK)

        assert result["detail"]["gap_pct"] == pytest.approx(-2.0812, abs=0.01)
        assert result["direction"] == -1

    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_no_prev_close(self, mock_get_angel):
        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = None
        mock_get_angel.return_value = mock_angel

        result = GIFTNiftyCollector().parse(SAMPLE_FETCH_OK)

        assert result["detail"]["gap_pct"] is None
        assert result["direction"] == 0
        assert result["raw_value"] == 23500.5

    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_raises_on_no_value(self, mock_get_angel):
        with pytest.raises(ValueError, match="No GIFT Nifty value"):
            GIFTNiftyCollector().parse({"source": "groww", "url": "..."})

    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_detail_has_expected_keys(self, mock_get_angel):
        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = 23500.0
        mock_get_angel.return_value = mock_angel

        result = GIFTNiftyCollector().parse(SAMPLE_FETCH_OK)

        expected_keys = {"gap_pct", "prev_close", "gift_nifty_value", "source"}
        assert expected_keys.issubset(result["detail"].keys())
        assert result["source"] == "groww"

    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    def test_parse_zero_gap(self, mock_get_angel):
        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = 23500.5
        mock_get_angel.return_value = mock_angel

        result = GIFTNiftyCollector().parse(SAMPLE_FETCH_OK)

        assert result["detail"]["gap_pct"] == pytest.approx(0.0, abs=0.001)
        assert result["direction"] == 0


class TestScore:
    @pytest.mark.parametrize(
        "gap_pct,expected",
        [
            (0.0, 0.0),
            (1.0, 0.5),
            (2.0, 1.0),
            (-1.0, -0.5),
            (-2.0, -1.0),
            (3.0, 1.0),
            (-3.0, -1.0),
            (0.5, 0.25),
            (-0.5, -0.25),
        ],
    )
    def test_score_formula(self, collector, gap_pct, expected):
        parsed = {
            "raw_value": 23500.0,
            "detail": {"gap_pct": gap_pct},
            "source": "groww",
        }
        score = collector.score(parsed)
        assert score == pytest.approx(expected, abs=0.01)

    def test_score_no_gap_returns_zero(self, collector):
        parsed = {
            "raw_value": 23500.0,
            "detail": {"gap_pct": None},
            "source": "groww",
        }
        score = collector.score(parsed)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_score_missing_detail_returns_zero(self, collector):
        parsed = {"raw_value": 23500.0, "detail": {}}
        score = collector.score(parsed)
        assert score == pytest.approx(0.0, abs=0.01)


class TestIntegration:
    @pytest.mark.asyncio
    @patch(
        "variance.collectors.gift_nifty_collector._get_browser", new_callable=AsyncMock
    )
    @patch("variance.collectors.gift_nifty_collector._get_angel_client")
    async def test_poll_returns_parse_result(self, mock_get_angel, mock_get_browser):
        page = _mock_page("23500.50")
        mock_get_browser.return_value = _mock_browser(page)

        mock_angel = MagicMock()
        mock_angel.get_previous_close.return_value = 23500.0
        mock_get_angel.return_value = mock_angel

        result = await GIFTNiftyCollector().poll()

        assert "normalized" in result
        assert result["raw_value"] == 23500.5
        assert result["source"] == "groww"
        assert "as_of" in result
        assert result["detail"]["gap_pct"] is not None
