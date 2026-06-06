"""Shared AngelOneClient singleton for MVE collectors.

Lazily initialized on first use — import does NOT create a session.
Config must be injected via _set_angel_config() before first _get_angel_client() call.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from data.collector.angel_client import AngelOneClient
except ImportError:  # pragma: no cover — tests mock this
    AngelOneClient = None  # type: ignore

_logger = logging.getLogger(__name__)

_angel_client: AngelOneClient | None = None
_angel_config: dict[str, Any] | None = None


def _set_angel_config(config: dict[str, Any]) -> None:
    """Inject Angel One configuration before first client instantiation.

    Must be called during application startup. Raises RuntimeError if
    the client has already been initialized.
    """
    global _angel_config
    if _angel_client is not None:
        raise RuntimeError(
            "Cannot set Angel One config after client has been initialized"
        )
    _angel_config = dict(config)
    _logger.info("Angel One configuration stored (%d keys)", len(config))


def _get_angel_client() -> AngelOneClient:
    """Return the shared AngelOneClient instance, lazy-initializing it on first call."""
    global _angel_client
    if AngelOneClient is None:
        raise ImportError(
            "AngelOneClient not available — check data.collector.angel_client dependencies"
        )
    if _angel_client is None:
        if _angel_config is None:
            raise RuntimeError(
                "Angel One config not set — call _set_angel_config() first"
            )
        _logger.info("Initializing shared AngelOneClient instance")
        _angel_client = AngelOneClient(_angel_config)
    return _angel_client
