"""Shared NseIndiaApi singleton for MVE collectors.

Lazily initialized on first use — import does NOT create a session.
Both VIXCollector and OptionsCollector share the same instance
via _get_nse_api().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from nse import NseIndiaApi
except ImportError:  # pragma: no cover — tests mock this
    NseIndiaApi = None  # type: ignore

_logger = logging.getLogger(__name__)

_nse_api: NseIndiaApi | None = None


def _get_nse_api() -> NseIndiaApi:
    """Return the shared NseIndiaApi instance, lazy-initializing it on first call."""
    global _nse_api
    if NseIndiaApi is None:
        raise ImportError("nse package not installed — run: pip install nse @ git+https://github.com/BennyThadikaran/NseIndiaApi.git")
    if _nse_api is None:
        _logger.info("Initializing shared NseIndiaApi instance")
        _nse_api = NseIndiaApi()
    return _nse_api


async def _fetch_all_indices() -> list[dict[str, Any]]:
    """Fetch all NSE indices via asyncio.to_thread wrapper.

    Per D-04: NseIndiaApi is a sync library — all calls wrapped in asyncio.to_thread().
    """
    api = _get_nse_api()
    return await asyncio.to_thread(api.get_all_indices)


async def _fetch_option_chain(symbol: str = "NIFTY") -> dict[str, Any]:
    """Fetch NIFTY option chain via asyncio.to_thread wrapper.

    Per D-07: calls self._api.get_option_chain(symbol="NIFTY") wrapped in to_thread.
    """
    api = _get_nse_api()
    return await asyncio.to_thread(api.get_option_chain, symbol)


async def _fetch_fii_dii_data() -> dict[str, Any]:
    """Fetch FII/DII net flow data via asyncio.to_thread wrapper.

    Tries common method names on the NseIndiaApi object:
      get_fii_dii_data, get_fii_dii_net_flows, get_fii_dii
    Raises NotImplementedError if none are found.
    """
    api = _get_nse_api()
    for method_name in ("get_fii_dii_data", "get_fii_dii_net_flows", "get_fii_dii"):
        method = getattr(api, method_name, None)
        if method is not None:
            return await asyncio.to_thread(method)
    raise NotImplementedError(
        "No FII/DII method found on NseIndiaApi — expected one of: "
        "get_fii_dii_data, get_fii_dii_net_flows, get_fii_dii"
    )
