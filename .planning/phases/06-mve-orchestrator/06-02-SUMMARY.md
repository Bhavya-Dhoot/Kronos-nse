---
phase: 06-mve-orchestrator
plan: 02
subsystem: engine
tags: [mve, orchestrator, prometheus, redis, async, market-hours, collector-management]

# Dependency graph
requires:
  - phase: 06-01
    provides: GlobalDimensionAggregator class for combining GIFT Nifty + global market scores
provides:
  - MarketVarianceEngine orchestrator class with lifecycle (start/stop)
  - Market-hours state machine (PRE_MARKET/MARKET_HOURS/POST_MARKET/GLOBAL_ONLY)
  - Async collector task management with market-state-aware polling
  - Per-dimension score tracking with ready gate (3+ dims) and degraded mode (30s timeout)
  - Composite MVS recompute with 1% publish threshold
  - Redis per-dimension caching at mve:{name} and MVS publish to mve:mvs:updates
  - Prometheus 4-metric instrumentation (composite, vix, collector health, age)
affects:
  - 06-03 (FastAPI lifespan + --standalone-mve flag integration)
  - Phase 7 (PredictionModifier consuming MVS)
  - Phase 8 (API routes + WebSocket serving MVS)
  - Phase 9 (DQG health check using health_status property)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - async collector poll_loop with market-state gating
    - DimensionScore aggregation chain (collector → aggregator → MVS)
    - Prometheus gauge registration with per-collector labels

key-files:
  created:
    - variance/engine.py (MarketVarianceEngine class, 513 lines)
  modified:
    - variance/__init__.py (added MarketVarianceEngine export)

key-decisions:
  - "Market state determined by IST time ranges; CLOSED state reserved for calendar-based detection"
  - "GLOBAL_ONLY auto-activates when NSE collectors return no data (weekends/holidays per D-03)"
  - "1% MVS change threshold before Redis publish prevents redundant updates (D-09)"
  - "Ready gate at 3+ sub-dimensions (D-11) — any 3 of 6 sub-dimensions suffices"
  - "Degraded mode at 30s with fewer than 3 dimensions (D-13)"

patterns-established:
  - "Aggregator chain: InstitutionalDimensionAggregator (fii_dii+oi) and GlobalDimensionAggregator (gift_nifty+global_macro combined) produce 4 DimensionScores from 6 sub-dimensions"
  - "Prometheus metrics use labels for per-collector health tracking (mve_collector_up{collector=name})"

requirements-completed:
  - ENG-01
  - ENG-02
  - ENG-03
  - ENG-04
  - ENG-07

# Metrics
duration: 6 min
completed: 2026-06-04
---

# Phase 6 Plan 2: MarketVarianceEngine Core Summary

**MarketVarianceEngine orchestrator with async market-hours-aware collector management, MVS recompute pipeline (aggregators → 1% threshold → Redis publish), and Prometheus 4-metric instrumentation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-04T07:00:00Z
- **Completed:** 2026-06-04T07:06:10Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- **MarketVarianceEngine class** (513 lines) with async lifecycle (start/stop), IST-aware market state machine, and per-collector task management
- **Market state machine** returns PRE_MARKET, MARKET_HOURS, POST_MARKET, or GLOBAL_ONLY based on IST time (540 rules: total-minutes approach)
- **STATE_COLLECTORS** maps each state to active collector names — GLOBAL/PRE_MARKET run 3 collectors, MARKET_HOURS/POST_MARKET run all 7
- **_on_dimension_update()** processes poll results: stores ScoreEntry, caches to Redis at `mve:{name}`, checks ready gate (3+ of 6 sub-dimensions), evaluates degraded mode (30s timeout)
- **_recompute_mvs()** builds 4 DimensionScores (VIX, Options, Institutional via aggregator, Global via aggregator), constructs MVS via `MarketVarianceScore.build()`, enforces 1% publish threshold (D-09), publishes to `mve:mvs:updates`
- **4 Prometheus gauges** registered: `mve_composite_score`, `mve_vix_value`, `mve_collector_up` (with per-collector label), `mve_mvs_age_seconds`
- **5 public properties**: is_ready, is_degraded, last_mvs, active_dimensions, health_status

## Task Commits

Each task was committed atomically:

1. **Task 1: Create MarketVarianceEngine lifecycle, market state, collector management** - `2afdb29` (feat)
2. **Task 2: Add dimension update handling, MVS recompute, Redis publish, Prometheus** - `2afdb29` (included in same commit — cumulative implementation)
3. **Task 3: Export MarketVarianceEngine from variance/__init__.py** - `8f3dc8e` (feat)

**Plan metadata:** (pending)

## Files Created/Modified

- `variance/engine.py` — MarketVarianceEngine class (513 lines), module-level helpers, state constants
- `variance/__init__.py` — Added MarketVarianceEngine to exports

## Decisions Made

- **Market state logic:** Used total-minutes calculation (540=9:00, 555=9:15, 930=15:30, 960=16:00) for clean threshold comparisons
- **CLOSED state:** Included in enum but never returned by `_get_market_state()` — reserved for future calendar-based holiday detection (per D-03, GLOBAL_ONLY is the fallback)
- **Global Markets + Macro pre-combine:** Engine computes simple average of global_markets and macro scores before passing to GlobalDimensionAggregator's `global_score` parameter
- **1% threshold formula:** `abs(new - last) / max(abs(last), 0.01) > 0.01` — per D-09
- **Ready gate:** Counts any 3 of 6 sub-dimensions with `first_poll=True` (viX, options, fii_dii, gift_nifty, global_markets, macro)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. Engine takes pre-configured collector instances and RedisCache via constructor injection.

## Threat Surface Scan

No new threat flags introduced:
- `mve:` prefixed Redis keys via `RedisCache.set_mve()` (T-06-03 mitigated ✅)
- Circuit breaker isolation in _on_dimension_update (T-06-04 mitigated ✅)
- Task cancellation with return_exceptions=True in stop() (T-06-05 mitigated ✅)
- No PII or sensitive data in Prometheus metrics (T-06-06 accepted ✅)
- Market state by local system time only (T-06-07 accepted ✅)

## Next Phase Readiness

- All ENG-01 through ENG-07 requirements for the engine core are complete
- Engine is importable as `from variance.engine import MarketVarianceEngine`
- Ready for **06-03** (FastAPI lifespan integration + --standalone-mve flag) which wires the engine into the application lifecycle
- Properties `health_status` and `active_dimensions` ready for **Phase 9** DQG integration

## Self-Check: PASSED

- ✅ `variance/engine.py` exists (513 lines)
- ✅ `variance/__init__.py` exports MarketVarianceEngine
- ✅ `06-02-SUMMARY.md` exists
- ✅ Commit `2afdb29` exists (Task 1 feat)
- ✅ Commit `8f3dc8e` exists (Task 3 feat)
- ✅ All 4 verification commands pass (syntax, package import, direct import, prometheus)
- ✅ Market state machine verified: 11/11 edge cases pass (GLOBAL_ONLY at 5:00/8:59/16:00/23:59, PRE_MARKET at 9:00/9:14, MARKET_HOURS at 9:15/12:00/15:30, POST_MARKET at 15:31/15:59)

---

*Phase: 06-mve-orchestrator*
*Plan: 02*
*Completed: 2026-06-04*
