"""Base abstract collector for MVE dimension data."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from variance.schemas import ParseResult


class BaseVarianceCollector(ABC):
    """Abstract base for dimension-specific MVE collectors.

    Subclasses must implement fetch(), parse(), and score().
    The concrete poll() method chains all three and implements
    a circuit-breaker that trips after max_errors consecutive failures.
    """

    def __init__(
        self,
        name: str,
        poll_interval: int = 60,
        max_errors: int = 5,
    ) -> None:
        self.name = name
        self.poll_interval = poll_interval
        self._max_errors = max_errors
        self._consecutive_errors: int = 0
        self._last_successful_result: ParseResult | None = None
        self._last_poll_time: datetime | None = None
        self._logger = logging.getLogger(f"{__name__}.{name}")

    @abstractmethod
    async def fetch(self) -> Any:
        """Fetch raw data from the external source."""
        ...

    @abstractmethod
    def parse(self, raw: Any) -> ParseResult:
        """Parse raw data into a structured ParseResult."""
        ...

    @abstractmethod
    def score(self, parsed: ParseResult) -> float:
        """Return a normalized score in [-1.0, 1.0]."""
        ...

    async def poll(self) -> ParseResult:
        """Execute a full poll cycle: fetch -> parse -> score.

        Returns a ParseResult with the computed score.
        On failure, returns a stale copy of the last successful result
        if one exists, otherwise re-raises the exception.
        """
        try:
            raw = await self.fetch()
            parsed = self.parse(raw)
            score_val = self.score(parsed)
            parsed["normalized"] = score_val
            parsed["as_of"] = datetime.now(UTC).isoformat()
            self._last_successful_result = deepcopy(parsed)
            self._last_poll_time = datetime.now(UTC)
            self._consecutive_errors = 0
            return parsed
        except Exception:
            self._consecutive_errors += 1
            self._logger.warning(
                "Poll failed (%d/%d): %s",
                self._consecutive_errors,
                self._max_errors,
                self.name,
                exc_info=True,
            )
            if self._last_successful_result is not None:
                stale = deepcopy(self._last_successful_result)
                stale["as_of"] = datetime.now(UTC).isoformat()
                return stale
            raise

    @property
    def is_available(self) -> bool:
        """Return True if the collector has not exceeded the error threshold."""
        return self._consecutive_errors < self._max_errors

    async def poll_loop(self) -> AsyncIterator[ParseResult]:
        """Infinite async generator yielding poll results at the configured interval."""
        while True:
            result = await self.poll()
            yield result
            await asyncio.sleep(self.poll_interval)
