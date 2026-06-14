"""Key level computation — pivot points, VWAP, PDH/PDL, regime detection."""

from __future__ import annotations

import math
from typing import Any

REGIME_ATR_VOLATILE_PCT = 1.5
REGIME_ATR_RANGING_PCT = 0.8
REGIME_DIRECTION_STRONG = 6
REGIME_DIRECTION_MODERATE = 3
REGIME_DIRECTION_RANGING = 4


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _cfloat(v: Any, default: float = 0.0) -> float:
    return _to_float(v, default)


def compute_pivots(candles: list[dict]) -> dict[str, float]:
    if len(candles) < 2:
        return {}
    prev = candles[-2]
    h_val = _cfloat(prev.get("high"))
    l_val = _cfloat(prev.get("low"))
    c_val = _cfloat(prev.get("close"))
    p_val = (h_val + l_val + c_val) / 3.0
    if p_val == 0:
        return {}
    r = h_val - l_val
    return {
        "R3": round(p_val + 2 * r, 2),
        "R2": round(p_val + r, 2),
        "R1": round(2 * p_val - l_val, 2),
        "PP": round(p_val, 2),
        "S1": round(2 * p_val - h_val, 2),
        "S2": round(p_val - r, 2),
        "S3": round(p_val - 2 * r, 2),
    }


def compute_vwap(candles: list[dict]) -> float | None:
    if not candles:
        return None
    daily_groups: dict[str, list[dict]] = {}
    for c in candles:
        t = str(c.get("time", ""))
        date_key = t[:10]
        if date_key not in daily_groups:
            daily_groups[date_key] = []
        daily_groups[date_key].append(c)
    latest_date = max(daily_groups.keys())
    day_candles = daily_groups[latest_date]
    vol_sum = 0.0
    pv_sum = 0.0
    for c in day_candles:
        tp = (
            _cfloat(c.get("high")) + _cfloat(c.get("low")) + _cfloat(c.get("close"))
        ) / 3.0
        v = _cfloat(c.get("volume"))
        if v > 0:
            pv_sum += tp * v
            vol_sum += v
    return round(pv_sum / vol_sum, 2) if vol_sum > 0 else None


def compute_prior_day_hl(candles: list[dict]) -> dict[str, float]:
    if len(candles) < 2:
        return {}
    prev = candles[-2]
    return {"PDH": _cfloat(prev.get("high")), "PDL": _cfloat(prev.get("low"))}


def compute_key_levels(candles: list[dict]) -> dict[str, float]:
    levels = {}
    pivots = compute_pivots(candles)
    levels.update(pivots)
    vwap = compute_vwap(candles)
    if vwap is not None:
        levels["VWAP"] = vwap
    pd = compute_prior_day_hl(candles)
    levels.update(pd)
    poc = compute_volume_profile_poc(candles)
    if poc is not None:
        levels["POC"] = poc
    now = _cfloat(candles[-1].get("close")) if candles else 0
    levels["NOW"] = round(now, 2)
    return levels


def classify_regime(
    candles: list[dict],
    pred_close: list[float] | None = None,
    ltp: float | None = None,
) -> dict:
    if len(candles) < 20:
        return {
            "regime": "RANGING",
            "label": "─ RANGING",
            "color": "bold yellow",
            "adx": 0,
            "bias": 50,
        }

    recent = list(candles[-20:])
    if ltp is not None and len(recent) >= 2:
        recent[-1] = dict(recent[-1], close=ltp)

    atr_sum = 0.0
    direction = 0
    bull_count = 0
    closes = []
    for i in range(len(recent)):
        c = recent[i]
        close = _cfloat(c.get("close"))
        open_p = _cfloat(c.get("open"))
        high = _cfloat(c.get("high"))
        low = _cfloat(c.get("low"))
        closes.append(close)
        if i > 0:
            atr_sum += abs(high - low)
            direction += 1 if close > open_p else -1
            if close > open_p:
                bull_count += 1

    total = len(recent)
    atr = atr_sum / (total - 1) if total > 1 else 0
    avg_price = sum(closes) / total if closes else 0
    atr_pct = (atr / avg_price) * 100 if avg_price else 0
    bull_pct = (bull_count / max(total, 1)) * 100

    pred_bias = 0
    if pred_close and len(pred_close) >= 3:
        pred_bias = 1 if pred_close[-1] > pred_close[0] else -1

    if atr_pct > REGIME_ATR_VOLATILE_PCT:
        regime = "VOLATILE"
        label = "⚡ VOLATILE"
        color = "bold yellow"
    elif abs(direction) < REGIME_DIRECTION_RANGING and atr_pct < REGIME_ATR_RANGING_PCT:
        regime = "RANGING"
        label = "─ RANGING"
        color = "bold yellow"
    elif direction > REGIME_DIRECTION_STRONG or (
        direction > REGIME_DIRECTION_MODERATE and pred_bias > 0
    ):
        regime = "TRENDING_UP"
        label = "↑ TRENDING"
        color = "bold green"
    elif direction < -REGIME_DIRECTION_STRONG or (
        direction < -REGIME_DIRECTION_MODERATE and pred_bias < 0
    ):
        regime = "TRENDING_DOWN"
        label = "↓ TRENDING"
        color = "bold #ff2d5b"
    else:
        regime = "RECOVERY"
        label = "↗ RECOVERY"
        color = "bold green"

    direction_strength = min(100, round(abs(direction) / total * 200, 1))

    return {
        "regime": regime,
        "label": label,
        "color": color,
        "direction_strength": direction_strength,
        "bias": round(bull_pct),
        "atr_pct": round(atr_pct, 2),
    }


def compute_rsi(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    closes = [_cfloat(c.get("close")) for c in candles[-(period + 1) :]]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def compute_rsi_from_closes(closes: list[float], period: int = 14) -> float:
    """RSI from pre-extracted close prices (used by fetcher)."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return round(100 - 100 / (1 + rs), 1)


def compute_macd(candles: list[dict]) -> dict:
    closes = [_cfloat(c.get("close")) for c in candles]
    if len(closes) < 34:
        return {"macd": 0, "signal": 0, "histogram": 0}

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    macd_line_values = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    macd_line = macd_line_values[-1] if macd_line_values else 0

    signal_values = _ema(macd_line_values, 9)
    signal_line = signal_values[-1] if signal_values else 0
    hist = macd_line - signal_line

    return {
        "macd": round(macd_line, 2),
        "signal": round(signal_line, 2),
        "histogram": round(hist, 2),
    }


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute_atr(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = _cfloat(candles[i].get("high"))
        lo = _cfloat(candles[i].get("low"))
        p_c = _cfloat(candles[i - 1].get("close"))
        tr = max(h - lo, abs(h - p_c), abs(lo - p_c))
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 2)


def compute_bollinger(candles: list[dict], period: int = 20) -> dict:
    closes = [_cfloat(c.get("close")) for c in candles]
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "width": 0, "state": "N/A"}

    recent = closes[-period:]
    mean = sum(recent) / period
    variance = max(0, sum((x - mean) ** 2 for x in recent) / (period - 1))
    std = math.sqrt(variance)
    upper = mean + 2 * std
    lower = mean - 2 * std
    width = (upper - lower) / mean * 100 if mean else 0

    last = closes[-1]
    hist_widths = []
    n_full = len(closes) - period + 1
    if n_full > 1:
        w_sum = sum(closes[:period])
        w_sum_sq = sum(x * x for x in closes[:period])
        for i in range(n_full):
            m = w_sum / period
            variance = max(0, (w_sum_sq - w_sum * w_sum / period) / (period - 1))
            s = math.sqrt(variance)
            w = (4 * s) / m * 100 if m else 0
            hist_widths.append(w)
            if i + period < len(closes):
                w_sum = w_sum - closes[i] + closes[i + period]
                w_sum_sq = (
                    w_sum_sq
                    - closes[i] * closes[i]
                    + closes[i + period] * closes[i + period]
                )

    avg_width = sum(hist_widths) / len(hist_widths) if hist_widths else width

    if last > upper:
        state = "UPPER"
    elif last < lower:
        state = "LOWER"
    elif width < avg_width * 0.7:
        state = "SQUEEZE"
    else:
        state = "EXPANDING"

    return {
        "upper": round(upper, 2),
        "middle": round(mean, 2),
        "lower": round(lower, 2),
        "width": round(width, 2),
        "state": state,
    }


def compute_volume_ratio(candles: list[dict], period: int = 20) -> float | None:
    """Volume ratio: current candle volume / average volume over period."""
    if len(candles) < 2:
        return None
    vols = (
        [_cfloat(c.get("volume")) for c in candles[-period:]]
        if len(candles) >= period
        else [_cfloat(c.get("volume")) for c in candles]
    )
    if not vols:
        return None
    avg_vol = sum(vols) / len(vols)
    if avg_vol < 1e-9:
        return None
    current = _cfloat(candles[-1].get("volume"))
    return round(current / avg_vol, 2)


def compute_obv(candles: list[dict]) -> dict:
    """On-Balance Volume — returns dict with raw value and direction (up/down/flat)."""
    if len(candles) < 2:
        return {"value": 0.0, "direction": "FLAT"}
    obv = 0.0
    history: list[float] = []
    for i in range(1, len(candles)):
        prev_c = _cfloat(candles[i - 1].get("close"))
        cur_c = _cfloat(candles[i].get("close"))
        cur_v = _cfloat(candles[i].get("volume"))
        if cur_c > prev_c:
            obv += cur_v
        elif cur_c < prev_c:
            obv -= cur_v
        if i >= len(candles) - 5:
            history.append(obv)
    direction = "FLAT"
    if len(history) >= 2:
        recent_trend = history[-1] - history[0]
        if recent_trend > 0:
            direction = "UP"
        elif recent_trend < 0:
            direction = "DOWN"
    return {"value": round(obv, 0), "direction": direction}


def compute_volume_profile_poc(candles: list[dict], n_bins: int = 10) -> float | None:
    """Volume Point of Control — price level with highest traded volume."""
    if len(candles) < 2:
        return None
    highs = [_cfloat(c.get("high")) for c in candles]
    lows = [_cfloat(c.get("low")) for c in candles]
    vols = [_cfloat(c.get("volume")) for c in candles]
    if not highs or not lows:
        return None
    min_px = min(lows)
    max_px = max(highs)
    if max_px <= min_px:
        return None
    bin_w = (max_px - min_px) / n_bins
    bins: list[float] = [0.0] * n_bins
    for i in range(len(candles)):
        h = highs[i]
        lo = lows[i]
        v = vols[i]
        if bin_w <= 0 or h <= lo:
            continue
        start_idx = max(0, min(n_bins - 1, int((lo - min_px) / bin_w)))
        end_idx = max(0, min(n_bins - 1, int((h - min_px) / bin_w)))
        if start_idx == end_idx:
            bins[start_idx] += v
        else:
            n_span = end_idx - start_idx + 1
            per_bin = v / n_span
            for bi in range(start_idx, end_idx + 1):
                bins[bi] += per_bin
    max_vol = max(bins)
    max_indices = [i for i, v in enumerate(bins) if v == max_vol]
    poc_idx = max_indices[len(max_indices) // 2]
    poc_px = min_px + (poc_idx + 0.5) * bin_w
    return round(poc_px, 2)
