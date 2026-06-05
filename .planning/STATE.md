# STATE.md — Project Memory

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-04)

**Core value:** Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals so the system emits fewer false signals during high volatility and catches directional shifts earlier.

**Current focus:** Phase 9 — DQG & System Test (Pending 2026-06-05)

## Current Phase

**Phase 8: API & UI**
- Requirements: API-01/02/03/04, UI-01/02/03/04/05
- Status: Complete ✅
- Plans: 5 plans — all completed (08-01 through 08-05)
- Last Activity: 2026-06-05 (all plans committed)
- Tests: 13 Phase-8 tests passing (234 total)

## Previous Phase

**Phase 7: PredictionModifier**
- Requirements: MOD-01/02/03/04/05/06/07/08
- Status: Complete ✅
- Plans: 4 plans — all completed
- Last Activity: 2026-06-05 (all plans committed)
- Tests: 18 Phase-7 tests passing

## Previous Phase

**Phase 6: MVE Orchestrator**
- Requirements: ENG-01/02/03/04/05/06/07
- Status: Complete ✅
- Plans: 4 plans (06-01, 06-02, 06-03, 06-04) — all executed
- Last Activity: 2026-06-04 (all plans committed)
- Tests: 41 Phase-6 tests passing
- Key Deliverables: MarketVarianceEngine with lifecycle, market state machine (PRE_MARKET/MARKET_HOURS/POST_MARKET/GLOBAL_ONLY), collector management, MVS recompute pipeline, Redis publish, Prometheus 4-metric instrumentation, FastAPI lifespan integration, --standalone-mve CLI flag

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
| 6. Orchestrator | Complete | ENG-01–07 |
| 7. PredictionModifier | Complete ✅ | MOD-01–08 |
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
| Market state by IST time ranges, CLOSED reserved | D-02: 4 timed states, holiday handling via D-03 | Done — 06-02 |
| 1% MVS change threshold before Redis publish | D-09: prevents redundant updates, formula abs(new-last)/max(abs(last),0.01) > 0.01 | Done — 06-02 |
| GlobalMarkets+Macro pre-combined before aggregator | Simple average before passing as global_score to GlobalDimensionAggregator | Done — 06-02 |
| Ready gate: 3 of 6 sub-dimensions | D-11/D-12: any 3 suffices (vix, options, fii_dii, gift_nifty, global_markets, macro) | Done — 06-02 |
| Prometheus: 4 gauges with collector labels | ENG-07/D-19: mve_composite_score, mve_vix_value, mve_collector_up, mve_mvs_age_seconds | Done — 06-02 |

| MVE in lifespan after model_version, before mode-specific | Makes engine available in all modes via app.state.mve (D-16) | Done — 06-03 |
| Engine failure isolated via try/except in lifespan | Prevents engine crash from taking down API (T-06-08) | Done — 06-03 |
| engine.stop() in finally block | Prevents zombie engine on shutdown (T-06-09) | Done — 06-03 |
| --standalone-mve + STANDALONE_MVE=1 | Dual activation for CLI and containers (D-17) | Done — 06-03 |
| signal module imported inline in _run_standalone_mve | Keeps top-level imports unchanged | Done — 06-03 |
| Config load failure → empty dict fallback | Graceful degradation if config file missing (T-06-11) | Done — 06-03 |
| PredictionModifier with optional MVE injection | Default None = all mods disabled, defensive per T-07-02 | Done — 07-01 |
| modify_pre_inference uses D-05: max(temp, 0.7+VIX adj) | Reads pre-computed temperature_adjustment from MVS dict | Done — 07-01 |
| Post-inference order: bias→bands→constraints→confidence | Per D-18: pred_close shift first, then H/L bands, then OHLCV clamp | Done — 07-01 |
| Directional bias only affects pred_close with linear decay | D-10/D-12: 1.0→0.5 decay, multiplicative shift per D-13 | Done — 07-01 |
| OHLCV constraints after all modifications | D-17: high=max(high,O,C), low=min(low,O,C), volume>=0 | Done — 07-01 |
| Confidence override sets mve_confidence flag, direction unchanged | D-19/D-21: PANIC/FEAR→LOW, only confidence not direction | Done — 07-01 |
| PredictionModifier injected as optional param in KronosEngine.__init__ | None default preserves existing behavior | Done — 07-02 |
| modify_pre_inference called before predictor.predict() for temperature | MVS VIX adjustment layers on top of regime temperature | Done — 07-02 |
| modify_post_inference called after _df_to_result() before Redis/DB | Bias, bands, OHLCV constraints, confidence applied to result dict | Done — 07-02 |

| HeadlessRunner._compute_signal() changed to instance method to read MVS | Engine access requires self._engine._mve — can't be static | Done — 07-03 |
| MVS signal_threshold replaces hardcoded 0.005 in direction classification | D-22/D-23: dynamic threshold adjusts for market volatility | Done — 07-03 |
| MVS confidence_override applied after computed confidence | D-19/D-20: PANIC/FEAR/UNCERTAIN overrides to LOW | Done — 07-03 |
| Safe getattr fallback when MVE not configured | Graceful degradation: try/except with 0.005 default | Done — 07-03 |
| api/helpers.compute_confidence() checks mve_confidence flag | D-20: override from prediction dict, fallback to computed | Done — 07-03 |
| api/helpers.engine_result_to_prediction() passes mve_confidence from result | Routes modifier-set flag through to API response | Done — 07-03 |

| MVS mocked via MockMVE in all modifier tests | No live MVE/Redis/collectors — MockMVE implements only `is_ready`+`last_mvs` | Done — 18 tests pass 07-04 |
| Directional bias formula validated: shift_pct = bias * bias_scale * 0.01 | D-11: bar 0=1.0 scale, last bar=0.5 scale, verified with pytest.approx() | Done — 07-04 |
| Band scaling formula validated: midpoint widen with mult | D-15: mid=(H+L)/2, new_H=mid+(H-mid)*mult, new_L=mid-(mid-L)*mult | Done — 07-04 |
| Temperature cap at +0.3 verified | (VIX-15)*0.015 cap tested via make_mvs(temperature_adjustment=0.3) | Done — 07-04 |
| React + TypeScript for MVS dashboard | D-01: richest ecosystem for financial charts | Done — 08-03 |
| TradingView lightweight-charts for CandleChart | D-02: 2KB purpose-built financial charting | Done — 08-04 |
| Arc gauge + right sidebar for MVS panel | D-04/D-05: semi-circular SVG gauge, sidebar layout | Done — 08-03 |
| Background gradient tint on candles + FEAR/PANIC border+banner | D-07/D-08: lightweight-charts VerticalGradient, 2px red border | Done — 08-04 |
| Compact DQG MVE row: dims/MVS/state/age | D-09: inline with existing DQG checks | Done — 08-04 |
| Redis list mve:mvs:history capped 1000/TTL 24h | D-10: RPUSH+LTRIM pattern | Done — 08-02 |
| WS typed mvs_update messages | D-11: {"type":"mvs_update","payload":{...}} | Done — 08-02 |
| GET /api/v1/variance/score, /dimensions, /history | API-01/02/03: full MVS, per-dim, history endpoints | Done — 08-01 |
| WS /ws/variance real-time pushes | API-04: ConnectionManager + Redis pub/sub | Done — 08-02 |
| 13 integration tests (REST + WS) | API-01/02/03/04: score, dims, history, WS coverage | Done — 08-05 |
| MarketVariancePanel with gauge, badge, bars, impact | UI-01: 5 React components in 320px sidebar | Done — 08-03 |
| CandleChart MVS background tint | UI-02: lightweight-charts VerticalGradient | Done — 08-04 |
| FEAR/PANIC red border + HIGH VOLATILITY banner | UI-03: 2px red border on chart container, sticky top banner | Done — 08-04 |
| DQG panel MVE status row | UI-04: compact dims/MVS/state/age badge row | Done — 08-04 |
| MVE initialized in all modes via lifespan | UI-05: handled by Phase 6 lifespan integration | Done — 06-03 |

*Last updated: 2026-06-05 after Phase 8 completion*
