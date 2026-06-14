"""GIFTNiftyCollector — scrapes GIFT Nifty index value via Playwright.

Primary source: Groww.in (every 5min)
Fallback: niftytrader.in (when primary fails)
Computes gap vs previous Nifty 50 close and produces directional score.

Per D-04: gap_pct = (gift_nifty_value - prev_close) / prev_close * 100
Per D-06: score = min(1.0, max(-1.0, gap_pct * 50))
Per D-07: when prev_close is None, score = 0.0, gap_pct = None in detail
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import yaml

from variance.base_collector import BaseVarianceCollector
from variance.collectors._angel import _get_angel_client
from variance.collectors._browser import _get_browser
from variance.schemas import ParseResult

_logger = logging.getLogger(__name__)


def _load_config() -> dict[str, Any]:
    """Load GIFT Nifty config from base.yaml."""
    with open("config/base.yaml") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("variance", {}).get("gift_nifty", {})


class GIFTNiftyCollector(BaseVarianceCollector):
    """Scrape GIFT Nifty value every 300s via Playwright.

    Primary: Groww.in (configurable via base.yaml)
    Fallback: niftytrader.in
    """

    def __init__(self) -> None:
        super().__init__(name="gift_nifty", poll_interval=300)
        self._gift_config = _load_config()

    async def fetch(self) -> dict[str, Any]:
        """Fetch GIFT Nifty value using Playwright.

        Tries primary URL first, falls back to secondary on failure.
        Returns dict with value, source, and url on success.
        Raises ValueError if both sources fail.
        """
        browser = await _get_browser()
        primary = self._gift_config.get(
            "primary_url", "https://groww.in/markets/gift-nifty"
        )
        fallback = self._gift_config.get(
            "fallback_url", "https://niftytrader.in/gift-nifty"
        )

        for url, source_name in [(primary, "groww"), (fallback, "niftytrader")]:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

                text = await page.locator("body").text_content()
                if not text:
                    continue

                numbers = re.findall(r"[\d,]+\.?\d*", text)
                parsed = [
                    float(n.replace(",", ""))
                    for n in numbers
                    if n.replace(",", "").replace(".", "").isdigit()
                    or (
                        n.count(".") == 1
                        and n.replace(",", "").replace(".", "").isdigit()
                    )
                ]
                valid = [v for v in parsed if 15000 < v < 40000]
                if valid:
                    return {"value": valid[0], "source": source_name, "url": url}
            except Exception as e:
                _logger.warning("GIFT Nifty scrape failed for %s: %s", url, e)
            finally:
                await page.close()

        raise ValueError("GIFT Nifty: both primary and fallback sources failed")

    def parse(self, raw: dict[str, Any]) -> ParseResult:
        """Extract GIFT Nifty value and compute gap vs previous close."""
        gift_value = raw.get("value")
        if gift_value is None:
            raise ValueError("No GIFT Nifty value in fetch result")

        angel = _get_angel_client()
        prev_close = angel.get_previous_close()

        gap_pct = None
        direction = 0
        magnitude = 0.0

        if prev_close is not None and prev_close > 0:
            gap_pct = round((gift_value - prev_close) / prev_close * 100, 4)
            direction = 1 if gap_pct > 0 else (-1 if gap_pct < 0 else 0)
            magnitude = abs(gap_pct) / 100.0  # normalize magnitude

        return ParseResult(
            raw_value=float(gift_value),
            normalized=0.0,
            direction=direction,
            magnitude=magnitude,
            detail={
                "gap_pct": gap_pct,
                "prev_close": prev_close,
                "gift_nifty_value": float(gift_value),
                "source": raw.get("source", "unknown"),
            },
            source=raw.get("source", "unknown"),
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Score GIFT Nifty gap using linear formula per D-06.

        score = min(1.0, max(-1.0, gap_pct * 50))
        Returns 0.0 when gap_pct is None per D-07.
        """
        gap_pct = parsed.get("detail", {}).get("gap_pct")
        if gap_pct is None:
            return 0.0
        return max(-1.0, min(1.0, gap_pct * 0.5))
