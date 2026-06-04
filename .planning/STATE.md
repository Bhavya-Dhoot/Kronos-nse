# STATE.md — Project Memory

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-04)

**Core value:** Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals so the system emits fewer false signals during high volatility and catches directional shifts earlier.

**Current focus:** Phase 1 — Scaffold & Score Foundation

## Current Phase

**Phase 1: Scaffold & Score Foundation**
- Requirements: SCF-01/02/03/04, BASE-01/02/03/04
- Status: Pending

## Progress

| Phase | Status | Requirements |
|-------|--------|-------------|
| 1. Scaffold & Score | Pending | SCF-01–04, BASE-01–04 |
| 2. VIX & Options | Pending | VIX-01–03, OPT-01–06 |
| 3. Institutional Flow | Pending | FII-01–02, OIC-01–03 |
| 4. GIFT Nifty | Pending | GFT-01–05 |
| 5. Global & Macro | Pending | GLB-01–03, MAC-01–02 |
| 6. Orchestrator | Pending | ENG-01–07 |
| 7. PredictionModifier | Pending | MOD-01–08 |
| 8. API & UI | Pending | API-01–04, UI-01–05 |
| 9. DQG & System Test | Pending | DQG-01–05 |

## Key Decisions Log

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Post-processing layer | Faster iteration than retraining | — Pending |
| Deterministic scoring | Explainable, testable, no drift | — Pending |
| Scrapling for GIFT Nifty | No free API; handles layout changes | — Pending |
| yfinance for global/macro | Free, well-tested, sufficient freq | — Pending |
| NseIndiaApi for NSE data | Manages NSE cookies/sessions | — Pending |
| Per-collector circuit breakers | Prevents cascading failures | — Pending |

---
*Last updated: 2026-06-04 after initialization*
