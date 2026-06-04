# Requirements: Kronos NSE — Market Variance Engine

**Defined:** 2026-06-04
**Core Value:** Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals

## v1 Requirements

### MVE Foundation

- [ ] **SCF-01**: Create `variance/` directory tree with all subdirectories and `__init__.py` files
- [ ] **SCF-02**: Add MVE dependencies (NseIndiaApi, yfinance, scrapling, playwright, ta-lib/pandas-ta) to pyproject.toml
- [ ] **SCF-03**: Add MVE config section to config/base.yaml (poll intervals, dimension weights, modification factors, GIFT Nifty URLs)
- [ ] **SCF-04**: RedisCache integration for MVE data persistence (set/get with TTL)

### Base Collector & Score

- [ ] **BASE-01**: `BaseVarianceCollector` abstract class with fetch()/parse()/score()/poll() and circuit-breaker (5 consecutive errors)
- [ ] **BASE-02**: `MarketVarianceScore` dataclass with composite scoring, 5 DimensionScore objects, market state classification, and derived properties (temperature_adjustment, directional_bias, band_width_multiplier, signal_threshold)
- [ ] **BASE-03**: `MarketVarianceScore.build()` classmethod with stale-dimension half-weight logic
- [ ] **BASE-04**: Standardized parse output schema shared by all collectors

### VIX Collector

- [ ] **VIX-01**: NseIndiaApi installed and import verified
- [ ] **VIX-02**: `VIXCollector` polls India VIX every 60s via NseIndiaApi.getAllIndices()
- [ ] **VIX-03**: VIX scoring: VIX 30→-1.0, VIX 20→-0.3, VIX 15→0.0, VIX 10→0.8

### Options Collector

- [ ] **OPT-01**: `OptionsCollector` fetches NIFTY option chain every 5min via NseIndiaApi
- [ ] **OPT-02**: PCR computation from total CE/PE open interest
- [ ] **OPT-03**: Max Pain computation (strike minimizing total OI loss)
- [ ] **OPT-04**: ATM IV extraction from nearest ATM strike options
- [ ] **OPT-05**: OI concentration ratio (top 5 strikes / total OI)
- [ ] **OPT-06**: Score adjusts PCR base score with max-pain distance

### FII/DII Collector

- [ ] **FII-01**: `FIIDIICollector` polls FII/DII net flows every 30min via NseIndiaApi
- [ ] **FII-02**: FII/DII scoring: FII weighted 0.7, DII weighted 0.3, normalized to ±4000Cr

### Futures OI Collector

- [x] **OIC-01**: `OICollector` polls Nifty/BankNifty futures OI every 5min via Angel One
- [x] **OIC-02**: OI change percentage computed against previous poll (stored in Redis)
- [x] **OIC-03**: OI scoring: >3% buildup→+0.3, <-3% unwind→-0.3

### GIFT Nifty Collector

- [ ] **GFT-01**: Scrapling + Playwright installed, browser initialization working
- [ ] **GFT-02**: `GIFTNiftyCollector` scrapes Groww.in (primary) every 5min
- [ ] **GFT-03**: Fallback to niftytrader.in when Groww fails
- [ ] **GFT-04**: Gap-vs-prev-Nifty-close computation for directional signal
- [ ] **GFT-05**: GIFT Nifty scoring: 1% gap→0.5 score (linear, capped at ±1.0)

### Global Markets Collector

- [ ] **GLB-01**: `GlobalMarketsCollector` polls US futures (ES, YM, NQ) + Asian indices (N225, HSI, SH) + DXY every 5min via yfinance
- [ ] **GLB-02**: Weighted scoring: S&P 500 30%, Nasdaq 20%, Dow 10%, Nikkei 15%, HSI 12%, Shanghai 8%, KOSPI 5%
- [ ] **GLB-03**: DXY impact applies inverse adjustment (strong USD = NSE headwind)

### Macro Collector

- [ ] **MAC-01**: `MacroCollector` polls USD/INR, Brent crude, Gold, US 10Y every 5min via yfinance
- [ ] **MAC-02**: Weighted scoring: USD/INR 35%, Crude 30%, Gold 15%, US10Y 20% (all inverse — rising = bearish for India)

### MVE Orchestrator

- [ ] **ENG-01**: `MarketVarianceEngine` runs all 5 dimension collectors in async loops
- [ ] **ENG-02**: `_recompute_mvs()` publishes to Redis + pub/sub after any dimension update
- [ ] **ENG-03**: Market-hours aware scheduling (CLOSED pauses all, PRE_MARKET polls GIFT+global, MARKET_HOURS polls all, etc.)
- [ ] **ENG-04**: Startup: immediate poll of all collectors, wait for 3 dimensions, degraded mode after 30s
- [ ] **ENG-05**: `GlobalDimensionAggregator` combines GIFT Nifty (0.5) + Global Markets (0.5)
- [ ] **ENG-06**: `InstitutionalDimensionAggregator` combines FII/DII (0.7) + OI (0.3)
- [ ] **ENG-07**: Prometheus metrics: mve_composite_score, mve_vix_value, mve_collector_up, mve_mvs_age_seconds

### PredictionModifier

- [ ] **MOD-01**: `modify_pre_inference()` increases Kronos temperature based on VIX (0.015/point above 15, capped at +0.3)
- [ ] **MOD-02**: `modify_post_inference()` applies directional bias with decay (full at bar 0, 50% at last bar)
- [ ] **MOD-03**: `modify_post_inference()` scales H/L bands by band_width_multiplier (0.8%/VIX point above 15)
- [ ] **MOD-04**: Signal threshold adjustment: base 0.5% + 0.02%/VIX point
- [ ] **MOD-05**: Confidence override: PANIC/FEAR→LOW, <0.5 MVS confidence→LOW, UNCERTAIN→downgrade one level
- [ ] **MOD-06**: OHLCV constraints enforced after all modifications
- [ ] **MOD-07**: Integrate into KronosEngine.predict() flow
- [ ] **MOD-08**: Update HeadlessRunner._compute_signal() to use mve_signal_threshold

### API Routes

- [ ] **API-01**: `GET /api/v1/variance/score` returns full MVS
- [ ] **API-02**: `GET /api/v1/variance/dimensions/{name}` returns per-dimension detail
- [ ] **API-03**: `GET /api/v1/variance/history` returns MVS time-series from Redis
- [ ] **API-04**: `WS /ws/variance` pushes real-time MVS updates on every recompute

### UI Integration

- [ ] **UI-01**: `MarketVariancePanel.tsx` with MVS gauge, market state badge, dimension bars, impact summary
- [ ] **UI-02**: CandleChart prediction overlay shows MVS tint (green for bullish, red for bearish)
- [ ] **UI-03**: FEAR/PANIC states add thin red chart border + "HIGH VOLATILITY" banner
- [ ] **UI-04**: DQG panel includes MVE status row
- [ ] **UI-05**: main.py initializes MVE in VISUAL/HEADLESS/PAPER/COLLECT modes

### DQG Extension & Config

- [ ] **DQG-01**: `check_mve_health()` in DQG pipeline (active dimensions, stale/circuit-broken lists)
- [ ] **DQG-02**: `PATCH /api/v1/variance/config` for runtime weight/modification factor tuning
- [ ] **DQG-03**: mve_history hypertable in TimescaleDB
- [ ] **DQG-04**: Backtesting script comparing MAE with/without MVE modifications
- [ ] **DQG-05**: Integration tests: full MVE cycle, fear state raises threshold, degraded mode pass-through, engine injection

## v2 Requirements

- **ML-based MVS refinement**: Learn optimal weights from historical MVS vs Nifty returns
- **Sector-specific MVS**: Track sector indices (IT, BANK, PHARMA, AUTO) for per-stock context
- **Social sentiment**: NSE-specific Twitter/Telegram sentiment from Indian trading communities
- **Corporate actions calendar**: Dividend, buyback, FPO calendar as macro input
- **Broader futures tracking**: Include all index futures OI (MIDCAP, SMLCAP, FINNIFTY)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Retraining Kronos-small | MVE is post-processing, not model training infrastructure |
| ML-based scoring | Deterministic for explainability; ML adds drift risk |
| Retail flow tracking | No reliable source for retail F&O data |
| Global bond yields beyond US10Y | Adds complexity with minimal NSE correlation gain |
| Agri-commodities | Not correlated with Indian equity market noise |
| Real-time news/NLP | Requires separate NLP pipeline; out of current scope |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCF-01, SCF-02, SCF-03, SCF-04 | Phase 1 | Pending |
| BASE-01, BASE-02, BASE-03, BASE-04 | Phase 1 | Pending |
| VIX-01, VIX-02, VIX-03 | Phase 2 | Pending |
| OPT-01, OPT-02, OPT-03, OPT-04, OPT-05, OPT-06 | Phase 2 | Pending |
| FII-01, FII-02 | Phase 3 | Pending |
| OIC-01, OIC-02, OIC-03 | Phase 3 | Complete ✅ |
| GFT-01, GFT-02, GFT-03, GFT-04, GFT-05 | Phase 4 | Pending |
| GLB-01, GLB-02, GLB-03 | Phase 5 | Pending |
| MAC-01, MAC-02 | Phase 5 | Pending |
| ENG-01, ENG-02, ENG-03, ENG-04, ENG-05, ENG-06, ENG-07 | Phase 6 | Pending |
| MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, MOD-07, MOD-08 | Phase 7 | Pending |
| API-01, API-02, API-03, API-04 | Phase 8 | Pending |
| UI-01, UI-02, UI-03, UI-04, UI-05 | Phase 8 | Pending |
| DQG-01, DQG-02, DQG-03, DQG-04, DQG-05 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 62 total
- Mapped to phases: 62
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-04*
*Last updated: 2026-06-04 after initial definition*
