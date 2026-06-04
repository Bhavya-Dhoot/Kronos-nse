# Kronos NSE — Market Variance Engine

## Milestone: MVE Core

**9 phases** | **62 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Scaffold & Score | Foundation: dir tree, deps, config, BaseCollector, Score dataclass | SCF-01/02/03/04, BASE-01/02/03/04 | 8 tests passing for score math |
| 2 | VIX & Options | NSE-specific dimension collectors (volatility, options sentiment) | VIX-01/02/03, OPT-01/02/03/04/05/06 | 8 tests passing; both collectors poll successfully |
| 3 | Institutional Flow | FII/DII + futures OI collectors | FII-01/02, OIC-01/02/03 | 7 tests passing; aggregator combines correctly |
| 4 | GIFT Nifty | Scrapling-based GIFT Nifty with fallback | GFT-01/02/03/04/05 | 6 tests passing; both scrapers work |
| 5 | Global & Macro | yfinance collectors for US/Asia/macro | GLB-01/02/03, MAC-01/02 | 7 tests passing; weighted scores correct |
| 6 | Orchestrator | MarketVarianceEngine with async loops, hours-awareness, Redis pub | ENG-01/02/03/04/05/06/07 | Engine starts, polls all dims, publishes MVS |
| 7 | PredictionModifier | 5 modification layers + KronosEngine integration | MOD-01/02/03/04/05/06/07/08 | 10 tests; OHLCV constraints verified |
| 8 | API & UI | REST/WS endpoints + React MarketVariancePanel + chart MVE overlay | API-01/02/03/04, UI-01/02/03/04/05 | Endpoints return data; panel renders with live updates |
| 9 | DQG & System Test | MVE health check, runtime config, history table, backtesting, integration tests | DQG-01/02/03/04/05 | All integration tests pass; full system test |

### Phase Details

**Phase 1: Scaffold & Score Foundation**
Goal: Create variance/ directory scaffold, install dependencies, add config, build BaseVarianceCollector abstract class and MarketVarianceScore dataclass with test suite.
Requirements: SCF-01, SCF-02, SCF-03, SCF-04, BASE-01, BASE-02, BASE-03, BASE-04
Success criteria:
1. variance/ directory tree exists with all __init__.py files
2. NseIndiaApi, yfinance, scrapling, playwright, ta-lib/pandas-ta installable
3. config/base.yaml has variance section with all MVE settings
4. BaseVarianceCollector poll/parse/score/circuit-breaker all work
5. MarketVarianceScore.build() computes weighted composite correctly
6. Stale dimensions get half weight in composite
7. Market state classified correctly (FEAR/PANIC/BULL_RUN/etc.)
8. Derived properties (temperature_adjustment, directional_bias, etc.) compute correctly

**Plans:** 4 plans (3 waves)
```
Plans:
- [x] 01-01-PLAN.md — Foundation scaffold (dir tree, deps, config) — Wave 1 ✓
- [x] 01-02-PLAN.md — Data contracts (schema, score dataclass, Redis) — Wave 2 ✓
- [x] 01-03-PLAN.md — BaseVarianceCollector abstract class — Wave 2 ✓
- [x] 01-04-PLAN.md — Tests (collector + scoring math, 24 tests) — Wave 3 ✓
```

**Phase 2: VIX & Options Sentiment**
Goal: Build the two most important NSE-specific collectors — India VIX (60s poll) and NIFTY options sentiment (300s poll).
Requirements: VIX-01, VIX-02, VIX-03, OPT-01, OPT-02, OPT-03, OPT-04, OPT-05, OPT-06
Success criteria:
1. VIXCollector polls successfully via NseIndiaApi
2. VIX score maps correctly: 30→-1.0, 20→-0.3, 15→0.0, 10→0.8
3. OptionsCollector computes PCR, Max Pain, ATM IV, OI concentration correctly
4. Max Pain computation matches expected results
5. Options score adjusts for max-pain distance from spot
6. All 8 tests pass

**Plans:** 2 plans (2 waves)
```
Plans:
- [x] 02-01-PLAN.md — NseIndiaApi singleton + VIXCollector + tests — Wave 1 ✓
- [x] 02-02-PLAN.md — OptionsCollector + tests — Wave 2 ✓
```

Wave 2 *(blocked on Wave 1 completion)*:
Cross-cutting constraints: Both collectors share NseIndiaApi singleton via `_nse.py`. Each collector subclasses `BaseVarianceCollector`. Tests follow Phase 1 patterns (AsyncMock, parametrize, fixtures).

**Phase 3: Institutional Flow**
Goal: Build FII/DII net flows collector (30min) + futures OI change tracker (5min) + InstitutionalDimensionAggregator.
Requirements: FII-01, FII-02, OIC-01, OIC-02, OIC-03
Success criteria:
1. FIIDIICollector polls FII/DII data via NseIndiaApi
2. FII/DII scoring: 0.7 FII weight, 0.3 DII weight, normalized to ±4000Cr
3. OICollector tracks OI change vs previous poll via Redis
4. OI buildup/unwind scoring matches expected thresholds
5. InstitutionalDimensionAggregator combines FII/DII (0.7) + OI (0.3)
6. All 7 tests pass

**Plans:** 3 plans (2 waves)
```
Plans:
- [ ] 03-01-PLAN.md — Angel singleton + FIIDIICollector + tests — Wave 1
- [x] 03-02-PLAN.md — InstitutionalDimensionAggregator + tests — Wave 1 ✓
- [x] 03-03-PLAN.md — OICollector + OI tests — Wave 2 ✓
```

Wave 2 *(blocked on Wave 1 completion)*:
Cross-cutting constraints: OICollector depends on _angel.py singleton (Plan 03). All collectors share _nse.py singleton from Phase 2. Each collector subclasses BaseVarianceCollector. Aggregator is standalone (no collector deps). Tests follow Phase 2 patterns (AsyncMock, parametrize, fixtures).

**Phase 4: GIFT Nifty**
Goal: Build GIFTNiftyCollector using Scrapling + Playwright with Groww primary and NiftyTrader fallback.
Requirements: GFT-01, GFT-02, GFT-03, GFT-04, GFT-05
Success criteria:
1. Scrapling + Playwright installed, browser initializes
2. GIFTNiftyCollector scrapes Groww.in successfully
3. Fallback to niftytrader.in works when primary fails
4. Gap vs previous Nifty close computed correctly
5. Score: 1% gap→0.5, -2% gap→-1.0
6. All 6 tests pass

**Phase 5: Global & Macro**
Goal: Build GlobalMarketsCollector and MacroCollector using yfinance with weighted scoring logic.
Requirements: GLB-01, GLB-02, GLB-03, MAC-01, MAC-02
Success criteria:
1. GlobalMarketsCollector polls US futures (ES, YM, NQ) + Asian indices (N225, HSI, SH) + DXY
2. Weighted global score matches expected: S&P 500 30%, Nasdaq 20%, Nikkei 15%, etc.
3. DXY inverse adjustment applied correctly
4. MacroCollector polls USD/INR, Brent, Gold, US10Y
5. Macro scoring: USD/INR 35%, Crude 30%, Gold 15%, US10Y 20% (all inverse)
6. Missing tickers handled gracefully (skip, don't crash)
7. All 7 tests pass

**Phase 6: MVE Orchestrator**
Goal: Build MarketVarianceEngine that orchestrates all 5 dimension collectors, implements market-hours-aware scheduling, publishes MVS to Redis, and exposes Prometheus metrics.
Requirements: ENG-01, ENG-02, ENG-03, ENG-04, ENG-05, ENG-06, ENG-07
Success criteria:
1. Engine starts and polls all collectors immediately
2. Each dimension collector runs on its own async loop with correct interval
3. _recompute_mvs() publishes to Redis + pub/sub
4. Market-hours aware scheduling works (CLOSED pauses, PRE_MARKET limits, etc.)
5. GlobalDimensionAggregator combines GIFT (0.5) + Global (0.5)
6. InstitutionalDimensionAggregator combines FII/DII (0.7) + OI (0.3)
7. Engine ready only after 3+ dimensions have data
8. Degraded mode after 30s with fewer than 3 dimensions
9. Prometheus metrics exposed correctly

**Phase 7: PredictionModifier**
Goal: Build PredictionModifier — the most intellectually critical component — applying 5 layers of MVS-driven modification to Kronos predictions.
Requirements: MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, MOD-07, MOD-08
Success criteria:
1. Pre-inference temperature adjustment (0.015/VIX point above 15, capped at +0.3)
2. Post-inference directional bias with decay (full at bar 0, 50% at last bar)
3. Band scaling (0.8% wider per VIX point above 15)
4. Signal threshold: base 0.5% + 0.02%/VIX point
5. Confidence override: PANIC/FEAR→LOW, uncertain→downgrade
6. OHLCV constraints maintained after all modifications
7. Integrated into KronosEngine.predict()
8. HeadlessRunner uses mve_signal_threshold
9. All 10 tests pass

**Phase 8: API & UI**
Goal: Expose MVS through REST/WS API endpoints and build React MarketVariancePanel + update CandleChart for MVE visualization.
Requirements: API-01, API-02, API-03, API-04, UI-01, UI-02, UI-03, UI-04, UI-05
Success criteria:
1. GET /api/v1/variance/score returns full MVS (204 if not ready)
2. GET /api/v1/variance/dimensions/{name} returns per-dimension detail
3. GET /api/v1/variance/history returns time-series data
4. WS /ws/variance pushes real-time updates
5. MarketVariancePanel: MVS gauge, market state badge, 5 dimension bars, impact summary
6. CandleChart prediction overlay has MVS tint
7. FEAR/PANIC states show red border + "HIGH VOLATILITY" banner
8. DQG panel includes MVE health status
9. main.py initializes MVE in all modes

**Phase 9: DQG & System Test**
Goal: Extend DQG for MVE health, add runtime config API, create mve_history hypertable, build backtesting, and run full system tests.
Requirements: DQG-01, DQG-02, DQG-03, DQG-04, DQG-05
Success criteria:
1. DQG pipeline includes check_mve_health()
2. PATCH /api/v1/variance/config hot-reloads runtime changes
3. mve_history hypertable created and receiving data
4. Backtesting script produces MVE contribution report
5. Full integration test: MVS cycle→fear state→degraded mode→engine injection
6. All collectors poll successfully in live test
7. Prediction modification verified with/without MVE
---

*Created: 2026-06-04*
