# STATE.md — Project Memory

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-04)

**Core value:** Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals so the system emits fewer false signals during high volatility and catches directional shifts earlier.

**Current focus:** Phase 3 — Institutional Flow (Planned 2026-06-04)

## Current Phase

**Phase 3: Institutional Flow**
- Requirements: FII-01/02, OIC-01/02/03
- Status: Executing (1/3 plans complete)
- Plans: 3 plans (03-01, 03-02, 03-03) — 2 waves
  - 03-01: FII/DII Collector — Pending (Wave 1)
  - 03-02: InstitutionalDimensionAggregator — Complete ✅
  - 03-03: OI Collector — Pending (Wave 2)
- Last Activity: 2026-06-04 (03-02 aggregator built, 18 tests passing)
- Tests: 18 aggregator tests passing

## Progress

| Phase | Status | Requirements |
|-------|--------|-------------|
| 1. Scaffold & Score | Complete | SCF-01–04, BASE-01–04 |
| 2. VIX & Options | Complete | VIX-01–03, OPT-01–06 |
| 3. Institutional Flow | Executing (1/3) | FII-01–02, OIC-01–03 |
| 4. GIFT Nifty | Pending | GFT-01–05 |
| 5. Global & Macro | Pending | GLB-01–03, MAC-01–02 |
| 6. Orchestrator | Pending | ENG-01–07 |
| 7. PredictionModifier | Pending | MOD-01–08 |
| 8. API & UI | Pending | API-01–04, UI-01–05 |
| 9. DQG & System Test | Pending | DQG-01–05 |

## Key Decisions Log

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Aggregator is standalone class, not collector | No fetch/parse/poll contract needed; pure score combination | Done — 18 tests pass |
| INSTITUTIONAL_WEIGHT=0.25 as module constant | Reusable config for MVE composite | Done |
| Partial-data: reduce active_weight, not stale | More informative than marking everything stale | Done |
| Post-processing layer | Faster iteration than retraining | — Pending |
| Deterministic scoring | Explainable, testable, no drift | — Pending |
| Scrapling for GIFT Nifty | No free API; handles layout changes | — Pending |
| yfinance for global/macro | Free, well-tested, sufficient freq | — Pending |
| NseIndiaApi for NSE data | Manages NSE cookies/sessions | — Pending |
| Per-collector circuit breakers | Prevents cascading failures | — Pending |

---
*Last updated: 2026-06-04 after initialization*
