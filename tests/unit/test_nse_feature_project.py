from __future__ import annotations

import numpy as np
import pandas as pd

from training.nse_feature_project import NSEFeatureConfig, NSEFeatureEngineer


def _make_intraday_df(start: str, periods: int = 300) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="5min", tz="Asia/Kolkata")
    base = np.linspace(100, 110, periods)
    return pd.DataFrame(
        {
            "open": base - 0.2,
            "high": base + 0.4,
            "low": base - 0.5,
            "close": base,
            "volume": np.linspace(1000, 5000, periods),
        },
        index=idx,
    )


def test_build_feature_table_has_expected_columns():
    engineer = NSEFeatureEngineer(
        NSEFeatureConfig(horizons=(6, 12), min_rows_per_symbol=50)
    )

    candles = {
        "RELIANCE": _make_intraday_df("2025-01-01 09:15", periods=500),
        "TCS": _make_intraday_df("2025-01-01 09:15", periods=500),
    }
    context = {
        "NIFTY50": _make_intraday_df("2025-01-01 09:15", periods=500),
        "BANKNIFTY": _make_intraday_df("2025-01-01 09:15", periods=500),
    }

    out = engineer.build_feature_table(
        candles_by_symbol=candles, context_candles=context
    )

    assert not out.empty
    required = {
        "nifty_ret_1",
        "banknifty_ret_1",
        "bars_since_open",
        "bars_to_close",
        "vwap_dev_pct",
        "vol_ratio_20",
        "realized_vol_20",
        "gap_pct",
        "body_ratio",
        "target_voladj_h6",
        "target_dir_h12",
    }
    assert required.issubset(set(out.columns))


def test_targets_present_for_all_horizons():
    engineer = NSEFeatureEngineer(
        NSEFeatureConfig(horizons=(6, 12, 24), min_rows_per_symbol=50)
    )

    candles = {"RELIANCE": _make_intraday_df("2025-01-01 09:15", periods=600)}
    out = engineer.build_feature_table(candles_by_symbol=candles, context_candles={})

    for h in (6, 12, 24):
        assert f"target_logret_h{h}" in out.columns
        assert f"target_voladj_h{h}" in out.columns
        assert f"target_dir_h{h}" in out.columns
