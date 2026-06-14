from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal

import numpy as np
import pandas as pd
import pytest

from scripts.seed_instruments import is_trading_day

IST = "Asia/Kolkata"


def _tf_minutes(timeframe: str) -> int:
    tf = timeframe.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def make_clean_nse_df(
    symbol: str,
    timeframe: str,
    days: int,
    start_date: date,
) -> pd.DataFrame:
    """Synthetic NSE OHLCV for market hours only, no holidays/weekends."""
    tf_min = _tf_minutes(timeframe)
    per_day = 375 // tf_min
    open_t = time(9, 15)

    rows: list[dict] = []
    d = start_date
    price = 100.0

    while len({r["time"].date() for r in rows}) < days:
        if not is_trading_day(d):
            d += timedelta(days=1)
            continue

        day_start = pd.Timestamp(datetime.combine(d, open_t), tz=IST)
        times = pd.date_range(day_start, periods=per_day, freq=f"{tf_min}min", tz=IST)

        for ts in times:
            # small random walk, always valid OHLCV
            delta = float(np.random.normal(0, 0.05))
            o = price
            c = max(0.01, price + delta)
            h = max(o, c) + 0.02
            lo = min(o, c) - 0.02
            v = 1000.0
            rows.append(
                {"time": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}
            )
            price = c

        d += timedelta(days=1)

    df = pd.DataFrame(rows).set_index("time")
    return df


def make_df_with_gap(
    df: pd.DataFrame, gap_start_time: datetime, gap_minutes: int
) -> pd.DataFrame:
    """Remove candles to create an intraday gap."""
    if df.empty:
        return df
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    else:
        idx = idx.tz_convert(IST)
    df = df.copy()
    df.index = idx

    start = (
        pd.Timestamp(gap_start_time, tz=IST)
        if gap_start_time.tzinfo is None
        else pd.Timestamp(gap_start_time).tz_convert(IST)
    )
    end = start + pd.Timedelta(minutes=gap_minutes)
    return df[(df.index < start) | (df.index > end)].copy()


def make_df_with_ohlcv_violation(
    df: pd.DataFrame,
    row_index: int,
    violation_type: Literal["high_below_close", "low_above_open", "negative_volume"],
) -> pd.DataFrame:
    """Inject an OHLCV violation at a row index."""
    out = df.copy()
    if row_index >= len(out):
        raise IndexError("row_index out of range")
    if violation_type == "high_below_close":
        out.iloc[row_index, out.columns.get_loc("high")] = (
            float(out.iloc[row_index]["close"]) - 1.0
        )
    elif violation_type == "low_above_open":
        out.iloc[row_index, out.columns.get_loc("low")] = (
            float(out.iloc[row_index]["open"]) + 1.0
        )
    elif violation_type == "negative_volume":
        out.iloc[row_index, out.columns.get_loc("volume")] = -1.0
    else:
        raise ValueError("unknown violation_type")
    return out


@pytest.fixture
def clean_df() -> pd.DataFrame:
    return make_clean_nse_df("SBIN", "1m", days=10, start_date=date(2025, 4, 1))
