# STATE.md — Project Memory

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-04)

**Core value:** Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals so the system emits fewer false signals during high volatility and catches directional shifts earlier.

**Current focus:** Phase 6 — MVE Orchestrator (Plan 01 ✅ 2026-06-04)

## Current Phase

**Phase 6: MVE Orchestrator**
- Requirements: ENG-01/02/03/04/05/06/07
- Status: In Progress
- Plans: 4 plans (06-01, 06-02, 06-03, 06-04) — Wave 1 done, Waves 2-3 pending
- Last Activity: 2026-06-04 (GlobalDimensionAggregator done)
- Key Deliverables: GlobalDimensionAggregator (GIFT Nifty 0.5 + Global Markets 0.5, combined weight 0.30)

## Previous Phase

**Phase 5: Global & Macro**
- Requirements: GLB-01/02/03, MAC-01/02
- Status: Complete ✅
- Plans: 3 plans (05-01, 05-02, 05-03) — all executed
- Last Activity: 2026-06-04 (all plans committed)
- Tests: 26 Phase-5 tests passing

## Progress

| Phase | Status | Requirements |
|-------|--------|-------------|
| 1. Scaffold & Score | Complete | SCF-01–04, BASE-01–04 |
| 2. VIX & Options | Complete | VIX-01–03, OPT-01–06 |
| 3. Institutional Flow | Complete | FII-01–02, OIC-01–03 |
| 4. GIFT Nifty | Complete | GFT-01–05 |
| 5. Global & Macro | Complete | GLB-01–03, MAC-01–02 |
| 6. Orchestrator | Pending | ENG-01–07 |
| 7. PredictionModifier | Pending | MOD-01–08 |
| 8. API & UI | Pending | API-01–04, UI-01–05 |
| 9. DQG & System Test | Pending | DQG-01–05 |

## Key Decisions Log

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Aggregator is standalone class, not collector | No fetch/parse/poll contract needed; pure score combination | Done — 18 tests pass |
| poll_with_baseline() dedicated method | Keeps standard poll() chain clean; baseline tracking callable when Redis available | Done — 22 tests pass |
| OI baseline stored per-symbol + aggregate | Enables per-symbol analysis without extra queries | Done |
| Baseline TTL=3600s | 1-hour window supports 300s polling interval | Done |
| INSTITUTIONAL_WEIGHT=0.25 as module constant | Reusable config for MVE composite | Done |
| Partial-data: reduce active_weight, not stale | More informative than marking everything stale | Done |
| AngelOneClient singleton in _angel.py | Matches _nse.py pattern for lazy init; avoids import-time TOTP | Done — 24 tests pass |
| FII/DII scoring linear ±4000Cr | Simple, explainable, clamped at extremes | Done — 24 tests pass |
| OI scoring threshold-based ±3% | Threshold maps to ±0.3 with linear interpolation; matches market intuition | Done — 22 tests pass |
| Post-processing layer | Faster iteration than retraining | — Pending |
| Deterministic scoring | Explainable, testable, no drift | — Pending |
| get_previous_close() on AngelOneClient | Fetches last daily close via getCandleData for gap computation | Done — 04-01 |
| Browser singleton in _browser.py | Matches _nse.py/_angel.py lazy singleton pattern, ~150MB headless | Done — 04-01 |
| GIFTNiftyCollector with Scrapling | Playwright-based scraping of Groww/NiftyTrader for GIFT Nifty value | Done — 04-01 |
| GIFT Nifty scoring: max(-1.0, min(1.0, gap_pct*0.5)) | 0% gap→0.0, 1% gap→0.5, 2% gap→1.0, -2% gap→-1.0 | Done — 21 tests pass |
| Groww primary + NiftyTrader fallback | Dual-source reliability per D-08/D-09 | Done — 21 tests pass |
| Playwright browser singleton in _browser.py | Lazy async singleton matching _nse.py pattern | Done — 21 tests pass |
| get_previous_close() on AngelOneClient | Daily candle close via Angel Smart API for gap computation | Done — 21 tests pass |
| yfinance for global/macro | Free, well-tested, sufficient freq | Done — 05-01 |
| NseIndiaApi for NSE data | Manages NSE cookies/sessions | — Pending |
| Per-collector circuit breakers | Prevents cascading failures | — Pending |
| GlobalDimensionAggregator follows Institutional pattern | D-04: uniform aggregator interface | Done — 06-01 |
| Global internal weights: GIFT 0.5, Global 0.5 | D-05: equal split | Done — 06-01 |
| Combined MVS weight 0.30 | D-06: sum of gift_nifty 0.15 + global_macro 0.15 | Done — 06-01 |

*Last updated: 2026-06-04 after Plan 06-01 execution*
