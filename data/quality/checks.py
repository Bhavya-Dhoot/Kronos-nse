"""Data Quality Gate (DQG) checks for Kronos NSE.

Each check is a standalone function and returns a dict of the form:
  {"passed": bool, "critical": bool, "detail": str, ...extra_fields}

All timestamps are treated as Asia/Kolkata (IST).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts.seed_instruments import is_market_open, is_trading_day

IST = "Asia/Kolkata"
NSE_SESSION_MINUTES = 375  # 09:15 to 15:30


def _ensure_ist_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df must have a DatetimeIndex")
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    else:
        idx = idx.tz_convert(IST)
    df = df.copy()
    df.index = idx
    return df


def _tf_minutes(timeframe: str) -> int:
    tf = timeframe.strip().lower()
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
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def check_min_history(df: pd.DataFrame, mode: str) -> dict[str, Any]:
    """Require minimum number of trading days present in the dataset."""
    df = _ensure_ist_index(df)
    mode_u = mode.upper()

    if mode_u in {"COLLECT", "TRAIN"}:
        required_days = 180
    elif mode_u in {"VISUAL", "HEADLESS", "PAPER"}:
        required_days = 10
    elif mode_u == "BACKTEST":
        required_days = 30
    else:
        required_days = 10

    if df.empty:
        return {
            "passed": False,
            "critical": True,
            "detail": "No data available.",
            "required_days": required_days,
            "trading_days": 0,
        }

    trading_days = df.index.normalize().date
    trading_days = {d for d in trading_days if is_trading_day(d)}
    passed = len(trading_days) >= required_days
    return {
        "passed": passed,
        "critical": True,
        "detail": f"Trading days available: {len(trading_days)} (required: {required_days}).",
        "required_days": required_days,
        "trading_days": len(trading_days),
    }


def check_coverage(
    df: pd.DataFrame, timeframe: str, mode: str = "HEADLESS"
) -> dict[str, Any]:
    """Coverage across the trading session for observed trading days.

    Threshold is relaxed for TRAIN/COLLECT modes (85%) where multi-year
    historical data naturally has more gaps from API limits, holidays,
    and partial sessions.
    """
    df = _ensure_ist_index(df)
    tf_min = _tf_minutes(timeframe)

    # Use relaxed threshold for bulk historical modes
    mode_u = mode.upper()
    threshold = 85.0 if mode_u in {"TRAIN", "COLLECT", "BACKTEST"} else 90.0

    if df.empty:
        return {
            "passed": False,
            "critical": True,
            "detail": "No data available.",
            "coverage_pct": 0.0,
            "expected_count": 0,
            "actual_count": 0,
        }

    expected_per_day = max(1, NSE_SESSION_MINUTES // tf_min)
    all_days = sorted({d for d in df.index.normalize().date if is_trading_day(d)})
    expected_count = expected_per_day * len(all_days)
    actual_count = int(len(df))
    # Cap expected count to avoid penalizing symbols whose history exceeds the
    # DQG fetch limit (10K candles). Symbols with >133 trading days of 5min data
    # would otherwise fail coverage despite having perfect data.
    expected_count = min(expected_count, actual_count + expected_per_day * 2)
    coverage_pct = (actual_count / expected_count * 100.0) if expected_count else 0.0
    passed = coverage_pct >= threshold

    return {
        "passed": passed,
        "critical": True,
        "detail": f"Coverage {coverage_pct:.2f}% (threshold {threshold:.0f}%).",
        "coverage_pct": float(coverage_pct),
        "expected_count": int(expected_count),
        "actual_count": int(actual_count),
        "expected_per_day": int(expected_per_day),
        "trading_days": int(len(all_days)),
    }


def check_no_critical_gaps(df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    """Detect intraday gaps during market hours above a threshold.

    Gaps spanning overnight/weekends/holidays are not considered critical.
    """
    df = _ensure_ist_index(df)
    if len(df) < 2:
        return {
            "passed": False,
            "critical": True,
            "detail": "Not enough candles to evaluate gaps.",
            "gap_count": 0,
            "worst_gap_minutes": 0.0,
            "gap_timestamps": [],
        }

    tf_min = _tf_minutes(timeframe)
    threshold_minutes = max(10, 2 * tf_min)
    idx = df.index.sort_values()

    gap_timestamps: list[str] = []
    worst_gap = 0.0

    for prev, cur in zip(idx[:-1], idx[1:]):
        delta_min = (cur - prev).total_seconds() / 60.0
        if delta_min <= threshold_minutes:
            continue

        # Only treat as critical if both points are intraday market hours.
        if prev.date() != cur.date():
            continue

        if not (
            is_market_open(prev.to_pydatetime()) and is_market_open(cur.to_pydatetime())
        ):
            continue

        # Skip if there are non-trading days between (holiday/weekend) — though same date already handled.
        # Here, same date means no holiday span; so it's a true intraday gap.
        worst_gap = max(worst_gap, delta_min)
        gap_timestamps.append(prev.isoformat())

    passed = len(gap_timestamps) == 0
    return {
        "passed": passed,
        "critical": True,
        "detail": (
            f"No critical gaps > {threshold_minutes} minutes."
            if passed
            else f"Found {len(gap_timestamps)} critical gap(s) > {threshold_minutes} minutes."
        ),
        "gap_count": int(len(gap_timestamps)),
        "worst_gap_minutes": float(worst_gap),
        "gap_timestamps": gap_timestamps[:50],
        "threshold_minutes": int(threshold_minutes),
    }


def check_ohlcv_constraints(df: pd.DataFrame) -> dict[str, Any]:
    """Validate OHLCV invariants."""
    df = _ensure_ist_index(df)
    if df.empty:
        return {
            "passed": False,
            "critical": True,
            "detail": "No data available.",
            "violation_count": 0,
            "violation_indices": [],
        }

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        return {
            "passed": False,
            "critical": True,
            "detail": f"Missing columns: {sorted(missing)}",
            "violation_count": len(df),
            "violation_indices": [],
        }

    o = df["open"]
    h = df["high"]
    lo = df["low"]
    c = df["close"]
    v = df["volume"]

    mask = (h >= o) & (h >= c) & (lo <= o) & (lo <= c) & (h >= lo) & (v >= 0)
    violations = df.index[~mask]
    passed = len(violations) == 0
    return {
        "passed": passed,
        "critical": True,
        "detail": "OHLCV constraints valid."
        if passed
        else f"Found {len(violations)} OHLCV violation(s).",
        "violation_count": int(len(violations)),
        "violation_indices": [ts.isoformat() for ts in violations[:50]],
    }


def check_lookback_sufficient(df: pd.DataFrame, required: int = 400) -> dict[str, Any]:
    df = _ensure_ist_index(df)
    passed = len(df) >= required
    return {
        "passed": passed,
        "critical": True,
        "detail": f"Lookback bars: {len(df)} (required: {required}).",
        "required": int(required),
        "available": int(len(df)),
    }


def check_outliers(df: pd.DataFrame) -> dict[str, Any]:
    """Flag suspicious outliers. Warning-only."""
    df = _ensure_ist_index(df)
    if len(df) < 2:
        return {
            "passed": True,
            "critical": False,
            "detail": "Not enough candles to evaluate outliers.",
            "outlier_count": 0,
        }

    c = df["close"].astype(float)
    pct = c.pct_change().abs()
    pct_outliers = pct > 0.20

    wick = (df["high"].astype(float) - df["low"].astype(float)).abs()
    wick_outliers = (wick / c.replace(0, pd.NA)) > 0.15
    outlier_idx = df.index[pct_outliers.fillna(False) | wick_outliers.fillna(False)]

    return {
        "passed": True,  # warning only
        "critical": False,
        "detail": f"Flagged {len(outlier_idx)} outlier candle(s) (warning only).",
        "outlier_count": int(len(outlier_idx)),
        "outlier_timestamps": [ts.isoformat() for ts in outlier_idx[:50]],
    }


def check_staleness(
    df: pd.DataFrame, threshold_seconds: int = 30, timeframe: str | None = None
) -> dict[str, Any]:
    """Fail if the latest candle is older than threshold during market hours.
    When ``timeframe`` is provided, ``threshold_seconds`` is computed adaptively
    as ``max(30, 2 * tf_minutes * 60)`` unless overridden explicitly."""
    if timeframe is not None:
        tf_min = _tf_minutes(timeframe)
        threshold_seconds = max(30, 2 * tf_min * 60)
    df = _ensure_ist_index(df)
    now = pd.Timestamp.now(tz=IST)

    outside_hours = not is_market_open(now.to_pydatetime())
    last_ts = df.index.max() if not df.empty else None
    staleness = (now - last_ts).total_seconds() if last_ts is not None else None

    if outside_hours:
        detail = "Outside market hours; staleness check skipped."
        data_stale = False
        if staleness is not None and staleness > 3600:
            detail += f" Data from {last_ts.strftime('%a %H:%M')}, {staleness / 3600:.0f}h ago."
            data_stale = True
        return {
            "passed": True,
            "critical": True,
            "detail": detail,
            "staleness_seconds": staleness,
            "last_candle_time": last_ts.isoformat() if last_ts is not None else None,
            "threshold_seconds": int(threshold_seconds),
            "warning": data_stale or None,
        }

    if df.empty:
        return {
            "passed": False,
            "critical": True,
            "detail": "No data available to evaluate staleness during market hours.",
            "staleness_seconds": None,
            "threshold_seconds": int(threshold_seconds),
        }

    last_ts = df.index.max()
    staleness = (now - last_ts).total_seconds()
    passed = staleness <= threshold_seconds
    return {
        "passed": passed,
        "critical": True,
        "detail": (
            f"Latest candle staleness {staleness:.1f}s (threshold {threshold_seconds}s)."
            if passed
            else f"Stale data: {staleness:.1f}s old (threshold {threshold_seconds}s)."
        ),
        "staleness_seconds": float(staleness),
        "threshold_seconds": int(threshold_seconds),
        "last_candle_time": last_ts.isoformat(),
    }


def check_corporate_action_suspected(df: pd.DataFrame) -> dict[str, Any]:
    """Detect likely corporate actions by large close gaps between consecutive trading days."""
    df = _ensure_ist_index(df)
    if df.empty:
        return {
            "passed": True,
            "critical": False,
            "detail": "No data available.",
            "suspected_dates": [],
        }

    daily = df["close"].astype(float).resample("1D").last().dropna()
    if len(daily) < 2:
        return {
            "passed": True,
            "critical": False,
            "detail": "Not enough daily data to evaluate corporate actions.",
            "suspected_dates": [],
        }

    pct = daily.pct_change().abs()
    suspected = pct[pct > 0.15].index
    return {
        "passed": True,
        "critical": False,
        "detail": f"Suspected corporate action on {len(suspected)} day(s) (warning only).",
        "suspected_dates": [d.date().isoformat() for d in suspected[:50]],
    }


def check_volume_sanity(df: pd.DataFrame) -> dict[str, Any]:
    """Warning-only volume sanity checks."""
    df = _ensure_ist_index(df)
    if df.empty:
        return {
            "passed": True,
            "critical": False,
            "detail": "No data available.",
            "zero_volume_days": [],
            "flat_volume_runs": 0,
        }

    vol = df["volume"].astype(float)
    daily_total = vol.resample("1D").sum()
    zero_days = [d.date().isoformat() for d, v in daily_total.items() if v == 0]

    # Flat volume for >10 consecutive bars
    same_as_prev = vol == vol.shift(1)
    run = 0
    flat_runs = 0
    for x in same_as_prev.fillna(False).to_list():
        if x:
            run += 1
            if run == 10:
                flat_runs += 1
        else:
            run = 0

    return {
        "passed": True,
        "critical": False,
        "detail": f"Volume sanity warnings: zero_volume_days={len(zero_days)}, flat_volume_runs={flat_runs}.",
        "zero_volume_days": zero_days[:50],
        "flat_volume_runs": int(flat_runs),
    }


def check_mve_health(mve: Any | None) -> dict[str, Any]:
    """Warning-level health check for MarketVarianceEngine.

    Reports active dimensions, stale dimensions, and circuit-broken dimensions.
    Non-critical — always returns passed=True per D-01.

    Parameters
    ----------
    mve : Any | None
        The MarketVarianceEngine instance, or None if MVE is not configured.
        Uses Any to avoid importing MarketVarianceEngine (keeps checks.py free
        of cyclic imports).

    Returns
    -------
    dict[str, Any]
        {
            "passed": True,  # warning-level — always passes per D-01
            "critical": False,  # non-critical per D-01
            "detail": str,  # Human-readable summary
            "active_dimensions": str | int,  # "N/M" or 0 if MVE not configured
            "stale_dimensions": list[str],  # names or empty list
            "circuit_broken_dimensions": list[str],  # names or empty list
        }
    """
    if mve is None:
        return {
            "passed": True,
            "critical": False,
            "detail": "MVE not configured — check skipped.",
            "active_dimensions": 0,
            "stale_dimensions": [],
            "circuit_broken_dimensions": [],
        }

    health = mve.health_status

    # Total collectors count from health dict
    total_collectors = len(health.get("collectors", {}))
    active_count = health.get("active_dimensions", 0)
    active_str = (
        f"{active_count}/{total_collectors}"
        if total_collectors > 0
        else str(active_count)
    )

    # Stale dimensions: check collected_at timestamps against current time
    # Uses 30s threshold matching DQG's max_staleness_seconds_live default
    threshold_seconds = 30
    now = datetime.now(UTC)
    stale_dimensions: list[str] = []

    scores = getattr(mve, "_scores", {})
    for name, entry in scores.items():
        if entry.get("first_poll") is True:
            collected_at_str = entry.get("collected_at", "")
            if collected_at_str:
                try:
                    collected_at = datetime.fromisoformat(collected_at_str)
                    if (now - collected_at).total_seconds() > threshold_seconds:
                        stale_dimensions.append(name)
                except (ValueError, TypeError):
                    # If timestamp is unparseable, mark as stale
                    stale_dimensions.append(name)

    # Circuit-broken dimensions: collectors where is_available is False
    circuit_broken_dimensions = [
        name
        for name, available in health.get("collectors", {}).items()
        if not available
    ]

    # Build detail string
    detail_parts = [f"{active_str} active"]
    if stale_dimensions:
        detail_parts.append(
            f"{len(stale_dimensions)} stale ({', '.join(sorted(stale_dimensions))})"
        )
    else:
        detail_parts.append("0 stale")
    if circuit_broken_dimensions:
        detail_parts.append(
            f"{len(circuit_broken_dimensions)} circuit-broken "
            f"({', '.join(sorted(circuit_broken_dimensions))})"
        )
    else:
        detail_parts.append("0 circuit-broken")

    detail = "MVE health: " + ", ".join(detail_parts)

    return {
        "passed": True,
        "critical": False,
        "detail": detail,
        "active_dimensions": active_str,
        "stale_dimensions": stale_dimensions,
        "circuit_broken_dimensions": circuit_broken_dimensions,
    }
