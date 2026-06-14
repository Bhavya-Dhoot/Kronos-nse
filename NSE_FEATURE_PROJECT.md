# NSE Feature Project (Kronos + LightGBM Development Loop)

This project implements a production-grade NSE 5-minute feature stack and a fast LightGBM baseline loop.

## What was implemented

### 1) Feature engineering (`training/nse_feature_project.py`)

- **Tier 1 market context**
  - `nifty_ret_1`, `nifty_mom_5/10/20`
  - `banknifty_ret_1`, `banknifty_mom_5`
  - `india_vix_level`, `india_vix_change` (when available in DB)
  - `gift_nifty_open_premium_pct` placeholder hook
  - sector momentum (`sector_ret_1`, `sector_mom_5`) with index-first, basket fallback

- **Tier 2 NSE session timing**
  - `bars_since_open`, `bars_to_close`
  - `is_first_30min`, `is_last_30min`
  - `is_weekly_expiry`, `is_monthly_expiry`
  - `days_to_weekly_expiry`, `days_to_monthly_expiry`

- **Tier 3 VWAP microstructure**
  - `session_vwap`, `vwap_dev_pct`, `price_above_vwap`
  - `vwap_slope_5`, `vwap_slope_10`

- **Tier 4 relative volume**
  - `vol_ratio_20`, `vol_zscore_20`
  - `vol_tod_ratio` (same-time-of-day normalization)

- **Tier 5 volatility regime**
  - `atr14_pct`, `realized_vol_20`
  - `high_vol_regime`, `low_vol_regime`, `vol_regime_code`

- **Tier 6 gap + candle geometry + OHLCV microstructure**
  - `gap_abs`, `gap_pct`, `gap_up`, `intraday_ret_from_open`
  - `body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`, `close_location`, `range_expansion_20`
  - `order_flow_proxy_10`, `absorption_proxy`, `liquidity_shift_proxy`

### 2) Target formulation

For each horizon in `(6, 12, 24, 60)`:

- `target_logret_h{h}`
- `target_voladj_h{h}` (log-return normalized by realized vol)
- `target_dir_h{h}` (binary direction)

### 3) Fast model loop

`NSELightGBMTrainer` trains:

- regression head on volatility-adjusted return
- binary direction head
- quantile heads (`q10/q50/q90`) for uncertainty

Metrics reported:

- directional accuracy
- rank IC (cross-sectional Spearman by timestamp)
- MAE (vol-adjusted target)
- confidence score from quantile spread

### 4) End-to-end runner

- Script: `scripts/run_nse_feature_project.py`
- Output artifacts:
  - `reports/nse_feature_project/nse_feature_table.parquet`
  - `reports/nse_feature_project/nse_lightgbm_report.json`

---

## Install requirements

```bash
pip install -e .
```

If needed explicitly:

```bash
pip install lightgbm
```

---

## Run command (primary)

```bash
python scripts/run_nse_feature_project.py --years 5 --timeframe 5min --lookback 225 --horizons 6 12 24 60 --primary-horizon 12 --output-dir ./reports/nse_feature_project
```

---

## Quality gate

The runner prints:

- `Gate: PASS (directional_accuracy >= 0.54)`
- or `Gate: FAIL (directional_accuracy < 0.54)`

---

## Recommended workflow with Kronos

1. Run this LightGBM pipeline first to validate feature usefulness quickly.
2. Keep only positively contributing features (from top feature importance + metrics).
3. Feed the validated feature ideas into your heavier Kronos fine-tuning experiments on A4000.
4. Use this baseline as a regression test before promoting Kronos models.
