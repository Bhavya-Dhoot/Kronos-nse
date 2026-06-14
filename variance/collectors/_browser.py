"""Shared Playwright browser singleton for Scrapling-based collectors.

Lazily initialized on first use — import does NOT launch a browser.
A single shared instance avoids the ~150MB overhead per poll.
"""

from __future__ import annotations

import asyncio
import logging

try:
    from playwright.async_api import Browser, async_playwright
except ImportError:  # pragma: no cover
    Browser = None  # type: ignore

_logger = logging.getLogger(__name__)

_browser: Browser | None = None
_playwright_instance = None
_browser_refcount: int = 0

_BROWSER_LAUNCH_TIMEOUT = 20.0


async def _get_browser() -> Browser:
    """Return shared Browser instance, launching on first call."""
    global _browser, _playwright_instance
    if Browser is None:
        raise ImportError(
            "playwright not installed — run: pip install playwright && playwright install chromium"
        )
    if _browser is None:
        _logger.info("Launching shared Playwright browser instance")
        _playwright_instance = await async_playwright().start()
        try:
            _browser = await asyncio.wait_for(
                _playwright_instance.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                ),
                timeout=_BROWSER_LAUNCH_TIMEOUT,
            )
        except TimeoutError:
            _logger.error(
                "Chromium launch timed out after %ss — Playwright browser unavailable",
                _BROWSER_LAUNCH_TIMEOUT,
            )
            raise
    return _browser


async def _close_browser() -> None:
    """Clean shutdown — close browser and playwright."""
    global _browser, _playwright_instance
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None
