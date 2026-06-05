
<!-- markdownlint-disable MD033 MD041 MD013 -->
<div align="center">

# ⚡ Kronos NSE

**Real-time Market Variance Engine for NSE Equity Predictions**

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-00a86b?logo=fastapi&logoColor=white)]()
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)]()
[![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)]()
[![PyTorch](https://img.shields.io/badge/PyTorch-2.1-EE4C2C?logo=pytorch&logoColor=white)]()
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-hypertable-FCBB2C?logo=timescale&logoColor=white)]()
[![Redis](https://img.shields.io/badge/Redis-pubsub-DC382D?logo=redis&logoColor=white)]()
[![Tests](https://img.shields.io/badge/tests-139_passing-22c55e)]()
[![License](https://img.shields.io/badge/license-MIT-8b5cf6)]()

<br>

<svg width="700" height="44" viewBox="0 0 700 44" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gb1" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#22c55e"/>
      <stop offset="100%" stop-color="#06b6d4"/>
    </linearGradient>
    <linearGradient id="gb2" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#8b5cf6"/>
      <stop offset="100%" stop-color="#f43f5e"/>
    </linearGradient>
  </defs>
  <text x="16" y="28" fill="#94a3b8" font-size="13" font-family="monospace">latency</text>
  <rect x="72" y="14" width="96" height="14" rx="7" fill="url(#gb1)"/>
  <text x="86" y="25" fill="#0f172a" font-size="11" font-family="monospace" font-weight="bold">340ms</text>
  <text x="180" y="28" fill="#64748b" font-size="12" font-family="monospace">&lt; 500ms budget</text>
  <circle cx="310" cy="22" r="3" fill="#475569"/>
  <text x="324" y="28" fill="#94a3b8" font-size="13" font-family="monospace">parameters</text>
  <rect x="408" y="14" width="72" height="14" rx="7" fill="url(#gb2)"/>
  <text x="420" y="25" fill="#fff" font-size="11" font-family="monospace" font-weight="bold">24.7M</text>
  <text x="492" y="28" fill="#64748b" font-size="12" font-family="monospace">Kronos-small</text>
</svg>

<br>

<svg width="700" height="88" viewBox="0 0 700 88" xmlns="http://www.w3.org/2000/svg">
  <style>
    .p { fill:#1e293b; stroke:#334155; stroke-width:1; }
    .pt { fill:#e2e8f0; font-size:11px; font-family:monospace; text-anchor:middle; }
    .a { fill:none; stroke:#64748b; stroke-width:1.5; marker-end:url(#am); }
    .ab { fill:none; stroke:#06b6d4; stroke-width:1.5; marker-end:url(#am); }
  </style>
  <defs>
    <marker id="am" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#64748b"/>
    </marker>
  </defs>
  <rect class="p" x="6" y="6" width="106" height="24" rx="12"/>
  <text class="pt" x="59" y="22">Angel One API</text>
  <rect class="p" x="122" y="6" width="90" height="24" rx="12"/>
  <text class="pt" x="167" y="22">NSE India</text>
  <rect class="p" x="222" y="6" width="100" height="24" rx="12"/>
  <text class="pt" x="272" y="22">Yahoo Finance</text>
  <rect class="p" x="332" y="6" width="106" height="24" rx="12"/>
  <text class="pt" x="385" y="22">Playwright</text>
  <rect class="p" x="448" y="6" width="100" height="24" rx="12"/>
  <text class="pt" x="498" y="22">TimescaleDB</text>
  <rect x="16" y="46" width="210" height="28" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1.5"/>
  <text x="121" y="65" fill="#c4b5fd" font-size="12" font-family="monospace" text-anchor="middle">Market Variance Engine</text>
  <rect x="244" y="46" width="196" height="28" rx="8" fill="#1e293b" stroke="#06b6d4" stroke-width="1.5"/>
  <text x="342" y="65" fill="#67e8f9" font-size="12" font-family="monospace" text-anchor="middle">Kronos Inference Engine</text>
  <rect class="p" x="458" y="46" width="80" height="24" rx="12"/>
  <text class="pt" x="498" y="63">FastAPI</text>
  <rect class="p" x="548" y="46" width="70" height="24" rx="12"/>
  <text class="pt" x="583" y="63">WebSocket</text>
  <rect class="p" x="628" y="46" width="60" height="24" rx="12"/>
  <text class="pt" x="658" y="63">React UI</text>
  <path class="a" d="M59,30 L59,41"/>
  <path class="a" d="M167,30 L167,41"/>
  <path class="a" d="M272,30 L286,41"/>
  <path class="a" d="M385,30 L385,41"/>
  <path class="ab" d="M226,60 L244,60"/>
  <path class="a" d="M440,60 L458,59"/>
  <path class="a" d="M440,60 L548,59"/>
  <path class="a" d="M440,60 L628,59"/>
</svg>

<br>

<svg width="460" height="22" viewBox="0 0 460 22" xmlns="http://www.w3.org/2000/svg">
  <text x="6" y="15" fill="#64748b" font-size="11" font-family="monospace">9 phases</text>
  <circle cx="70" cy="11" r="2.5" fill="#64748b"/>
  <text x="78" y="15" fill="#64748b" font-size="11" font-family="monospace">62 requirements</text>
  <circle cx="176" cy="11" r="2.5" fill="#64748b"/>
  <text x="184" y="15" fill="#64748b" font-size="11" font-family="monospace">139 tests</text>
  <circle cx="254" cy="11" r="2.5" fill="#64748b"/>
  <text x="262" y="15" fill="#64748b" font-size="11" font-family="monospace">7 dimension collectors</text>
  <circle cx="388" cy="11" r="2.5" fill="#64748b"/>
  <text x="396" y="15" fill="#64748b" font-size="11" font-family="monospace">143 files</text>
</svg>

</div>

---

## Overview

**Kronos NSE** is a production-grade financial prediction system for the Indian National Stock Exchange (NSE). It combines a **Kronos-small** foundation model (24.7M parameters) with a real-time **Market Variance Engine (MVE)** that monitors 5 orthogonal market dimensions — VIX, options sentiment, institutional flow, GIFT Nifty gaps, and global/macro indicators — to contextually modify predictions based on live market conditions.

The system ingests OHLCV data via Angel One SmartAPI, runs data quality gates (DQG) before every inference, and emits trading signals through Redis pub/sub, WebSocket streams, CSV export, and database storage — all within a 500ms latency budget from candle close to signal emission.

---

## Key Features

| Area | Capability |
|------|-----------|
| **Market Variance Engine** | 7 sub-dimension collectors with adaptive polling (60s–1800s intervals), composite MVS scoring with market-state classification, 5-layer prediction modification |
| **Data Quality Gate** | 9 pre-inference checks (history depth, coverage, gaps, OHLCV constraints, outliers, staleness, volume, MVE health) with Redis caching and DB persistence |
| **Prediction Modification** | Pre-inference temperature scaling → directional bias with linear decay → band widening → OHLCV constraint enforcement → confidence override |
| **Real-time Streaming** | WebSocket endpoints for predictions, ticks, DQG reports, trading signals, and MVS updates — all powered by Redis pub/sub |
| **React Dashboard** | TradingView candlestick chart with MVS-driven background tint, animated SVG gauge, dimension bars, FEAR/PANIC visual alerts |
| **Backtesting** | Historical prediction runner + MVE impact comparison (MAE, directional accuracy, confidence delta) |
| **Persistent Storage** | TimescaleDB hypertables with compression + auto-retention, Redis dual-write for fast cache |

---

## Architecture

### System Flow

<pre>
                            DATA SOURCES
  ┌─────────────┐  ┌──────────┐  ┌─────────────┐  ┌───────────┐  ┌──────────┐
  │ Angel One   │  │ NSE      │  │ Yahoo       │  │ Playwright│  │ Timescale│
  │ SmartAPI    │  │ India    │  │ Finance     │  │ (browser) │  │ DB       │
  │ OHLCV / F&O │  │ VIX/PCR  │  │ Global/Macro│  │ GIFT Nifty│  │ candles  │
  └──────┬──────┘  └────┬─────┘  └──────┬──────┘  └─────┬─────┘  └─────┬────┘
         │              │               │               │              │
         ▼              ▼               ▼               ▼              ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                       DATA QUALITY GATE (DQG)                          │
  │                                                                         │
  │  ┌──────────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌────┐ │
  │  │min_hist..│ │coverage│ │ gaps │ │OHLCV │ │outlier│ │stale.. │ │vol │ │
  │  └──────────┘ └────────┘ └──────┘ └──────┘ └──────┘ └────────┘ └────┘ │
  │                          + mve_health (warning)                        │
  └──────────────────────────────┬──────────────────────────────────────────┘
                                 │ PASS
                                 ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  KRONOS ENGINE  (24.7M params)      MARKET VARIANCE ENGINE             │
  │  ┌────────────────────────┐       ┌────────────────────────────────┐   │
  │  │ Kronos-small           │       │ VIX         Options    FII/DII │   │
  │  │ lookback: 225 bars     │◄──────┤ OI          GIFT Nifty         │   │
  │  │ predict:  12 bars      │  MVS  │ Global Mkts Macro              │   │
  │  │ cached + versioned     │ inject│                                │   │
  │  └───────────┬────────────┘       └────────────┬───────────────────┘   │
  │              │               ▲                 │ composite MVS        │
  │     PredictionModifier      │                 ▼                       │
  │     • temperature scale     │      ┌──────────────────────┐           │
  │     • directional bias      │      │ MarketVarianceScore │           │
  │     • band widening         │      │  -1.0  ←→  +1.0    │           │
  │     • OHLCV constraints     │      │  state classifier   │           │
  │     • confidence override   │      └──────────────────────┘           │
  └──────────────────────────────┬──────────────────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                           OUTPUT TARGETS                               │
  │                                                                         │
  │  ┌────────────┐  ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
  │  │ FastAPI    │  │ WebSocket  │  │  Redis   │  │   CSV    │  │  DB  │ │
  │  │ REST API   │  │   Stream   │  │  pub/sub │  │  Export   │  │ Store│ │
  │  └────────────┘  └────────────┘  └──────────┘  └──────────┘  └──────┘ │
  │  ┌───────────────────────────────────────────────────────────────────┐ │
  │  │              React Dashboard (lightweight-charts)                │ │
  │  │     CandleChart · MVS Gauge · Dimension Bars · DQG Row         │ │
  │  └───────────────────────────────────────────────────────────────────┘ │
  └─────────────────────────────────────────────────────────────────────────┘
</pre>

### Market Variance Score Computation

<pre>
  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
  │    VIX     │   │  Options   │   │ Inst.Flow  │   │ GIFT Nifty │   │ Global/    │
  │  weight   │   │  weight    │   │  weight    │   │  weight    │   │ Macro      │
  │    0.25   │   │   0.20     │   │   0.25     │   │   0.15     │   │ weight 0.15│
  │   -1↔+1   │   │   -1↔+1    │   │   -1↔+1    │   │   -1↔+1    │   │   -1↔+1    │
  └─────┬─────┘   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘   └──────┬─────┘
        │                │                │                │                 │
        └────────────────┴────────────────┴────────────────┴─────────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │         Weighted Composite               │
                    │                                          │
                    │  MVS = 0.25·VIX + 0.20·Options +         │
                    │        0.25·Inst + 0.15·GIFT +           │
                    │        0.15·GlobalMacro                   │
                    │                                          │
                    │  * stale dimensions  → half weight       │
                    │  * ready when 3/7 dimensions active      │
                    └───────────────────┬──────────────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────────────┐
                    │         Market State Classification      │
                    │                                          │
                    │  ≥ +0.5 → BULL_RUN    ≥ +0.2 → NEUTRAL  │
                    │  ≥ -0.2 → UNCERTAIN   ≥ -0.4 → FEAR      │
                    │  &lt; -0.4 → PANIC                          │
                    └───────────────────┬──────────────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────────────┐
                    │         Derived Properties                │
                    │                                          │
                    │  temperature_adjust = max(0,(VIX-15)×0.015)│
                    │  directional_bias    = MVS composite      │
                    │  band_width_mult     = 1 + VIXpts×0.008  │
                    │  signal_threshold    = 0.005+VIXpts×0.002 │
                    │  confidence_override = PANIC/FEAR → LOW   │
                    └──────────────────────────────────────────┘
</pre>

---

## Data Model

### TimescaleDB Hypertables

| Hypertable      | Chunk | Compression | Retention | Purpose                          |
|-----------------|-------|-------------|-----------|----------------------------------|
| `candles`       | 1 day | 7 days      | 90 days   | OHLCV candle data per symbol     |
| `predictions`   | 1 day | 7 days      | 30 days   | Prediction outputs with metadata |
| `signals`       | 1 day | 7 days      | 30 days   | Trading signals with direction   |
| `mve_history`   | 1 day | 7 days      | 30 days   | MVS snapshots with dimensions    |
| `dqg_reports`   | 1 day | 7 days      | 30 days   | Data quality gate results        |

### Redis Cache

| Key Pattern            | Type    | TTL  | Purpose                         |
|------------------------|---------|------|----------------------------------|
| `kronos:cache:*`       | String  | 300s | Prediction cache                 |
| `dqg:report:*:*`       | String  | 300s | DQG report cache                 |
| `mve:mvs:current`      | String  | 60s  | Current MVS snapshot             |
| `mve:mvs:history`      | List    | 24h  | Recent MVS entries (capped 1000) |
| `mve:mvs:pubsub`       | Channel | —    | Real-time MVS broadcast          |
| `signals:*`            | Channel | —    | Signal pub/sub per symbol        |

---

## API Reference

All REST endpoints are prefixed with `/api/v1`. Interactive docs at `/docs` (Swagger) and `/redoc`.

### REST Endpoints

| Method | Endpoint                          | Description                              |
|--------|-----------------------------------|------------------------------------------|
| GET    | `/health`                         | Health check + mode + model version      |
| GET    | `/predictions/{symbol}`           | DQG-gated prediction for one symbol      |
| GET    | `/predictions/batch/{universe}`   | Batch prediction for entire universe     |
| GET    | `/predictions/history/{symbol}`   | Historical OHLCV for charting            |
| GET    | `/dqg/{symbol}`                   | Latest DQG report (cached or fresh)      |
| GET    | `/dqg/batch/{universe}`           | Batch DQG for all symbols in universe    |
| GET    | `/dqg/history/{symbol}`           | DQG report history (24h window)          |
| GET    | `/model/current`                  | Production model metadata + metrics      |
| GET    | `/model/versions`                 | All registered model versions            |
| GET    | `/model/compare`                  | Metric delta between two versions        |
| GET    | `/mode`                           | Get current operating mode               |
| POST   | `/mode`                           | Change operating mode (validated)        |
| GET    | `/variance/score`                 | Current Market Variance Score            |
| GET    | `/variance/dimensions/{name}`     | Per-dimension detail                     |
| GET    | `/variance/history`               | Historical MVS entries from Redis        |
| PATCH  | `/variance/config`                | Update MVE runtime config (ephemeral)    |

### WebSocket Endpoints

| Path                        | Message Type        | Description                          |
|-----------------------------|---------------------|--------------------------------------|
| `/ws/predictions/{symbol}`  | `prediction_update` | Stream predictions on candle close   |
| `/ws/ticks/{symbol}`        | `tick`              | Redis tick pub/sub proxy             |
| `/ws/dqg/{symbol}`          | `dqg_update`        | DQG pub/sub proxy                    |
| `/ws/signals`               | `signal`            | Broadcast all trading signals        |
| `/ws/variance`              | `mvs_update`        | Real-time MVS updates                |
| `/ws/ping`                  | `pong`              | Connection keepalive                 |

---

## Quick Start

### Prerequisites

- Python 3.11+ with CUDA-capable GPU (recommended: A2000 4GB+)
- TimescaleDB + PostgreSQL
- Redis
- Node.js 20+ (for dashboard UI)

### Setup

```bash
git clone https://github.com/Bhavya-Dhoot/Kronos-nse.git
cd kronos-nse

# Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements_linux.txt

# Environment
cp .env.example .env
# Edit .env with Angel One credentials, Redis URL, DB URL

# Database
python scripts/bootstrap_db.py
python scripts/seed_instruments.py
python scripts/bootstrap_historical.py

# UI
cd ui && npm install && cd ..
```

### Configuration

Key settings in `config/base.yaml`:

```yaml
app:
  mode: ${APP_MODE}    # COLLECT | BACKTEST | VISUAL | HEADLESS | TRAIN | PAPER

model:
  name: kronos-small
  lookback: 225        # input bars
  pred_len: 12         # output bars
  temperature: 0.7

variance:
  enabled: true
  poll_intervals:
    vix: 60            # seconds
    options: 300
    fii_dii: 1800
    oi: 300
    gift_nifty: 300
    global_markets: 300
    macro: 300
  weights:
    vix: 0.25
    options: 0.20
    institutional: 0.25
    gift_nifty: 0.15
    global_macro: 0.15
```

### Running

```bash
# Data collection mode
APP_MODE=COLLECT uvicorn main:app --reload

# Headless production (no API)
APP_MODE=HEADLESS python main.py

# Full stack (API + MVE)
APP_MODE=VISUAL uvicorn main:app --reload

# Standalone MVE (no API)
STANDALONE_MVE=1 APP_MODE=HEADLESS python main.py

# UI dev server (separate terminal)
cd ui && npm run dev
```

---

## Market Variance Engine

### Dimension Collectors

| Collector         | Source        | Interval | Weight | Scoring                            |
|-------------------|---------------|----------|--------|------------------------------------|
| **VIX**           | NseIndiaApi   | 60s      | 0.25   | 30→-1.0, 20→-0.3, 15→0.0, 10→+0.8 |
| **Options**       | NseIndiaApi   | 300s     | 0.20   | PCR + Max Pain + ATM IV + OI conc  |
| **FII/DII**       | NseIndiaApi   | 1800s    | 0.175  | Net ±4000Cr, FII 0.7 + DII 0.3     |
| **OI**            | Angel One     | 300s     | 0.075  | Change % vs baseline, ±3%→±0.3     |
| **GIFT Nifty**    | Playwright    | 300s     | 0.15   | Gap%×0.5 capped ±1.0               |
| **Global Markets**| yfinance      | 300s     | 0.075  | 8 weighted tickers (ES, NQ, N225…)  |
| **Macro**         | yfinance      | 300s     | 0.075  | 4 inverse tickers (USDINR, Crude…)  |

### Prediction Modification Pipeline

<pre>
  Input Prediction (OHLCV sequence)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │ Layer 1: Temperature Scaling                 │
  │                                              │
  │   temp = max(regime_temp,                    │
  │               0.7 + (VIX - 15) × 0.015)      │
  │   capped at +0.3 above baseline              │
  └─────────────────────┬────────────────────────┘
                        │
                        ▼
  ┌──────────────────────────────────────────────┐
  │ Layer 2: Directional Bias                    │
  │                                              │
  │   shift_pct = bias × scale × 0.01           │
  │   applied to pred_close only                 │
  │   decay: 1.0 (first bar) → 0.5 (last bar)   │
  └─────────────────────┬────────────────────────┘
                        │
                        ▼
  ┌──────────────────────────────────────────────┐
  │ Layer 3: Band Widening                       │
  │                                              │
  │   mult = 1 + VIX_points_above_15 × 0.008    │
  │   new_H = mid + (H - mid) × mult             │
  │   new_L = mid - (mid - L) × mult             │
  └─────────────────────┬────────────────────────┘
                        │
                        ▼
  ┌──────────────────────────────────────────────┐
  │ Layer 4: OHLCV Constraints                   │
  │                                              │
  │   H ≥ max(O, C)    L ≤ min(O, C)             │
  │   V ≥ 0 (volume cannot be negative)          │
  └─────────────────────┬────────────────────────┘
                        │
                        ▼
  ┌──────────────────────────────────────────────┐
  │ Layer 5: Confidence Override                 │
  │                                              │
  │   PANIC / FEAR   →  confidence = LOW         │
  │   UNCERTAIN       →  downgrade by 1 level    │
  │   direction field is never overridden         │
  └─────────────────────┬────────────────────────┘
                        │
                        ▼
  Modified Prediction (OHLCV sequence)
</pre>

### Market State Classification

| State       | Composite   | VIX    | UI Treatment                                               |
|-------------|-------------|--------|------------------------------------------------------------|
| BULL_RUN    | ≥ +0.5      | &lt; 15  | Normal predictions, lower signal thresholds                |
| NEUTRAL     | ≥ +0.2      | 15–18  | Standard operation                                          |
| UNCERTAIN   | ≥ -0.2      | 18–22  | Slightly elevated thresholds                                |
| FEAR        | ≥ -0.4      | 22–28  | Higher thresholds, LOW confidence, 2px red chart border     |
| PANIC       | &lt; -0.4     | > 28   | Max thresholds, LOW confidence, red banner + border in UI   |

---

## React Dashboard

The monitoring UI is built with React 19 + TypeScript + Vite + `lightweight-charts` 4.2:

| Component              | Description                                               |
|------------------------|-----------------------------------------------------------|
| `CandleChartOverlay`   | Candlestick chart with MVS-driven green/red gradient tint |
| `MVSGauge`             | SVG semi-circular gauge with animated needle              |
| `StateBadge`           | Colored pill for current market state                     |
| `DimensionBar`         | Horizontal bar per dimension with score + weight          |
| `ImpactSummary`        | Grid of 5 derived MVS properties                          |
| `FearPanicBanner`      | Sticky red/orange banner in extreme volatility            |
| `DQGMveRow`            | Compact status bar with dims/MVS/state/age                |
| `MarketVariancePanel`  | 320px right sidebar assembling gauge + bars + impact      |

---

## Testing

```bash
pytest tests/ variance/tests/         # full suite
pytest --cov=variance --cov=api       # coverage
pytest tests/integration/test_variance_system.py -v --tb=long
```

| Test Area              | Files | Lines    | Coverage                          |
|------------------------|-------|----------|-----------------------------------|
| `variance/tests/`      | 13    | ~2,600   | Collectors, engine, modifier, MVS |
| `tests/integration/`   | 4     | ~1,350   | API, headless, system lifecycle   |
| `tests/data_quality/`  | 2     | ~300     | All 9 DQG check functions         |
| `tests/unit/`          | 8     | ~1,470   | Engine, storage, training, TUI    |

---

## Performance Budget

| Component     | Budget  | Actual | Detail                              |
|---------------|---------|--------|--------------------------------------|
| Database      | 20ms    | ~5ms   | TimescaleDB candle fetch             |
| DQG           | 10ms    | ~3ms   | 9 checks on cached data              |
| Inference     | 200ms   | ~150ms | Kronos-small forward pass            |
| MVE overhead  | 5ms     | ~2ms   | PredictionModifier 5 layers          |
| Signal emit   | 5ms     | ~1ms   | Redis pub + CSV + DB                 |
| **Total**     | **500ms** | **~340ms** | Candle close → signal emission |

---

## Project Structure

```
kronos-nse/
├── api/               FastAPI application (7 route modules, schemas, WS manager)
├── variance/          Market Variance Engine (7 collectors, 2 aggregators, modifier, score)
├── model/             ML inference (KronosEngine, predictor wrapper, registry, factory)
├── data/              Data pipeline (Angel One collection, DQG, TimescaleDB + Redis clients)
├── headless/          Production operation (poll loop, signal emitter, runtime, watchdog)
├── backtest/          Historical backtesting framework
├── training/          Fine-tuning pipeline (PyTorch dataset, trainer, evaluator, drift detector)
├── ui/                React dashboard (8 components + WS hook + TypeScript types)
├── scripts/           CLI utilities (DB bootstrap, health check, MVE backtest, TUI)
├── config/            YAML configuration (base + environment overrides)
└── tests/             Test suites (unit, integration, data quality)
```

---

## Tech Stack

| Layer       | Technologies                                                           |
|-------------|-----------------------------------------------------------------------|
| Frontend    | React 19, TypeScript 6, Vite, lightweight-charts 4.2                 |
| Backend     | Python 3.11, FastAPI 0.110, Pydantic v2, asyncpg, uvicorn, httpx     |
| ML/DL       | PyTorch 2.1, HuggingFace Transformers 4.40, bitsandbytes, einops     |
| Storage     | TimescaleDB (hypertables + compression), Redis (cache + pub/sub)     |
| Data Sources| Angel One SmartAPI, NSE India Web API, yfinance, Playwright          |
| Infra       | Docker Compose, pre-commit, ruff, mypy, pytest, hypothesis           |

---

## Development

```bash
ruff check . && ruff format --check .    # lint
mypy api/ variance/ headless/ data/      # type check
pytest -q                                 # all tests
pre-commit run --all-files                # git hooks
```

### Operating Modes

| Mode       | Description                                        |
|------------|----------------------------------------------------|
| `COLLECT`  | Data collection only — Angel One OHLCV ingestion   |
| `BACKTEST` | Historical prediction run with metrics             |
| `VISUAL`   | API + UI + MVE (development)                       |
| `HEADLESS` | Production loop: DQG → predict → emit (no API)     |
| `TRAIN`    | Fine-tuning pipeline                                |
| `PAPER`    | Paper trading with simulated fills                  |

---

## Monitoring

### Prometheus Metrics (MVE)

```
mve_composite_score           gauge  current MVS composite value
mve_vix_value                 gauge  current VIX value
mve_collector_up{collector}   gauge  1 = collector available, 0 = down
mve_mvs_age_seconds           gauge  seconds since last MVS recompute
```

### Health Check

```
GET /health
→ { "status": "ok", "mode": "VISUAL", "model_version": "v2" }
```

---

## License

MIT — see `vendor/Kronos/LICENSE` for details.

---

<div align="center">
  <sub>Built by Bhavya Dhoot · 2026</sub>
</div>
