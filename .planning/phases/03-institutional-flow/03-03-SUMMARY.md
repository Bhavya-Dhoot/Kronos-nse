---
phase: 03-institutional-flow
plan: 03-03
subsystem: institutional-flow
tags: [oi, futures, institutional-flow, collector, angel-one]
dependency_graph:
  requires: [03-01-angel-client]
  provides: [oi-collector, get-futures-oi]
  affects: [mve-aggregator, market-variance-score]
tech-stack:
  added:
    - "AngelOneClient.get_futures_oi() — ltpData for NFO futures OI"
  patterns:
    - "asyncio.to_thread() for blocking Smart API calls"
    - "Redis baseline tracking via poll_with_baseline()"
key-files:
  created:
    - "variance/collectors/oi_collector.py"
    - "variance/tests/test_oi_collector.py"
  modified:
    - "data/collector/angel_client.py"
    - "variance/collectors/__init__.py"
metrics:
  duration: 11m
  completed_at: "2026-06-04T05:53:23Z"
  tests: 22
  tests_passed: 22
---

# Phase 3 Plan 3: Build OICollector + AngelOneClient.get_futures_oi() + tests

**One-liner:** Futures OI polling collector (OICollector) polling NIFTY/BANKNIFTY every 300s via AngelOneClient with Redis-backed baseline tracking for OI change computation, scoring clamped to ±0.3 per D-10.

## Tasks Executed

### Task 1 — Context gathering
Read all referenced files: `_angel.py`, `angel_client.py`, `base_collector.py`, `schemas.py`, `fii_dii_collector.py`, `redis_cache.py`, `__init__.py`. No code changes.

### Task 2 — `get_futures_oi()` on AngelOneClient
- Added `get_futures_oi(symbol)` — calls `SmartConnect.ltpData()` on NFO exchange
- Added `_build_futures_symbol(symbol)` — returns `{symbol}FUT` (e.g. NIFTYFUT)
- Returns empty dict on any error (never raises)
- Auto-refreshes session if needed before API call
- **Files:** `data/collector/angel_client.py`
- **Commit:** 725365a

### Task 3 — OICollector class
- Extends `BaseVarianceCollector` with `name="oi"`, `poll_interval=300`
- `fetch()` — iterates `TRACKED_SYMBOLS` ("NIFTY", "BANKNIFTY"), calls `get_futures_oi()` via `asyncio.to_thread()`
- `parse()` — extracts total OI + symbol-level OI/LTP; raises on empty/non-dict
- `score()` — OI change pct mapped to [-0.3, 0.3]; >= 3% → ±0.3, below → linear interpolation (pct/10)
- `poll_with_baseline(redis_cache)` — stores current OI in Redis (key prefix `mve:oi_baseline`), computes percentage change from previous poll, populates normalized score + direction + magnitude
- **Files:** `variance/collectors/oi_collector.py`
- **Commit:** 0972556

### Task 4 — Register OICollector in `__init__.py`
- Added import and appended to `__all__`
- **Files:** `variance/collectors/__init__.py`
- **Commit:** 6efe591

### Task 5 — Tests
22 tests across 4 test classes:
- **TestFetch** (2): verifies per-symbol calls, error handling per symbol
- **TestParse** (7): total OI, symbol-level detail, partial data, empty raises, non-dict raises, detail keys, source field
- **TestScore** (9): zero change, 3% threshold (±0.3), beyond-3% clamping, parametrized linear interpolation (0, ±1, ±2), no-change default
- **TestPollWithBaseline** (3): first poll zero change, second poll computes 10%, no-Redis zero change
- **Files:** `variance/tests/test_oi_collector.py`
- **Commit:** 8f0e0aa

### Task 6 — Verification
All 22 tests pass.

```
variance/tests/test_oi_collector.py ✓ 22 passed in 11.95s
```

## Deviations from Plan

None — plan executed exactly as written.

## Decisions Made

1. **`poll_with_baseline()` as dedicated method** rather than inline in `poll()` — keeps the standard inherited `poll()` chain (fetch→parse→score) clean and allows baseline tracking to be called explicitly when Redis is available.
2. **OI baseline stored per-symbol** in addition to the aggregate total — enables per-symbol OI change analysis without additional queries.
3. **TTL of 3600s** for baseline keys — gives 1-hour window between polls before baseline expires, supporting the 300s polling interval with ~12 consecutive comparisons before requiring a fresh baseline.

## Threats & Security

No new threat surface. The collector reads data via the existing AngelOneClient (already authenticated) and writes to Redis via the existing RedisCache interface. No new network endpoints, file access patterns, or auth paths introduced.

## Self-Check: PASSED

- [x] `data/collector/angel_client.py` — modified (commit 725365a)
- [x] `variance/collectors/oi_collector.py` — created (commit 0972556)
- [x] `variance/collectors/__init__.py` — modified (commit 6efe591)
- [x] `variance/tests/test_oi_collector.py` — created (commit 8f0e0aa)
- [x] 22/22 tests pass
