from __future__ import annotations

from unittest.mock import patch

from data.collector.rate_limiter import AngelHistoricalRateLimiter


def test_rate_limiter_allows_requests_under_cap():
    limiter = AngelHistoricalRateLimiter(per_second=10, per_minute=1000, per_hour=10000)
    for _ in range(5):
        limiter.acquire()


def test_rate_limiter_waits_when_second_window_full():
    limiter = AngelHistoricalRateLimiter(per_second=1, per_minute=100, per_hour=1000)
    times = iter([0.0, 0.0, 0.0, 2.0, 2.0])

    with patch(
        "data.collector.rate_limiter.time.monotonic",
        side_effect=lambda: next(times, 2.0),
    ):
        with patch("data.collector.rate_limiter.time.sleep") as sleep_mock:
            limiter.acquire()
            limiter.acquire()
            assert sleep_mock.called
