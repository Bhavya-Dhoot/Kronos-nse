# Kronos NSE — Market Variance Engine

## What This Is

A real-time Market Variance Engine (MVE) that continuously monitors 5 orthogonal dimensions of Indian market variance, computes a composite Market Variance Score (MVS), and uses it to modify Kronos predictions in real-time — adjusting temperature, confidence bands, signal thresholds, and directional bias before any signal is emitted. Kronos predictions become contextually aware of what the broader market is doing RIGHT NOW, rather than relying purely on OHLCV patterns.

## Core Value

Kronos predictions are no longer purely OHLCV-pattern based — they are contextually modified by real-time market variance signals so the system emits fewer false signals during high volatility and catches directional shifts earlier.

## Requirements

### Validated

- ✓ Real-time OHLCV candlestick chart TUI — existing
- ✓ WebSocket tick stream for live NSE prices — existing
- ✓ Kronos-small 24.7M param prediction model — existing
- ✓ NSE data pipeline (Angel One, TimescaleDB, Redis) — existing
- ✓ FastAPI backend with predictions/dqg/history endpoints — existing
- ✓ Angel One Smart API integration (futures OI) — existing
- ✓ DQG (Data Quality Gate) pipeline — existing

### Active

#### MVE-1: Directory Scaffold & Foundation

- [ ] **SCF-01**: Create `variance/` directory tree with `__init__.py` files
- [ ] **SCF-02**: Add MVE dependencies to pyproject.toml (NseIndiaApi, yfinance, scrapling, playwright, ta-lib)
- [ ] **SCF-03**: Add MVE config to config/base.yaml (poll intervals, weights, modification factors)
- [ ] **SCR-04**: RedisCache integration for MVE data persistence

#### MVE-2: Base Collector & Score Dataclass

- [ ] **BASE-01**: Implement `BaseVarianceCollector` abstract class with `fetch()`/`parse()`/`score()`/`poll()`/circuit-breaker
- [ ] **BASE-02**: Create `MarketVarianceScore` dataclass with composite scoring, dimension scores, market state classification, and derived properties (temperature_adjustment, directional_bias, band_width_multiplier, signal_threshold)
- [ ] **BASE-03**: Write and pass unit tests for scoring math (weighted composite, stale dimension handling, market state edge cases)

#### MVE-3: India VIX & Options Collectors

- [ ] **VIX-01**: Install NseIndiaApi and verify import
- [ ] **VIX-02**: Implement `VIXCollector` — poll India VIX every 60s via NseIndiaApi
- [ ] **VIX-03**: Implement `OptionsCollector` — poll PCR, Max Pain, ATM IV, OI concentration every 5min via NseIndiaApi
- [ ] **VIX-04**: Write and pass VIX + Options collector tests

#### MVE-4: FII/DII & Institutional Flow Collector

- [ ] **FII-01**: Implement `FIIDIICollector` — poll FII/DII net flows every 30min via NseIndiaApi
- [ ] **FII-02**: Implement `OICollector` — track Nifty/BankNifty futures OI change via Angel One
- [ ] **FII-03**: Implement `InstitutionalDimensionAggregator` combining FII/DII (0.7) + OI (0.3)
- [ ] **FII-04**: Write and pass institutional collector tests

#### MVE-5: GIFT Nifty Collector (Scrapling)

- [ ] **GFT-01**: Install Scrapling + Playwright, verify
- [ ] **GFT-02**: Implement `GIFTNiftyCollector` with Groww primary + NiftyTrader fallback
- [ ] **GFT-03**: Implement gap-vs-prev-close computation for directional signal
- [ ] **GFT-04**: Write and pass GIFT Nifty collector tests

#### MVE-6: Global & Macro Collectors (yfinance)

- [ ] **GLB-01**: Implement `GlobalMarketsCollector` — poll US futures + Asian indices every 5min via yfinance
- [ ] **GLB-02**: Implement `MacroCollector` — poll USD/INR, crude, gold, US10Y every 5min via yfinance
- [ ] **GLB-03**: Implement `GlobalDimensionAggregator` combining GIFT Nifty (0.5) + Global Markets (0.5)
- [ ] **GLB-04**: Write and pass global + macro collector tests

#### MVE-7: MarketVarianceEngine Orchestrator

- [x] **ENG-01**: Implement `MarketVarianceEngine` — orchestrates all 5 dimension collectors in async loops (Phase 6)
- [x] **ENG-02**: Build `_recompute_mvs()` with Redis publish + pub/sub for real-time updates (Phase 6)
- [x] **ENG-03**: Implement market-hours aware scheduling (CLOSED/PRE_MARKET/MARKET_HOURS/POST_MARKET/GLOBAL_ONLY) (Phase 6)
- [x] **ENG-04**: Implement startup behavior (immediate poll, 3-dimension ready gate, degraded mode) (Phase 6)
- [x] **ENG-05**: Expose Prometheus metrics (mve_composite_score, mve_vix_value, collector health, MVS age) (Phase 6)

#### MVE-8: PredictionModifier (The Integration Layer)

- [ ] **MOD-01**: Implement `modify_pre_inference()` — temperature scaling based on MVS VIX
- [ ] **MOD-02**: Implement `modify_post_inference()` — directional bias + band scaling + signal threshold + confidence tagging
- [ ] **MOD-03**: Integrate into `KronosEngine.predict()` flow
- [ ] **MOD-04**: Update `HeadlessRunner._compute_signal()` to use MVS thresholds
- [ ] **MOD-05**: Enforce OHLCV constraints after all modifications
- [ ] **MOD-06**: Write and pass modifier unit tests (10 test cases)

#### MVE-9: API Routes & UI Integration

- [ ] **API-01**: Add `GET /api/v1/variance/score`, `/dimensions/{name}`, `/history` endpoints
- [ ] **API-02**: Add `WS /ws/variance` for real-time MVS updates
- [ ] **API-03**: Build `MarketVariancePanel.tsx` React component (MVS gauge, dimension bars, impact summary, detail section)
- [ ] **API-04**: Update CandleChart overlay for MVE (gold prediction with MVS tint, FEAR/PANIC chart border, banners)
- [ ] **API-05**: Update DQG panel with MVE health status
- [ ] **API-06**: Update main.py to initialize and inject MVE (VISUAL/HEADLESS/PAPER/COLLECT modes)

#### MVE-10: DQG Extension, Config & Backtesting

- [ ] **DQG-01**: Add `check_mve_health()` to DQG pipeline
- [ ] **DQG-02**: Add `PATCH /api/v1/variance/config` for runtime weight/modification tuning
- [ ] **DQG-03**: Create `mve_history` hypertable in TimescaleDB
- [ ] **DQG-04**: Build backtesting script comparing MAE with/without MVE
- [ ] **DQG-05**: Write and pass integration tests (full cycle, fear state, degraded mode, engine injection)
- [ ] **DQG-06**: Full system test — all 5 collectors poll successfully, MVS recomputes, all modifications applied

### Out of Scope

- Retraining Kronos-small model — MVE is a post-processing layer, NOT a retraining pipeline
- ML-based MVS computation — all dimension scores use deterministic heuristics, not learned models
- Retail flow tracking — no access to retail F&O data (only FII/DII via NSE)
- Corporate bond yields — only US 10Y tracked as macro indicator
- Commodity futures beyond crude/gold — no agri-commodity tracking

## Context

This project builds on the existing Kronos NSE prediction system. The existing system already has:

- **TimescaleDB** hypertables for OHLCV data and predictions
- **Redis** for caching and pub/sub
- **FastAPI** backend with existing routes
- **Angel One Smart API** integration for futures data
- **React TUI** with terminal UI components
- **DQG pipeline** for data quality monitoring
- **Kronos-small** (24.7M params) prediction model running on A2000 4GB

The MVE adds 5 new collector types, a scoring engine, a prediction modifier layer, new API routes, UI components, and historical tracking — all as a post-processing layer on top of the existing system.

## Constraints

- **Tech stack**: Python 3.11, asyncpg, TimescaleDB, Redis, FastAPI, React with Vite
- **Performance**: MVE must add < 5ms to end-to-end prediction latency (< 350ms total)
- **Scrapling dependency**: Requires Playwright Chromium browser (~300MB) for GIFT Nifty scraping
- **Market hours awareness**: Collectors must respect Indian market hours (9:15-15:30 IST)
- **Degraded mode**: System must function with <3 active dimensions
- **Circuit breaking**: Collectors with >5 consecutive errors stop polling automatically

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Post-processing layer (not retraining) | Faster iteration, no GPU training time | — Pending |
| Deterministic scoring (not ML) | Explainable, testable, no drift | — Pending |
| Scrapling for GIFT Nifty | No free API exists; Scrapling handles layout changes | — Pending |
| yfinance for global/macro | Free, well-tested, sufficient frequency | — Pending |
| NseIndiaApi for NSE data | Manages NSE cookies/sessions internally | — Pending |
| Per-collector circuit breakers | Prevents cascading failures | — Pending |
| MVS weights configurable at runtime | Enables tuning without deploy | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions

**After each milestone**:
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-04 after initialization*
