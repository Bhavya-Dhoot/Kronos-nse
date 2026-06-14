"""Async retry decorator with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter_factor: float = 0.1,
    exc_types: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry an async function with exponential backoff and jitter.

    Parameters
    ----------
    max_attempts : int
        Maximum number of attempts (default 3).
    base_delay : float
        Initial delay in seconds (default 1.0).
    max_delay : float
        Maximum delay cap in seconds (default 30.0).
    jitter_factor : float
        Random jitter as fraction of the delay (default 0.1).
    exc_types : tuple[Exception]
        Exception types that trigger a retry (default all Exception).

    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exc_types as e:
                    last_exc = e
                    if attempt == max_attempts:
                        logger.warning(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            e,
                        )
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    jitter = random.uniform(
                        -jitter_factor * delay, jitter_factor * delay
                    )
                    total_delay = delay + jitter
                    logger.debug(
                        "%s attempt %d/%d failed (%s), retrying in %.2fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        e,
                        total_delay,
                    )
                    await asyncio.sleep(total_delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
