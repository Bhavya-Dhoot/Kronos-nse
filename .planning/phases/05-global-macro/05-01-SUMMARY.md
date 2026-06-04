---
phase: "05-global-macro"
plan: "05-01"
subsystem: "variance"
tags:
  - collector
  - global-markets
  - yfinance
  - macro
dependency_graph:
  requires: [variance.base_collector, variance.schemas, yfinance]
  provides: [GlobalMarketsCollector]
  affects: [variance.collectors.__init__, config/base.yaml]
tech-stack:
  added: [yfinance]
  patterns: [async to_thread, weighted composite with inverse weight]
key-files:
  created:
    - variance/collectors/global_markets_collector.py
  modified:
    - variance/collectors/__init__.py
    - config/base.yaml
    - requirements_linux.txt
decisions:
  - "DXY weight set to -0.10 (inverse) vs other tickers all positive — strong USD is an NSE headwind"
  - "Failed tickers excluded with remaining weights renormalized via total_weight sum"
  - "Composite value clamped to [-1.0, 1.0] via score()"
  - "Each ticker fetched via asyncio.to_thread() for non-blocking I/O"
metrics:
  duration_minutes: 7
  completed_date: "2026-06-04"
---

# Phase 05 Global Macro — Plan 01: Build GlobalMarketsCollector Summary

**One-liner:** GlobalMarketsCollector polls 8 tickers (ES=F, NQ=F, YM=F, ^N225, ^HSI, 000001.SS, ^KS11, DX-Y.NYB) via yfinance every 300s and computes a weighted composite with DXY as an inverse-weight headwind indicator.

## Files Created

### `variance/collectors/global_markets_collector.py`

- **GlobalMarketsCollector(BaseVarianceCollector)**: polls `GLOBAL_TICKERS` dict (8 entries, DXY at -0.10) every 300s.
- `_compute_change_pct(ticker) -> float | None`: fetches 5d history via `yf.Ticker().history(period="5d")`, returns `(latest - prev) / prev * 100` or `None` on any failure (network, empty, NaN, zero prev_close).
- `fetch()`: iterates all tickers concurrently via `asyncio.to_thread(_compute_change_pct, ticker)`.
- `parse()`: computes weighted sum / total_weight (abs for negative weights), returns `ParseResult` with `raw_value`, direction, magnitude, and ticker-level details.
- `score()`: clamps `raw_value` to `[-1.0, 1.0]`.
- Failed tickers excluded from denominator — remaining weights renormalized.

### `variance/collectors/__init__.py`

- Added `from variance.collectors.global_markets_collector import GlobalMarketsCollector`
- Added `"GlobalMarketsCollector"` to `__all__`

### `config/base.yaml`

- Added `global_markets:` section under `variance:` with full ticker/weight mapping

### `requirements_linux.txt`

- Added `yfinance==1.4.1`

## Deviations from Plan

### [Rule 2 - Missing dependency] Added yfinance to requirements_linux.txt

- **Found during:** Task 5 verification
- **Issue:** `yfinance` module not installed in the virtual environment
- **Fix:** `pip install yfinance` and added `yfinance==1.4.1` to `requirements_linux.txt`
- **Files modified:** `requirements_linux.txt`
- **Commit:** 28344e2

## Verification

- Python syntax check: PASSED
- YAML config parse: PASSED
- Full import from `variance.collectors` via venv: PASSED
- `GlobalMarketsCollector` instantiation: PASSED (name=`global_markets`, interval=300)
- `__all__` export: PASSED

## Self-Check: PASSED

All files exist, syntax valid, imports work, commit hash 28344e2 recorded.
