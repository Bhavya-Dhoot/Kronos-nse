"""Process watchdog — detects stalled headless candle cycles."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

logger = logging.getLogger(__name__)


class Watchdog:
    """Monitors headless heartbeat and terminates the process on stall."""

    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds
        self._last_heartbeat = time.time()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start background watchdog thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.heartbeat()
        self._thread = threading.Thread(
            target=self._watch, name="headless-watchdog", daemon=True
        )
        self._thread.start()
        logger.info("Watchdog started (timeout=%ds)", self.timeout_seconds)

    def stop(self) -> None:
        """Stop watchdog thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def heartbeat(self) -> None:
        """Record a successful candle cycle."""
        with self._lock:
            self._last_heartbeat = time.time()

    def _heartbeat_age(self) -> float:
        with self._lock:
            return time.time() - self._last_heartbeat

    def _watch(self) -> None:
        while not self._stop.wait(10):
            age = self._heartbeat_age()
            if age > self.timeout_seconds:
                logger.critical(
                    "Headless watchdog: no heartbeat for %.1fs (limit %ds) — sending SIGTERM",
                    age,
                    self.timeout_seconds,
                )
                os.kill(os.getpid(), signal.SIGTERM)
                return
            if age > self.timeout_seconds / 2:
                logger.warning(
                    "Headless watchdog: heartbeat stale %.1fs (warn at %ds)",
                    age,
                    int(self.timeout_seconds / 2),
                )
