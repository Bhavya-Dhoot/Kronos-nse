---
phase: 05-global-macro
plan: 02
subsystem: variance
tags: [macro, yfinance, collector, all-inverse]
dependency-graph:
  requires: [05-01 (GlobalMarketsCollector pattern)]
  provides: [MacroCollector for MarketVarianceEngine]
  affects: [variance/score.py, variance/orchestrator.py]
tech-stack:
  added: [yfinance (used)]
  patterns: [BaseVarianceCollector subclass, all-inverse scoring]
key-files:
  created:
    - variance/collectors/macro_collector.py
  modified:
    - variance/collectors/__init__.py
    - config/base.yaml
metrics:
  duration: 2 min
  completed: 2026-06-04
  tasks: 3
  files_changed: 3
  commit_count: 1
---

# Phase 05 Plan 02: Build MacroCollector (4 tickers via yfinance, all-inverse scoring)

Implemented MacroCollector — polls 4 macro tickers (USD/INR, Brent Crude, Gold, US 10Y) via yfinance every 300s with all-inverse scoring per MAC-02: rising macro = bearish for India.

## Key Decisions Made

1. **All-inverse scoring in score() not parse()** — The inversion happens last in the score() method (`max(-1.0, min(1.0, -weighted_avg))`), keeping the parse() raw_value as the pre-inversion weighted average for transparency. The `raw_composite` field in detail exposes the pre-inversion value.
2. **Direct float() conversion (no _to_float helper)** — Followed the exact same pattern as GlobalMarketsCollector's `_compute_change_pct`, which uses direct `float()` calls with try/except rather than a separate `_to_float` helper. This keeps the two modules consistent.
3. **Module-level MACRO_TICKERS (no self._tickers copy)** — The module constant is directly referenced in fetch() and parse() rather than copied to `self._tickers`. The dict is effectively immutable at runtime, so no copy is needed.

## Tasks Executed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1-4 | Create MacroCollector, update __init__, update config | d11aabd | macro_collector.py, __init__.py, base.yaml |
| 5 | Verify syntax, exports, config | d11aabd | — |

## Deviations from Plan

None — plan executed as written with only minor non-functional adjustments (inlined float conversions matching GlobalMarketsCollector pattern, no _to_float helper since it's unused in the reference implementation).

### Auto-fixed Issues

None — no bugs, missing critical functionality, or blocking issues encountered.

## Verification Results

```
SYNTAX OK                                          # ast.parse on macro_collector.py
EXPORTED                                           # MacroCollector in __init__.py
Config macro section with 4 tickers                # base.yaml has macro: tickers: block
NAME=macro, INTERVAL=300, TICKERS=4               # Import from package works
__all__ export: NAME=macro, INTERVAL=300           # from variance.collectors import MacroCollector works
```

## Commits

- `d11aabd`: feat(05-global-macro): implement MacroCollector (4 tickers via yfinance, all-inverse scoring)

## Self-Check: PASSED

All verification commands produce expected output. Files exist, imports work, config is correct.

## Threat Surface Scan

No new threat surface detected beyond what the plan's threat model covers:
- T-05-05 (Spoofing): Yahoo Finance public data — accepted risk
- T-05-06 (Information disclosure): Public market data only — mitigated
- T-05-07 (Denial of service): 4 tickers / 300s — well within rate limits
- T-05-08 (Tampering): NaN/Inf handled via float conversion try/except
