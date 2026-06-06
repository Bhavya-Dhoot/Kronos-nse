"""Angel One Smart API client wrapper for Kronos NSE.

Historical candle API:
  POST .../historical/v1/getCandleData
  Response rows: [timestamp, open, high, low, close, volume] (IST timestamps)

Rate limits (getCandleData): 3 req/s, 180 req/min, 5000 req/hr
Max days per request vary by interval — see MAX_DAYS_PER_INTERVAL.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp

try:
    from SmartApi import SmartConnect  # type: ignore
except Exception:  # pragma: no cover - tests mock this class
    SmartConnect = None  # type: ignore

logger = logging.getLogger(__name__)

# Exchange segment codes (request body `exchange` field)
EXCHANGE_NSE = "NSE"
EXCHANGE_NFO = "NFO"


from data.collector.rate_limiter import get_shared_historical_rate_limiter


class AngelOneClient:
    """Thin resilient wrapper around SmartAPI calls."""

    # Kronos timeframe -> Angel One interval constant
    INTERVAL_MAP: dict[str, str] = {
        "1min": "ONE_MINUTE",
        "3min": "THREE_MINUTE",
        "5min": "FIVE_MINUTE",
        "10min": "TEN_MINUTE",
        "15min": "FIFTEEN_MINUTE",
        "30min": "THIRTY_MINUTE",
        "1h": "ONE_HOUR",
        "1hour": "ONE_HOUR",
        "1day": "ONE_DAY",
        # allow passing Angel constants directly
        "ONE_MINUTE": "ONE_MINUTE",
        "THREE_MINUTE": "THREE_MINUTE",
        "FIVE_MINUTE": "FIVE_MINUTE",
        "TEN_MINUTE": "TEN_MINUTE",
        "FIFTEEN_MINUTE": "FIFTEEN_MINUTE",
        "THIRTY_MINUTE": "THIRTY_MINUTE",
        "ONE_HOUR": "ONE_HOUR",
        "ONE_DAY": "ONE_DAY",
    }

    # Official max calendar days per getCandleData request (per interval)
    MAX_DAYS_PER_INTERVAL: dict[str, int] = {
        "ONE_MINUTE": 30,
        "THREE_MINUTE": 60,
        "FIVE_MINUTE": 100,
        "TEN_MINUTE": 100,
        "FIFTEEN_MINUTE": 200,
        "THIRTY_MINUTE": 200,
        "ONE_HOUR": 400,
        "ONE_DAY": 2000,
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self.api_key = config.get("api_key") or config.get("ANGEL_API_KEY")
        self.client_id = config.get("client_id") or config.get("ANGEL_CLIENT_ID")
        self.password = config.get("password") or config.get("ANGEL_PASSWORD")
        self.totp_secret = config.get("totp_secret") or config.get("ANGEL_TOTP_SECRET")

        self._smart = SmartConnect(api_key=self.api_key) if SmartConnect else None
        self._ws = None
        self._session_data: dict[str, Any] | None = None
        self.jwt_token: str | None = None
        self._jwt_expiry_utc: datetime | None = None
        self._rate_limiter = get_shared_historical_rate_limiter()

    @classmethod
    def resolve_interval(cls, interval: str) -> str:
        """Map Kronos timeframe or Angel constant to Angel interval string."""
        key = interval.strip()
        if key in cls.INTERVAL_MAP:
            return cls.INTERVAL_MAP[key]
        lowered = key.lower()
        if lowered in cls.INTERVAL_MAP:
            return cls.INTERVAL_MAP[lowered]
        return key.upper()

    @classmethod
    def max_chunk_days_for_interval(cls, interval: str) -> int:
        """Max days allowed in a single getCandleData request for this interval."""
        angel_interval = cls.resolve_interval(interval)
        return cls.MAX_DAYS_PER_INTERVAL.get(angel_interval, 30)

    def authenticate(self) -> bool:
        """Authenticate with TOTP. Never raises."""
        try:
            if self._smart is None:
                logger.error("SmartConnect is unavailable. Install SmartApi-python.")
                return False

            otp = pyotp.TOTP(self.totp_secret).now()
            data = self._smart.generateSession(self.client_id, self.password, otp)
            if not data or not data.get("status", False):
                logger.error("Angel authentication failed: %s", data)
                return False

            payload = data.get("data") or {}
            self.jwt_token = payload.get("jwtToken")
            self._session_data = payload
            self._jwt_expiry_utc = datetime.now(timezone.utc) + timedelta(hours=24)
            return True
        except Exception:
            logger.exception("Angel authentication failed")
            return False

    def _refresh_session_if_needed(self) -> None:
        """Refresh session when nearing expiry (<1 hour)."""
        now = datetime.now(timezone.utc)
        if self._jwt_expiry_utc is None or now >= (self._jwt_expiry_utc - timedelta(hours=1)):
            self.authenticate()

    def get_historical(
        self,
        symbol_token: str,
        exchange: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[list[Any]]:
        """Fetch historical candles, retrying network failures.

        Returns list of [timestamp, open, high, low, close, volume].
        Timestamps are ISO strings in IST (+05:30). Never raises.
        """
        self._refresh_session_if_needed()
        if self._smart is None:
            return []

        angel_interval = self.resolve_interval(interval)
        params = {
            "exchange": exchange,
            "symboltoken": str(symbol_token),
            "interval": angel_interval,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        for attempt in range(3):
            try:
                self._rate_limiter.acquire()
                resp = self._smart.getCandleData(params)
                if not resp or not resp.get("status", False):
                    logger.warning("Angel getCandleData error: %s", resp)
                    return []
                data = resp.get("data") or []
                return data if isinstance(data, list) else []
            except Exception as exc:
                if attempt == 2:
                    logger.warning("Historical fetch failed after retries: %s", exc)
                    return []
                time.sleep(1.0)
        return []

    def _build_chunks(
        self,
        from_date: datetime,
        to_date: datetime,
        chunk_days: int,
    ) -> list[tuple[datetime, datetime]]:
        chunks: list[tuple[datetime, datetime]] = []
        cur = from_date
        while cur < to_date:
            end = min(cur + timedelta(days=chunk_days), to_date)
            chunks.append((cur, end))
            if end >= to_date:
                break
            cur = end - timedelta(minutes=1) + timedelta(seconds=1)
        return chunks

    @staticmethod
    def _tf_minutes(interval: str) -> int:
        tf = interval.strip().lower()
        # Angel constants: ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE, etc.
        _ANGEL = {
            "one_minute": 1, "three_minute": 3, "five_minute": 5,
            "ten_minute": 10, "fifteen_minute": 15, "thirty_minute": 30,
            "one_hour": 60, "one_day": 1440,
        }
        if tf in _ANGEL:
            return _ANGEL[tf]
        if tf.endswith("min"):
            return int(tf[:-3])
        if tf.endswith("m"):
            return int(tf[:-1])
        if tf.endswith("hour") or tf.endswith("h"):
            n = tf[:-4] if tf.endswith("hour") else tf[:-1]
            return int(n) * 60
        if tf.endswith("day") or tf.endswith("d"):
            n = tf[:-3] if tf.endswith("day") else tf[:-1]
            return int(n) * 24 * 60
        raise ValueError(f"Unsupported interval: {interval}")

    @classmethod
    def _expected_per_trading_day(cls, interval: str) -> int:
        # NSE session minutes 09:15–15:30 = 375 minutes
        tf_min = cls._tf_minutes(interval)
        return max(1, 375 // tf_min)

    @staticmethod
    def _parse_row_ts(row: list[Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(str(row[0]))
        except Exception:
            return None

    # Maximum recursion depth for chunk-splitting retries
    MAX_RECURSION_DEPTH: int = 3

    def _suspect_truncation(
        self,
        *,
        interval: str,
        c_from: datetime,
        c_to: datetime,
        rows: list[list[Any]],
    ) -> bool:
        """Heuristic to detect silent truncation / bad fetches.

        SmartAPI can return partial data without errors; this flags likely issues.
        Returns False (accept data) for short windows (<= 10 calendar days) since
        the heuristic is unreliable for small ranges.
        """
        if not rows:
            # Empty result is suspicious only if the range has trading days
            span_days = (c_to.date() - c_from.date()).days
            return span_days > 3  # tiny ranges may legitimately be empty (holidays)

        # Skip heuristic for very small chunks — not enough data to judge
        span_days = (c_to.date() - c_from.date()).days
        if span_days <= 10:
            return False

        try:
            from scripts.seed_instruments import is_trading_day
        except Exception:
            return False

        start_d = c_from.date()
        end_d = c_to.date()
        days = 0
        cur = start_d
        while cur <= end_d:
            if is_trading_day(cur):
                days += 1
            cur = cur + timedelta(days=1)

        if days <= 1:
            return False

        expected = self._expected_per_trading_day(interval) * days
        actual = len(rows)
        # Relaxed threshold: 60% instead of 80% — weekends, holidays, partial
        # sessions, and API quirks legitimately reduce density for bulk fetches
        if actual < expected * 0.60:
            return True

        first_ts = self._parse_row_ts(rows[0])
        last_ts = self._parse_row_ts(rows[-1])
        if first_ts is None or last_ts is None:
            return True

        # Require that the returned series roughly covers the requested span.
        # Allow slack because ranges can start/end on weekends/holidays and
        # SmartAPI sometimes omits boundary candles.
        slack_days = 7
        if last_ts.date() < (c_to.date() - timedelta(days=slack_days)):
            return True
        if first_ts.date() > (c_from.date() + timedelta(days=slack_days)):
            return True
        return False

    def get_historical_chunked(
        self,
        symbol_token: str,
        exchange: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        chunk_days: int | None = None,
        *,
        _depth: int = 0,
    ) -> list[list[Any]]:
        """Fetch long ranges using Angel's per-interval max-days limits.

        Default chunk size comes from MAX_DAYS_PER_INTERVAL for the interval.
        Deduplicates overlapping chunk edges. Respects getCandleData rate limits.
        Recursion depth is bounded by MAX_RECURSION_DEPTH to prevent infinite loops.
        """
        if chunk_days is None:
            chunk_days = self.max_chunk_days_for_interval(interval)

        all_rows: dict[str, list[Any]] = {}
        chunks = self._build_chunks(from_date, to_date, chunk_days)
        total_chunks = len(chunks)

        for idx, (c_from, c_to) in enumerate(chunks):
            logger.info(
                "chunk %d/%d token=%s %s..%s (chunk_days=%d, depth=%d)",
                idx + 1, total_chunks, symbol_token,
                c_from.date(), c_to.date(), chunk_days, _depth,
            )
            rows = self.get_historical(symbol_token, exchange, interval, c_from, c_to)

            # Only attempt recursive retry if we haven't exceeded depth limit
            if (
                _depth < self.MAX_RECURSION_DEPTH
                and chunk_days > 5
                and self._suspect_truncation(interval=interval, c_from=c_from, c_to=c_to, rows=rows)
            ):
                smaller = max(5, chunk_days // 2)
                logger.warning(
                    "Suspected truncation token=%s interval=%s chunk=%s..%s "
                    "(rows=%d, depth=%d). Retrying with %d-day chunks.",
                    symbol_token, interval,
                    c_from.date(), c_to.date(),
                    len(rows), _depth, smaller,
                )
                sub_rows = self.get_historical_chunked(
                    symbol_token=symbol_token,
                    exchange=exchange,
                    interval=interval,
                    from_date=c_from,
                    to_date=c_to,
                    chunk_days=smaller,
                    _depth=_depth + 1,
                )
                rows = sub_rows
            elif (
                _depth >= self.MAX_RECURSION_DEPTH
                and self._suspect_truncation(interval=interval, c_from=c_from, c_to=c_to, rows=rows)
            ):
                logger.warning(
                    "Max recursion depth (%d) reached for token=%s chunk=%s..%s. "
                    "Accepting %d rows as-is.",
                    self.MAX_RECURSION_DEPTH, symbol_token,
                    c_from.date(), c_to.date(), len(rows),
                )

            for row in rows:
                if not row:
                    continue
                all_rows[str(row[0])] = row

            if (idx + 1) % 5 == 0 or idx + 1 == total_chunks:
                logger.info(
                    "Progress: token=%s %d/%d chunks done, %d total rows so far",
                    symbol_token, idx + 1, total_chunks, len(all_rows),
                )

        return [all_rows[k] for k in sorted(all_rows.keys())]

    def start_websocket(
        self,
        tokens_list: list[dict[str, Any]],
        on_tick_callback,
        on_error_callback,
    ) -> None:
        """Start websocket streaming in mode 3 (full snap quote)."""
        self._refresh_session_if_needed()
        if self._smart is None:
            on_error_callback(RuntimeError("SmartConnect unavailable"))
            return
        try:
            if self._ws and hasattr(self._ws, "close_connection"):
                self._ws.close_connection()
            self._ws = getattr(self._smart, "ws", None) or getattr(self._smart, "websocket", None)
            if self._ws is None:
                raise RuntimeError("Smart WebSocket client not available")

            if hasattr(self._ws, "on_data"):
                self._ws.on_data = on_tick_callback
            if hasattr(self._ws, "on_error"):
                self._ws.on_error = on_error_callback
            if hasattr(self._ws, "subscribe"):
                self._ws.subscribe(tokens_list, mode=3)
            if hasattr(self._ws, "connect"):
                self._ws.connect()
        except Exception as exc:
            on_error_callback(exc)

    def stop_websocket(self) -> None:
        """Gracefully stop websocket connection."""
        try:
            if self._ws and hasattr(self._ws, "close_connection"):
                self._ws.close_connection()
        except Exception:
            logger.exception("Failed stopping websocket")

    def get_futures_oi(self, symbol: str) -> dict:
        """Fetch futures OI for a symbol via Smart API.

        Args:
            symbol: Symbol name, e.g. "NIFTY", "BANKNIFTY".

        Returns:
            dict with OI data. Empty dict on error (never raises).
        """
        self._refresh_session_if_needed()
        if self._smart is None:
            return {}
        try:
            if hasattr(self._smart, 'ltpData'):
                exchange = "NFO"
                trading_symbol = self._build_futures_symbol(symbol)
                resp = self._smart.ltpData(exchange, trading_symbol, "")
                if resp and resp.get("status", False):
                    data = resp.get("data", {}) or {}
                    return {
                        "symbol": symbol,
                        "open_interest": data.get("openInterest", 0) or data.get("oi", 0),
                        "ltp": data.get("ltp", 0) or data.get("lastPrice", 0),
                        "change": data.get("change", 0),
                        "source": "angel_ltp",
                    }
            return {}
        except Exception:
            return {}

    def _build_futures_symbol(self, symbol: str) -> str:
        """Build the Angel One futures trading symbol."""
        return f"{symbol}FUT"

    def get_previous_close(
        self,
        symbol_token: str = "99926000",
        exchange: str = "NSE",
    ) -> float | None:
        """Fetch the last completed daily candle's close price.

        Per D-01: calls getCandleData with ONE_DAY interval for yesterday.
        Per D-03: default token for NIFTY 50 = "99926000", exchange = "NSE".
        Per D-05: returns None on error (never raises).
        """
        now = datetime.now(timezone.utc)
        # Yesterday's date in IST
        yesterday = now - timedelta(days=1)
        from_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)

        data = self.get_historical(symbol_token, exchange, "1day", from_date, to_date)
        if not data:
            return None
        try:
            return float(data[-1][4])  # last row, close column
        except (IndexError, TypeError, ValueError):
            return None
