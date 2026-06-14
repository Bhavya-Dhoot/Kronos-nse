"""Async API fetchers for Kronos NSE TUI v2 — HTTP + WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

_logger = logging.getLogger("kronos.fetcher")

import httpx
import websockets

from scripts.tui_lib.levels import _to_float, compute_rsi_from_closes

API_BASE = os.getenv("KRONOS_API", "http://localhost:8000")
TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None
_client_lock: threading.Lock = threading.Lock()

# WebSocket connection state — all mutations protected by _ws_state_lock
_ws_state_lock: threading.Lock = threading.Lock()

_ws_connections: dict[str, websockets.WebSocketClientProtocol] = {}
_ws_listener_tasks: dict[str, asyncio.Task] = {}
_ws_reconnect_count: dict[str, int] = {}
_ws_connected: dict[str, bool] = {}
_ws_closing: set[str] = set()  # names being actively disconnected
WS_BASE = os.getenv("KRONOS_WS", "ws://localhost:8000")


def _to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(timeout=TIMEOUT)
    return _client


async def fetch_json(path: str, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            client = await _get_client()
            url = f"{API_BASE}{path}"
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (502, 503, 504):
                last_exc = e
                await asyncio.sleep(2**attempt)
                continue
            raise
        except httpx.ConnectError as e:
            last_exc = e
            await asyncio.sleep(2**attempt)
            continue
        except httpx.TimeoutException as e:
            last_exc = e
            await asyncio.sleep(2**attempt)
            continue
    raise ConnectionError(
        f"Cannot connect to {API_BASE} after {retries} retries — is the API server running?"
    ) from last_exc


async def fetch_candles(
    symbol: str,
    timeframe: str = "5min",
    limit: int = 200,
) -> tuple[list[dict[str, Any]], float | None]:
    path = f"/api/v1/predictions/history/{symbol.upper()}?timeframe={timeframe}&limit={limit}&_t={int(time.time())}"
    data = await fetch_json(path)
    candles = data.get("candles", [])
    for c in candles:
        c["time"] = str(c.get("time", ""))
        for k in ("open", "high", "low", "close", "volume"):
            v = c.get(k)
            c[k] = float(v) if v is not None else 0.0
    return candles, data.get("candle_data_age_seconds")


async def fetch_prediction(
    symbol: str,
    timeframe: str = "5min",
    pred_len: int = 12,
    sample_count: int = 2,
    force_refresh: bool = False,
    conviction_mode: bool = True,
) -> dict[str, Any] | None:
    path = (
        f"/api/v1/predictions/{symbol.upper()}"
        f"?timeframe={timeframe}&mode=VISUAL&pred_len={pred_len}"
        f"&sample_count={sample_count}"
        f"&force_refresh={'true' if force_refresh else 'false'}"
        f"&conviction_mode={'true' if conviction_mode else 'false'}"
    )
    try:
        return await fetch_json(path)
    except httpx.HTTPStatusError as e:
        body = None
        try:
            body = e.response.json()
        except Exception:
            pass
        if e.response.status_code == 422:
            return body or {"detail": "DQG validation failed (422)"}
        _logger.warning("fetch_prediction(%s): HTTP %s", symbol, e.response.status_code)
        return body
    except Exception as e:
        _logger.warning("fetch_prediction(%s): %s", symbol, e)
        return None


async def fetch_dqg(symbol: str, timeframe: str = "5min") -> dict[str, Any] | None:
    path = f"/api/v1/dqg/{symbol.upper()}?timeframe={timeframe}&mode=STANDARD"
    try:
        return await fetch_json(path)
    except Exception as e:
        _logger.warning("fetch_dqg(%s): %s", symbol, e)
        return None


_MARKET_CONTEXT_CACHE: dict[str, tuple[Any, float]] = {}
_MARKET_CACHE_TTL = 60.0
_NSE_BACKOFF_UNTIL: float = 0.0  # cooldown after NSE fetch failure


async def fetch_market_context() -> dict[str, Any]:
    now = time.time()
    cached = _MARKET_CONTEXT_CACHE.get("market")
    if cached and (now - cached[1]) < _MARKET_CACHE_TTL:
        return cached[0]

    global _NSE_BACKOFF_UNTIL
    result: dict[str, Any] = {
        "vix": None,
        "pcr": None,
        "max_pain": None,
        "iv_ce": None,
        "iv_pe": None,
        "fetched_at": now,
    }

    if now < _NSE_BACKOFF_UNTIL:
        _MARKET_CONTEXT_CACHE["market"] = (result, now)
        return result

    try:
        client = await _get_client()
        resp = await client.get(
            "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            records = data.get("records", {})
            und = _to_float(records.get("underlyingValue"))
            if und is not None:
                result["vix"] = round(und * 0.15, 2)
            oi_data = records.get("data", [])
            ce_oi = 0
            pe_oi = 0
            for item in oi_data:
                ce = item.get("CE", {})
                pe = item.get("PE", {})
                ce_oi += _to_int(ce.get("openInterest"), 0)
                pe_oi += _to_int(pe.get("openInterest"), 0)
                iv_ce = _to_float(ce.get("impliedVolatility"))
                if iv_ce is not None:
                    result["iv_ce"] = round(iv_ce * 100, 2)
                iv_pe = _to_float(pe.get("impliedVolatility"))
                if iv_pe is not None:
                    result["iv_pe"] = round(iv_pe * 100, 2)
            result["pcr"] = round(pe_oi / ce_oi, 2) if ce_oi > 0 else None

            oi_by_strike: dict[float, float] = {}
            for item in oi_data:
                ce = item.get("CE", {})
                pe = item.get("PE", {})
                strike = _to_float(item.get("strikePrice"))
                total_oi = _to_float(ce.get("openInterest"), 0) + _to_float(
                    pe.get("openInterest"), 0
                )
                if strike and total_oi > oi_by_strike.get(strike, 0):
                    oi_by_strike[strike] = total_oi
            if oi_by_strike:
                result["max_pain"] = round(max(oi_by_strike, key=oi_by_strike.get), 2)

        iv_resp = await client.get(
            "https://www.nseindia.com/api/volatility?index=INDIAVIX",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15.0,
        )
        if iv_resp.status_code == 200:
            iv_data = iv_resp.json()
            if isinstance(iv_data, dict):
                v = _to_float(iv_data.get("value", iv_data.get("vix")))
                if v is not None:
                    result["vix"] = round(v, 2)
            elif isinstance(iv_data, (int, float)):
                result["vix"] = round(float(iv_data), 2)
    except Exception as e:
        _logger.warning("fetch_market_context failed: %s", e)
        _NSE_BACKOFF_UNTIL = time.time() + 60

    _MARKET_CONTEXT_CACHE["market"] = (result, now)
    return result


_MULTI_TF_CACHE: dict[str, tuple[dict, float]] = {}
_MULTI_TF_TTL = 30.0


async def fetch_multi_timeframe(symbol: str) -> dict[str, Any]:
    now = time.time()
    key = f"mtf_{symbol}"
    cached = _MULTI_TF_CACHE.get(key)
    if cached and (now - cached[1]) < _MULTI_TF_TTL:
        return cached[0]

    result: dict[str, Any] = {
        "15m": {"rsi": None, "direction": "NEUT"},
        "1h": {"rsi": None, "direction": "NEUT"},
        "1d": {"rsi": None, "direction": "NEUT"},
    }

    async def _fetch_tf(tf: str, limit: int) -> tuple[str, dict]:
        try:
            candles, _ = await fetch_candles(symbol, timeframe=tf, limit=limit)
            if candles and len(candles) > 15:
                closes = [c["close"] for c in candles[-15:]]
                rsi = compute_rsi_from_closes(closes)
                direction = (
                    "BULL"
                    if closes[-1] > closes[0]
                    else "BEAR"
                    if closes[-1] < closes[0]
                    else "NEUT"
                )
                return tf, {"rsi": rsi, "direction": direction}
        except Exception as e:
            _logger.debug("fetch_multi_timeframe %s failed: %s", tf, e)
        return tf, {"rsi": None, "direction": "NEUT"}

    tfs = {"15m": 80, "1h": 60, "1d": 50}
    tasks = [_fetch_tf(tf, limit) for tf, limit in tfs.items()]
    for tf, data in await asyncio.gather(*tasks):
        result[tf] = data

    _MULTI_TF_CACHE[key] = (result, now)
    return result


async def _ws_cleanup(name: str) -> None:
    with _ws_state_lock:
        if name in _ws_closing:
            _ws_closing.discard(name)
            return
        _ws_connections.pop(name, None)
        _ws_listener_tasks.pop(name, None)
        _ws_reconnect_count.pop(name, None)
        _ws_connected.pop(name, None)


async def _ws_listen(
    name: str,
    url: str,
    callback: Callable,
    max_retries: int = 10,
) -> None:
    """Listen on a WebSocket and call callback(msg_dict) for each message.
    Reconnects with capped exponential backoff (max 60s) for up to 5 minutes
    before giving up."""
    retries = 0
    start_time = time.monotonic()
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                with _ws_state_lock:
                    if name in _ws_closing:
                        _ws_closing.discard(name)
                        break
                    _ws_connections[name] = ws
                    _ws_reconnect_count[name] = 0
                    _ws_connected[name] = True
                retries = 0
                while True:
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    try:
                        msg = json.loads(raw)
                        if asyncio.iscoroutinefunction(callback):
                            await callback(msg)
                        else:
                            callback(msg)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            break
        except Exception:
            retries += 1
            with _ws_state_lock:
                _ws_reconnect_count[name] = retries
                _ws_connected[name] = False
            if time.monotonic() - start_time > 300:
                break
            delay = min(2**retries, 60)
            await asyncio.sleep(delay)
    await _ws_cleanup(name)


def ws_is_connected(name: str) -> bool:
    with _ws_state_lock:
        return _ws_connected.get(name, False)


def get_ws_states() -> dict[str, bool]:
    with _ws_state_lock:
        return dict(_ws_connected)


def connect_ticks_ws(
    symbol: str,
    callback: Callable,
) -> None:
    """Connect to /ws/ticks/{symbol} — calls callback(msg_dict) per tick."""
    name = f"ticks:{symbol.upper()}"
    disconnect_ws(name)
    with _ws_state_lock:
        _ws_closing.discard(name)
    url = f"{WS_BASE}/ws/ticks/{symbol.upper()}"
    task = asyncio.create_task(_ws_listen(name, url, callback))
    with _ws_state_lock:
        _ws_listener_tasks[name] = task


def connect_predictions_ws(
    symbol: str,
    callback: Callable,
) -> None:
    """Connect to /ws/predictions/{symbol} — calls callback(msg_dict) per prediction push."""
    name = f"preds:{symbol.upper()}"
    disconnect_ws(name)
    with _ws_state_lock:
        _ws_closing.discard(name)
    url = f"{WS_BASE}/ws/predictions/{symbol.upper()}"
    task = asyncio.create_task(_ws_listen(name, url, callback))
    with _ws_state_lock:
        _ws_listener_tasks[name] = task


def disconnect_ws(name: str) -> None:
    with _ws_state_lock:
        _ws_closing.add(name)
        _ws_connected[name] = False
        task = _ws_listener_tasks.pop(name, None)
        if task and not task.done():
            task.cancel()
        conn = _ws_connections.pop(name, None)
        if conn and not conn.close_code:
            try:
                asyncio.get_running_loop()
                asyncio.ensure_future(conn.close())
            except RuntimeError:
                pass


def disconnect_symbol_ws(symbol: str) -> None:
    s = symbol.upper()
    disconnect_ws(f"ticks:{s}")
    disconnect_ws(f"preds:{s}")


def reconnect_symbol_ws(
    symbol: str,
    on_tick: Callable | None = None,
    on_prediction: Callable | None = None,
) -> None:
    disconnect_symbol_ws(symbol)
    if on_tick:
        connect_ticks_ws(symbol, on_tick)
    if on_prediction:
        connect_predictions_ws(symbol, on_prediction)


def disconnect_all_ws() -> None:
    for name in list(_ws_listener_tasks.keys()):
        disconnect_ws(name)


async def close_fetcher() -> None:
    disconnect_all_ws()
    global _client
    if _client:
        await _client.aclose()
        _client = None
