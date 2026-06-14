"""Shared rate limiter for Angel One getCandleData / getOIData.

Limits (per client/API key):
  - 3 requests / second
  - 180 requests / minute
  - 5000 requests / hour
"""

from __future__ import annotations

import threading
import time
from collections import deque


class AngelHistoricalRateLimiter:
    """Thread-safe limiter shared across all collector workers."""

    def __init__(
        self,
        per_second: int = 5,
        per_minute: int = 300,
        per_hour: int = 5000,
    ) -> None:
        self._per_second_limit = per_second
        self._per_minute_limit = per_minute
        self._per_hour_limit = per_hour
        self._lock = threading.Lock()
        self._sec: deque[float] = deque()
        self._min: deque[float] = deque()
        self._hour: deque[float] = deque()

    def _evict(self, now: float) -> None:
        while self._sec and now - self._sec[0] >= 1.0:
            self._sec.popleft()
        while self._min and now - self._min[0] >= 60.0:
            self._min.popleft()
        while self._hour and now - self._hour[0] >= 3600.0:
            self._hour.popleft()

    def _sleep_hint(self, now: float) -> float:
        """Compute minimum wait to clear the tightest rate limit bucket."""
        waits: list[float] = []
        if len(self._sec) >= self._per_second_limit and self._sec:
            waits.append(max(0.0, 1.0 - (now - self._sec[0])))
        if len(self._min) >= self._per_minute_limit and self._min:
            waits.append(max(0.0, 60.0 - (now - self._min[0])))
        if len(self._hour) >= self._per_hour_limit and self._hour:
            wait_hr = max(0.0, 3600.0 - (now - self._hour[0]))
            waits.append(wait_hr)
        if not waits:
            return 0.34  # default short delay between requests
        return min(waits) + 0.05  # small buffer

    def acquire(self) -> None:
        """Block until a request slot is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._evict(now)
                if (
                    len(self._sec) < self._per_second_limit
                    and len(self._min) < self._per_minute_limit
                    and len(self._hour) < self._per_hour_limit
                ):
                    self._sec.append(now)
                    self._min.append(now)
                    self._hour.append(now)
                    return
                delay = self._sleep_hint(now)
                # Log when hitting hourly limit (long waits)
                if len(self._hour) >= self._per_hour_limit:
                    import logging

                    logging.getLogger(__name__).info(
                        "Rate limiter: hourly limit (%d) reached, waiting %.1fs",
                        self._per_hour_limit,
                        delay,
                    )
            time.sleep(delay)


_shared_limiter: AngelHistoricalRateLimiter | None = None
_limiter_lock = threading.Lock()

_shared_ltp_limiter: AngelHistoricalRateLimiter | None = None
_ltp_limiter_lock = threading.Lock()


def get_shared_historical_rate_limiter() -> AngelHistoricalRateLimiter:
    global _shared_limiter
    with _limiter_lock:
        if _shared_limiter is None:
            _shared_limiter = AngelHistoricalRateLimiter()
        return _shared_limiter


def get_shared_ltp_rate_limiter() -> AngelHistoricalRateLimiter:
    """Shared limiter for ltpData calls (2 req/s, 60 req/min, 1000 req/hr)."""
    global _shared_ltp_limiter
    with _ltp_limiter_lock:
        if _shared_ltp_limiter is None:
            _shared_ltp_limiter = AngelHistoricalRateLimiter(
                per_second=2,
                per_minute=60,
                per_hour=1000,
            )
        return _shared_ltp_limiter
