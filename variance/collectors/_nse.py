"""Shared NseIndiaApi singleton for MVE collectors.

Lazily initialized on first use — import does NOT create a session.
Both VIXCollector and OptionsCollector share the same instance
via _get_nse_api(). All NSE API calls are rate-limited to 1 req/s,
60 req/min to avoid connection resets from the NSE website.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from typing import Any

try:
    from data.collector.rate_limiter import AngelHistoricalRateLimiter
except ImportError:
    AngelHistoricalRateLimiter = None

try:
    from nse import NSE as NseIndiaApi  # noqa: N811
except ImportError:  # pragma: no cover — tests mock this
    NseIndiaApi = None  # type: ignore

_logger = logging.getLogger(__name__)

_nse_api: NseIndiaApi | None = None
_nse_refcount: int = 0

# Eager-init the NSE rate limiter at module load — no async code runs yet, so
# no lock is needed and the blocking AngelHistoricalRateLimiter constructor is safe.
_nse_rate_limiter: AngelHistoricalRateLimiter | None = None
if AngelHistoricalRateLimiter is not None:
    try:
        _nse_rate_limiter = AngelHistoricalRateLimiter(
            per_second=1,
            per_minute=60,
            per_hour=1000,
        )
        _logger.debug("NSE rate limiter initialised (1/s, 60/min, 1000/hr)")
    except Exception:
        _logger.exception("Failed to initialise NSE rate limiter")


def _get_nse_api() -> NseIndiaApi:
    """Return the shared NseIndiaApi instance, lazy-initializing it on first call."""
    global _nse_api, _nse_refcount
    if NseIndiaApi is None:
        raise ImportError(
            "nse package not installed — run: pip install nse @ git+https://github.com/BennyThadikaran/NseIndiaApi.git"
        )
    if _nse_api is None:
        _logger.info("Initializing shared NseIndiaApi instance")
        _nse_api = NseIndiaApi(tempfile.gettempdir())
    _nse_refcount += 1
    return _nse_api


def _get_nse_rate_limiter() -> AngelHistoricalRateLimiter:
    if _nse_rate_limiter is None:
        raise RuntimeError("NSE rate limiter not available at import time")
    return _nse_rate_limiter


async def _fetch_all_indices() -> list[dict[str, Any]]:
    """Fetch all NSE indices via asyncio.to_thread wrapper.

    Per D-04: NseIndiaApi is a sync library — all calls wrapped in asyncio.to_thread().
    """
    api = _get_nse_api()
    limiter = _get_nse_rate_limiter()

    def _sync_fetch() -> list[dict[str, Any]]:
        limiter.acquire()
        data = api.listIndices()
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    data = await asyncio.to_thread(_sync_fetch)
    return data


async def _fetch_option_chain(symbol: str = "NIFTY") -> dict[str, Any]:
    """Fetch NIFTY option chain via asyncio.to_thread wrapper.

    Per D-07: calls self._api.get_option_chain(symbol="NIFTY") wrapped in to_thread.
    """
    api = _get_nse_api()
    limiter = _get_nse_rate_limiter()

    def _sync_fetch() -> dict[str, Any]:
        limiter.acquire()
        return api.optionChain(symbol)

    return await asyncio.to_thread(_sync_fetch)


async def _fetch_fii_dii_data() -> dict[str, Any]:
    """Fetch FII/DII net flow data via asyncio.to_thread wrapper.

    Tries common method names on the NseIndiaApi object:
      get_fii_dii_data, get_fii_dii_net_flows, get_fii_dii
    Raises NotImplementedError if none are found.
    """
    api = _get_nse_api()
    limiter = _get_nse_rate_limiter()

    def _sync_fetch() -> Any:
        limiter.acquire()
        for method_name in ("get_fii_dii_data", "get_fii_dii_net_flows", "get_fii_dii"):
            method = getattr(api, method_name, None)
            if method is not None:
                return method()
        raise NotImplementedError(
            "No FII/DII method found on NseIndiaApi — expected one of: "
            "get_fii_dii_data, get_fii_dii_net_flows, get_fii_dii"
        )

    return await asyncio.to_thread(_sync_fetch)
