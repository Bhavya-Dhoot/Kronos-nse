---
phase: 09-dqg-system-test
plan: 04
subsystem: "MVE Backtesting"
tags: ["backtest", "MVE", "accuracy", "comparison", "metrics"]
dependency-graph:
  requires: ["variance/modifier.py", "model/factory.py", "backtest/runner.py"]
  provides: ["MVE impact quantification"]
  affects: ["System integration testing"]
tech-stack:
  added: []
  patterns: ["Standalone async CLI script using build_inference_context()"]
key-files:
  created: ["scripts/backtest_mve.py"]
  modified: []
decisions: ["D-18: Single backtest run — get predictions once, then compare modified vs unmodified", "D-19: Metrics: MAE of pred_close (primary), directional accuracy, average confidence", "D-20: Three states: Unmodified, Modified with MVE, Difference", "D-21: Symbols and timeframes from existing backtest config", "D-22: Output: console table + JSON file in backtest output directory"]
metrics:
  duration: "5 min"
  completed-date: "2026-06-05"
---

# Phase 9 Plan 4: MVE Backtesting Summary

## One-Liner
Standalone CLI backtesting script (`scripts/backtest_mve.py`) that runs a single prediction pass via `build_inference_context()`, then compares modified vs unmodified results by applying `PredictionModifier.modify_post_inference()` with a `_MockMVE` injecting a fixed moderate-bearish MVS dict (composite=-0.3, VIX=20).

## What was built

| File | Description |
|------|-------------|
| `scripts/backtest_mve.py` | CLI script with async runner, three-state comparison (Unmodified/Modified/Difference), console table + JSON output |

### Key components
- **`compute_mae(actual, predicted)`** — Mean Absolute Error between actual and predicted close values
- **`compute_directional_accuracy(actual, predicted)`** — Fraction of bars where price direction matches
- **`run_backtest(config_path, output_dir, max_symbols)`** — Core async runner: loads config, builds inference context, iterates symbols, computes both states
- **`_MockMVE(mvs_dict)`** — Minimal MVE mock with `is_ready=True` and fixed `last_mvs` dict for deterministic comparison
- **`_MockMVE.last_mvs`** — Property returning the injected MVS dict, consumed by `PredictionModifier.modify_post_inference()`
- **`_print_summary(summary)`** — Formatted console table per D-22
- **`main()`** — CLI entrypoint with `--config`, `--output-dir`, `--max-symbols`, `--verbose` args

## Tasks Executed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create MVE backtesting script | `d3a41f8` | `scripts/backtest_mve.py` |
| 2 | Verify script imports and structure | _(no code change)_ | — |

## Verification Results

All structure validations passed:
- ✅ Python syntax valid (AST parse)
- ✅ `_MockMVE` class: `is_ready=True`, `last_mvs` property returns provided dict
- ✅ `compute_mae()`: returns float for valid inputs, `None` for empty inputs
- ✅ `compute_directional_accuracy()`: returns `0.0–1.0` range for valid inputs, `None` for insufficient data

## Success Criteria

- [x] `scripts/backtest_mve.py` created with CLI argparse (`--config`, `--output-dir`, `--max-symbols`, `--verbose`)
- [x] `_MockMVE` helper provides `is_ready=True` and `last_mvs` property with fixed MVS dict
- [x] `compute_mae()` and `compute_directional_accuracy()` metrics functions
- [x] Script compares 3 states: Unmodified, Modified, Difference per D-20
- [x] Console summary table printed with MAE, directional accuracy, confidence per D-22
- [x] JSON output written to `backtest/output/mve_backtest_results.json`
- [x] All decisions D-18 through D-22 implemented

## Decisions Applied

| ID | Decision | Implementation |
|----|----------|---------------|
| D-18 | Single prediction pass, compare by applying modifier | `run_backtest()` calls `ctx.engine.predict()` once, passes result to `PredictionModifier(modifier_with_mve).modify_post_inference()` |
| D-19 | Metrics: MAE primary, directional accuracy, avg confidence | Three metric outputs per state in summary |
| D-20 | Three states: Unmodified, Modified, Difference | `symbol_result` dict with `unmodified`, `modified`, `difference` keys |
| D-21 | Symbols/timeframes from existing backtest config | Reads `backtest` section from YAML config |
| D-22 | Output: console table + JSON file | `_print_summary()` table + `mve_backtest_results.json` |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new threat flags introduced — the script runs read-only inference via existing `build_inference_context()` infrastructure. CLI args (`--config`, `--output-dir`) are accepted with `accept` disposition per T-09-11/T-09-12.

## Known Stubs

None.

## Self-Check: PASSED

- [x] `scripts/backtest_mve.py` exists (425 lines)
- [x] Commit `d3a41f8` exists in git log
- [x] Syntax verified via AST parse
- [x] `_MockMVE` class verified independently
- [x] Metric functions verified independently
