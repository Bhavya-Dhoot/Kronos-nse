
<!-- markdownlint-disable MD033 MD041 -->
<div align="center">

# ⚡ Kronos NSE

**Real-time Market Variance Engine for NSE Equity Predictions**

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-00a86b?logo=fastapi&logoColor=white)]()
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)]()
[![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)]()
[![Torch](https://img.shields.io/badge/PyTorch-2.1+-EE4C2C?logo=pytorch&logoColor=white)]()
[![TimescaleDB](https://img.shields.io/badge/TimescaleDB-hypertable-FCBB2C?logo=timescale&logoColor=white)]()
[![Redis](https://img.shields.io/badge/Redis-pub%2Fsub-DC382D?logo=redis&logoColor=white)]()
[![Tests](https://img.shields.io/badge/tests-139_passing-22c55e)]()
[![License](https://img.shields.io/badge/license-MIT-8b5cf6)]()

<br>

<svg width="720" height="48" viewBox="0 0 720 48" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bar1" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#22c55e"/>
      <stop offset="100%" stop-color="#06b6d4"/>
    </linearGradient>
    <linearGradient id="bar2" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#06b6d4"/>
      <stop offset="100%" stop-color="#8b5cf6"/>
    </linearGradient>
    <linearGradient id="bar3" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#8b5cf6"/>
      <stop offset="100%" stop-color="#f43f5e"/>
    </linearGradient>
  </defs>
  <text x="20" y="30" fill="#e2e8f0" font-size="16" font-family="monospace" font-weight="bold">LATENCY</text>
  <rect x="100" y="16" width="100" height="12" rx="6" fill="url(#bar1)" opacity="0.9"/>
  <text x="120" y="26" fill="#0f172a" font-size="10" font-family="monospace" font-weight="bold">340ms</text>
  <text x="210" y="30" fill="#94a3b8" font-size="12" font-family="monospace">&lt; 500ms budget</text>
  <text x="440" y="30" fill="#e2e8f0" font-size="16" font-family="monospace" font-weight="bold">PARAMS</text>
  <text x="510" y="30" fill="#22c55e" font-size="16" font-family="monospace" font-weight="bold">24.7M</text>
  <text x="600" y="30" fill="#94a3b8" font-size="12" font-family="monospace">Kronos-small</text>
</svg>

<br>

<svg width="720" height="96" viewBox="0 0 720 96" xmlns="http://www.w3.org/2000/svg">
  <style>
    .pill { fill: #1e293b; stroke: #334155; stroke-width:1; }
    .pill-text { fill:#e2e8f0; font-size:11px; font-family:monospace; text-anchor:middle; }
    .arrow { fill:none; stroke:#64748b; stroke-width:1.5; marker-end:url(#arrow); }
    .arrow-blue { fill:none; stroke:#06b6d4; stroke-width:1.5; marker-end:url(#arrow-b); }
  </style>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#64748b"/>
    </marker>
    <marker id="arrow-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 Z" fill="#06b6d4"/>
    </marker>
  </defs>

  <!-- Row 1: Data Sources -->
  <rect class="pill" x="10" y="8" width="110" height="26" rx="13"/>
  <text class="pill-text" x="65" y="26">Angel One SmartAPI</text>

  <rect class="pill" x="130" y="8" width="90" height="26" rx="13"/>
  <text class="pill-text" x="175" y="26">NSE India</text>

  <rect class="pill" x="230" y="8" width="100" height="26" rx="13"/>
  <text class="pill-text" x="280" y="26">Yahoo Finance</text>

  <rect class="pill" x="340" y="8" width="110" height="26" rx="13"/>
  <text class="pill-text" x="395" y="26">Playwright/Browser</text>

  <!-- Row 2: Engine -->
  <rect x="30" y="50" width="220" height="30" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1.5"/>
  <text x="140" y="70" fill="#c4b5fd" font-size="12" font-family="monospace" text-anchor="middle">Market Variance Engine</text>

  <rect x="270" y="50" width="180" height="30" rx="8" fill="#1e293b" stroke="#06b6d4" stroke-width="1.5"/>
  <text x="360" y="70" fill="#67e8f9" font-size="12" font-family="monospace" text-anchor="middle">Kronos Inference Engine</text>

  <!-- Row 3: Output -->
  <rect class="pill" x="470" y="50" width="90" height="26" rx="13"/>
  <text class="pill-text" x="515" y="68">FastAPI REST</text>

  <rect class="pill" x="570" y="50" width="70" height="26" rx="13"/>
  <text class="pill-text" x="605" y="68">WebSocket</text>

  <rect class="pill" x="650" y="50" width="60" height="26" rx="13"/>
  <text class="pill-text" x="680" y="68">React UI</text>

  <!-- Arrows: Data -> Engine -->
  <path class="arrow" d="M65,34 L65,45"/>
  <path class="arrow" d="M175,34 L175,45"/>
  <path class="arrow" d="M280,34 L300,45"/>
  <path class="arrow" d="M395,34 L395,45"/>

  <!-- Arrows: Engine -> Output -->
  <path class="arrow-blue" d="M250,65 L270,65"/>
  <path class="arrow" d="M450,65 L470,63"/>
  <path class="arrow" d="M450,65 L570,63"/>
  <path class="arrow" d="M450,65 L650,63"/>
</svg>

<br>

<svg width="400" height="24" viewBox="0 0 400 24" xmlns="http://www.w3.org/2000/svg">
  <text x="8" y="16" fill="#64748b" font-size="11" font-family="monospace">9 phases</text>
  <circle cx="64" cy="12" r="3" fill="#64748b"/>
  <text x="72" y="16" fill="#64748b" font-size="11" font-family="monospace">62 requirements</text>
  <circle cx="160" cy="12" r="3" fill="#64748b"/>
  <text x="168" y="16" fill="#64748b" font-size="11" font-family="monospace">139 tests</text>
  <circle cx="228" cy="12" r="3" fill="#64748b"/>
  <text x="236" y="16" fill="#64748b" font-size="11" font-family="monospace">7 dimension collectors</text>
  <circle cx="360" cy="12" r="3" fill="#64748b"/>
  <text x="368" y="16" fill="#64748b" font-size="11" font-family="monospace">143 files</text>
</svg>

<br>

</div>

---

## 🌟 Overview

**Kronos NSE** is a production-grade financial prediction system for the Indian National Stock Exchange. It combines a **Kronos-small** foundation model (24.7M params) with a real-time **Market Variance Engine (MVE)** that monitors 5 orthogonal market dimensions — VIX, options sentiment, institutional flow, GIFT Nifty gaps, and global/macro indicators — to contextually modify predictions based on live market conditions.

The system ingests OHLCV data via Angel One SmartAPI, runs data quality gates (DQG) before every inference, and emits trading signals through Redis, WebSocket, CSV, and database targets with sub-500ms latency.

---

## ✨ Key Features

<div align="center">

<svg width="720" height="48" viewBox="0 0 720 48" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="170" height="36" rx="8" fill="#1e293b" stroke="#8b5cf6" stroke-width="1"/>
  <text x="16" y="23" fill="#c4b5fd" font-size="12" font-family="monospace" font-weight="bold">MVE</text>
  <text x="85" y="23" fill="#e2e8f0" font-size="11" font-family="monospace" text-anchor="middle">5-dim market variance</text>

  <rect x="182" y="0" width="160" height="36" rx="8" fill="#1e293b" stroke="#22c55e" stroke-width="1"/>
  <text x="198" y="23" fill="#86efac" font-size="12" font-family="monospace" font-weight="bold">DQG</text>
  <text x="262" y="23" fill="#e2e8f0" font-size="11" font-family="monospace" text-anchor="middle">data quality gating</text>

  <rect x="354" y="0" width="170" height="36" rx="8" fill="#1e293b" stroke="#06b6d4" stroke-width="1"/>
  <text x="370" y="23" fill="#67e8f9" font-size="12" font-family="monospace" font-weight="bold">WS</text>
  <text x="439" y="23" fill="#e2e8f0" font-size="11" font-family="monospace" text-anchor="middle">real-time streaming</text>

  <rect x="536" y="0" width="170" height="36" rx="8" fill="#1e293b" stroke="#f43f5e" stroke-width="1"/>
  <text x="552" y="23" fill="#fda4af" font-size="12" font-family="monospace" font-weight="bold">UI</text>
  <text x="621" y="23" fill="#e2e8f0" font-size="11" font-family="monospace" text-anchor="middle">React dashboard</text>
</svg>

<br>
<br>

</div>

- **Market Variance Engine** — 7 sub-dimension collectors polling at adaptive intervals (60s–1800s), aggregated into a composite Market Variance Score with market-state classification (PANIC/FEAR/UNCERTAIN/BULL_RUN/NEUTRAL)
- **Prediction Modification** — 5-layer MVS-driven modification of Kronos predictions: pre-inference temperature scaling → directional bias with decay → band widening → OHLCV constraint enforcement → confidence override
- **Data Quality Gate** — 9 DQG checks executed before every inference (min history, coverage, gap detection, OHLCV constraints, outlier detection, staleness, volume sanity, MVE health)
- **Real-time Streaming** — WebSocket endpoints for predictions, ticks, DQG reports, signals, and MVS updates via Redis pub/sub
- **React Dashboard** — TradingView lightweight-charts candlestick chart with MVS-driven background gradient tint, FEAR/PANIC visual alerts, and compact DQG MVE status row
- **Backtesting** — Historical prediction runner + MVE impact quantification (MAE comparison, directional accuracy)
- **TimescaleDB + Redis** — Hypertable storage for OHLCV, predictions, signals, MVS history with dual-write (fast cache + persistent storage)

---

## 🧠 Architecture

### System Overview

<pre>
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                 │
├────────────┬───────────┬──────────────┬────────────────┬────────────┤
│ Angel One  │ NSE India │ Yahoo Finance│  Playwright    │ TimescaleDB│
│  SmartAPI  │ Web API   │  (yfinance)  │  (GIFT Nifty)  │  (history) │
│  OHLCV/F&O │ VIX/PCR   │ Global/Macro │  Groww/Scrape  │  candles   │
└─────┬──────┴─────┬─────┴──────┬───────┴───────┬────────┴─────┬──────┘
      │            │            │               │              │
      ▼            ▼            ▼               ▼              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    DATA QUALITY GATE (DQG)                          │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌─────┐ ┌──────┐ ┌────────┐ │
│  │ min  │ │ cov- │ │ gap  │ │OHLCV │ │ out- │ │ stale│ │volume  │ │
│  │history│ │erage │ │ check│ │const.│ │liers │ │ness  │ │sanity  │ │
│  └──────┘ └──────┘ └──────┘ └──────┘ └─────┘ └──────┘ └────────┘ │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    + mve_health (warning-level)                 ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────┬────────────────────────────────────────────┘
                          │ pass
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  KRONOS INFERENCE ENGINE          MARKET VARIANCE ENGINE (MVE)      │
│  ┌─────────────────────┐         ┌──────────────────────────────┐   │
│  │  Kronos-small       │         │  VIX Collector (60s)         │   │
│  │  24.7M params       │         │  Options Collector (300s)    │   │
│  │  Lookback: 225 bars │◄───────►│  FII/DII Collector (1800s)  │   │
│  │  Predict: 12 bars   │  MVS    │  OI Collector (300s)        │   │
│  │  Cache + Versioning │  inject │  GIFT Nifty (300s)          │   │
│  └─────────┬───────────┘         │  Global Markets (300s)      │   │
│            │                     │  Macro Collector (300s)     │   │
│     PredictionModifier           └──────────────┬───────────────┘   │
│     • Temperature scaling                       │ composite MVS    │
│     • Directional bias                          ▼                   │
│     • Band widening                   ┌──────────────────┐         │
│     • OHLCV constraints               │ MarketVariance   │         │
│     • Confidence override             │ Score (MVS)      │         │
│                                       │ -1.0 ←→ +1.0     │         │
│                                       │ State classifier  │         │
│                                       └──────────────────┘         │
└─────────────────────────┬────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       OUTPUT TARGETS                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │ FastAPI  │  │WebSocket │  │  Redis   │  │   CSV    │  │  DB  │ │
│  │ REST API │  │  Stream  │  │ pub/sub  │  │  Export  │  │ Store│ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘ │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              React Dashboard (lightweight-charts)           │   │
│  │  [CandleChart] [MVS Gauge] [Dimension Bars] [DQG Row]      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
</pre>

### Market Variance Score Flow

<pre>
┌──────────┐    ┌──────────┐    ┌──────────┐
│  VIX     │    │ Options  │    │ FII/DII  │
│  -1←→+1  │    │  -1←→+1  │    │  -1←→+1  │
└─────┬────┘    └─────┬────┘    └─────┬────┘
      │               │               │
      ▼               ▼               ▼
┌───────────────────────────────────────────────────┐
│  Weighted Composite (5 dimensions)                │
│                                                    │
│  MVS = 0.25·VIX + 0.20·Options + 0.25·Inst.       │
│       + 0.15·GIFT + 0.15·Global_Macro             │
│                                                    │
│  Stale dimensions get half-weight                  │
│  3/7 minimum for engine readiness                  │
└───────────────────────┬───────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────┐
│  Market State Classification                      │
│                                                    │
│  MVS ≥ +0.5  → BULL_RUN     (green)               │
│  MVS ≥ +0.2  → NEUTRAL      (gray)                │
│  MVS ≥ -0.2  → UNCERTAIN    (amber)               │
│  MVS ≥ -0.4  → FEAR         (orange)              │
│  MVS &lt; -0.4  → PANIC        (red)                 │
└───────────────────────┬───────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────┐
│  Derived Properties (applied to predictions)      │
│                                                    │
│  temperature_adjustment  = max(0, (VIX-15)·0.015) │
│  directional_bias        = MVS composite           │
│  band_width_multiplier   = 1 + VIX_points·0.008   │
│  signal_threshold        = 0.005 + VIX_points·0.002│
│  confidence_override     = PANIC/FEAR → LOW        │
└───────────────────────────────────────────────────┘
</pre>

---

## 🗄️ Data Model

### Core Tables (TimescaleDB Hypertables)

| Hypertable | Chunk Interval | Compression | Retention | Purpose |
|------------|---------------|-------------|-----------|---------|
| `candles` | 1 day | 7 days | 90 days | OHLCV candle data per symbol |
| `predictions` | 1 day | 7 days | 30 days | Prediction outputs with metadata |
| `signals` | 1 day | 7 days | 30 days | Trading signals with direction/confidence |
| `mve_history` | 1 day | 7 days | 30 days | MVS snapshots with dimension breakdown |
| `dqg_reports` | 1 day | 7 days | 30 days | Data quality gate results |

### Redis Cache

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `kronos:cache:*` | String | 300s | Prediction cache |
| `dqg:report:*:*` | String | 300s | DQG report cache |
| `mve:mvs:current` | String | 60s | Current MVS snapshot |
| `mve:mvs:history` | List | 24h | Recent MVS entries (capped 1000) |
| `mve:mvs:pubsub` | Channel | — | Real-time MVS broadcast |
| `signals:*` | Channel | — | Signal pub/sub per symbol |

---

## 🧩 API Reference

All REST endpoints are prefixed with `/api/v1`. Full OpenAPI docs at `/docs`.

### Predictions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/predictions/{symbol}` | DQG-gated prediction for one symbol |
| `GET` | `/predictions/batch/{universe}` | Batch prediction for universe |
| `GET` | `/predictions/history/{symbol}` | Historical OHLCV for charting |

### Data Quality

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dqg/{symbol}` | Latest DQG report |
| `GET` | `/dqg/batch/{universe}` | Batch DQG for universe |
| `GET` | `/dqg/history/{symbol}` | DQG report history (24h) |

### Market Variance

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/variance/score` | Current MVS (204 if not ready) |
| `GET` | `/variance/dimensions/{name}` | Per-dimension detail |
| `GET` | `/variance/history` | Historical MVS entries |
| `PATCH` | `/variance/config` | Runtime MVE config overlay |

### WebSocket

| Path | Message Type | Description |
|------|-------------|-------------|
| `/ws/predictions/{symbol}` | `prediction_update` | Stream predictions on candle close |
| `/ws/ticks/{symbol}` | `tick` | Redis tick pub/sub proxy |
| `/ws/dqg/{symbol}` | `dqg_update` | DQG pub/sub proxy |
| `/ws/signals` | `signal` | Broadcast trading signals |
| `/ws/variance` | `mvs_update` | Real-time MVS updates |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (mode + model version) |
| `GET` | `/mode` | Get operating mode |
| `POST` | `/mode` | Change operating mode |
| `GET` | `/model/current` | Production model metadata |
| `GET` | `/model/versions` | All registered model versions |
| `GET` | `/model/compare` | Metric delta between versions |

---

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.11+ with CUDA-capable GPU recommended (A2000 4GB+)
# TimescaleDB + PostgreSQL
# Redis
# Node.js 20+ (for UI)
```

### Installation

```bash
# Clone and setup
git clone https://github.com/Bhavya-Dhoot/Kronos-nse.git
cd kronos-nse

# Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements_linux.txt

# Environment variables
cp .env.example .env
# Edit .env with your Angel One credentials, Redis URL, DB URL

# Database migrations
python scripts/bootstrap_db.py

# Seed instruments
python scripts/seed_instruments.py

# Bootstrap historical data
python scripts/bootstrap_historical.py

# React UI
cd ui
npm install
cd ..
```

### Configuration

The main configuration lives in `config/base.yaml` with environment-specific overrides in `config/development.yaml` and `config/production.yaml`. Key settings:

```yaml
app:
  mode: ${APP_MODE}  # COLLECT | BACKTEST | VISUAL | HEADLESS | TRAIN | PAPER

database:
  url: postgresql://user:pass@localhost:5432/kronos_nse

redis:
  url: redis://localhost:6379/0

model:
  name: kronos-small
  lookback: 225   # input bars
  pred_len: 12    # output bars
  temperature: 0.7

variance:
  enabled: true
  poll_intervals:
    vix: 60
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

# Headless production mode (no API)
APP_MODE=HEADLESS python main.py

# With MVE standalone (no API)
STANDALONE_MVE=1 APP_MODE=HEADLESS python main.py

# Full stack (API + MVE)
APP_MODE=VISAUL uvicorn main:app --reload
# Start UI separately:
cd ui && npm run dev
```

---

## 🔬 Market Variance Engine (MVE)

### Dimension Collectors

| Collector | Source | Poll Interval | Weight | Scoring Logic |
|-----------|--------|---------------|--------|---------------|
| **VIX** | NseIndiaApi | 60s | 0.25 | 30→-1.0, 20→-0.3, 15→0.0, 10→+0.8 |
| **Options** | NseIndiaApi | 300s | 0.20 | PCR + Max Pain distance + ATM IV + OI concentration |
| **FII/DII** | NseIndiaApi | 1800s | 0.175 | Net (Cr) normalized ±4000, FII 0.7 + DII 0.3 |
| **OI** | Angel One | 300s | 0.075 | OI change % vs baseline: ±3%→±0.3 |
| **GIFT Nifty** | Playwright/Groww | 300s | 0.15 | Gap % × 0.5, capped ±1.0 |
| **Global Markets** | yfinance | 300s | 0.075 | 8 tickers weighted (ES 30%, NQ 20%, N225 15%, etc.) |
| **Macro** | yfinance | 300s | 0.075 | 4 tickers all-inverse (USDINR 35%, Crude 30%, Gold 15%, US10Y 20%) |

### Prediction Modification Layers

<pre>
 Input Prediction (OHLCV sequence)
        │
        ▼
 ┌─────────────────────────────────────┐
 │ Layer 1: Temperature Scaling        │
 │ temp = max(regime_temp,             │
 │          0.7 + (VIX-15) × 0.015)    │
 │ Cap: +0.3 above baseline            │
 └─────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────┐
 │ Layer 2: Directional Bias           │
 │ shift% = bias × scale × 0.01       │
 │ Applied to pred_close only          │
 │ Decay: 1.0→0.5 (first→last bar)    │
 └─────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────┐
 │ Layer 3: Band Widening              │
 │ mult = 1 + VIX_points × 0.008      │
 │ new_H = mid + (H-mid) × mult       │
 │ new_L = mid - (mid-L) × mult       │
 └─────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────┐
 │ Layer 4: OHLCV Constraints          │
 │ H ≥ max(O, C), L ≤ min(O, C)       │
 │ V ≥ 0 (volume non-negative)         │
 └─────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────┐
 │ Layer 5: Confidence Override        │
 │ PANIC/FEAR  →  LOW confidence       │
 │ UNCERTAIN   →  downgrade by 1       │
 │ Direction unchanged                 │
 └─────────────────────────────────────┘
        │
        ▼
 Modified Prediction (OHLCV sequence)
</pre>

### Market States

| State | Composite Range | VIX Range | Behavior |
|-------|----------------|-----------|----------|
| 🟢 **BULL_RUN** | ≥ +0.5 | < 15 | Normal predictions, lower thresholds |
| ⚪ **NEUTRAL** | ≥ +0.2 | 15–18 | Standard operation |
| 🟡 **UNCERTAIN** | ≥ -0.2 | 18–22 | Slightly elevated thresholds |
| 🟠 **FEAR** | ≥ -0.4 | 22–28 | Higher thresholds, confidence downgrade, 2px red border in UI |
| 🔴 **PANIC** | < -0.4 | > 28 | Max thresholds, LOW confidence, red banner in UI |

---

## 🖥️ React Dashboard

The UI is a React 19 + TypeScript + Vite application featuring:

- **CandleChart** — TradingView `lightweight-charts` candlestick chart with dark theme and MVS-driven background gradient tint (green→red)
- **MVS Gauge** — SVG semi-circular gauge with animated needle showing composite score
- **Market State Badge** — Colored pill for PANIC/FEAR/UNCERTAIN/BULL_RUN/NEUTRAL
- **Dimension Bars** — 7 horizontal bars with score colors, weight multipliers, stale indicators
- **Impact Summary** — Grid showing temperature_adjustment, directional_bias, band_width_multiplier, signal_threshold, confidence_override
- **Fear/Panic Banner** — Sticky top banner during extreme volatility states
- **DQG MVE Row** — Compact status bar with active dimension count, composite score, state badge, last update time

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ variance/tests/

# Run with coverage
pytest --cov=variance --cov=api --cov=headless --cov=data/quality

# Run specific test groups
pytest tests/integration/test_variance_system.py -v
pytest variance/tests/test_modifier.py -v
pytest tests/data_quality/test_dqg_checks.py -v
```

**Test matrix: 139 tests across 28 test files**

| Test Area | Files | Lines | What it covers |
|-----------|-------|-------|---------------|
| `variance/tests/` | 13 | ~2,600 | MVE collectors, engine, modifier, aggregators, scoring |
| `tests/integration/` | 4 | ~1,350 | API, headless runner, MVE system lifecycle |
| `tests/data_quality/` | 2 | ~300 | All 9 DQG check functions |
| `tests/unit/` | 8 | ~1,470 | Engine, storage, training, rate limiter |

---

## 📁 Project Structure

```
kronos-nse/
├── api/                    # FastAPI application
│   ├── routes/             # 7 route modules
│   ├── main.py             # App factory
│   ├── schemas.py          # Pydantic models
│   ├── ws_manager.py       # WebSocket manager
│   └── helpers.py          # Shared utilities
├── variance/               # Market Variance Engine
│   ├── collectors/         # 7 dimension collectors
│   ├── aggregators/        # Global + Institutional aggregators
│   ├── engine.py           # MarketVarianceEngine
│   ├── modifier.py         # PredictionModifier
│   ├── score.py            # MarketVarianceScore
│   └── base_collector.py   # ABC with circuit-breaker
├── model/                  # ML Inference
│   ├── engine.py           # KronosEngine (cached, versioned)
│   ├── predictor.py        # KronosPredictorWrapper
│   ├── factory.py          # InferenceContext bootstrap
│   └── registry.py         # Model version registry
├── data/                   # Data pipeline
│   ├── collector/          # Angel One + NSE data collection
│   ├── quality/            # DQG pipeline (9 checks)
│   └── storage/            # TimescaleDB + Redis clients
├── headless/               # Production operation
│   ├── runner.py           # Poll + DQG + Predict + Emit loop
│   ├── signal_emitter.py   # Multi-target signal emission
│   ├── runtime.py          # ApplicationRuntime orchestrator
│   └── watchdog.py         # Heartbeat monitor
├── backtest/               # Historical backtesting
│   └── runner.py
├── training/               # Fine-tuning pipeline
│   ├── dataset.py          # NSEKronosDataset (PyTorch)
│   ├── train_predictor.py  # Fine-tuning loop
│   └── evaluator.py        # Holdout evaluation
├── scripts/                # CLI utilities
│   ├── backtest_mve.py     # MVE impact comparison
│   ├── bootstrap_db.py     # DB setup
│   └── health_check.py     # System health
├── ui/                     # React dashboard
│   └── src/components/     # 8 React components
├── config/                 # YAML configuration
└── tests/                  # All test suites
```

---

## ⚙️ Performance Budget

| Component | Budget | Actual | Description |
|-----------|--------|--------|-------------|
| Database query | 20ms | ~5ms | TimescaleDB candle fetch |
| DQG | 10ms | ~3ms | 9 checks on cached data |
| Inference | 200ms | ~150ms | Kronos-small forward pass |
| MVE overhead | 5ms | ~2ms | PredictionModifier layers |
| Signal emit | 5ms | ~1ms | Redis + CSV + DB |
| **Total** | **500ms** | **~340ms** | Candle close to signal |

---

## 🛠️ Tech Stack

<pre>
┌──────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│   React 19 · TypeScript 6 · Vite · lightweight-charts 4.2       │
│   WebSocket (native) · CSS Grid/ Flexbox                        │
├──────────────────────────────────────────────────────────────────┤
│                        BACKEND                                   │
│   Python 3.11 · FastAPI 0.110 · Pydantic v2 · asyncpg           │
│   uvicorn · httpx · aiohttp · websockets 12                     │
│   prometheus-client · structlog                                  │
├──────────────────────────────────────────────────────────────────┤
│                        ML / DL                                   │
│   PyTorch 2.1 · HuggingFace Transformers 4.40                   │
│   Kronos-small (24.7M params) · bitsandbytes 4-bit              │
│   accelerate · einops · safetensors                              │
├──────────────────────────────────────────────────────────────────┤
│                        DATA / STORAGE                            │
│   TimescaleDB (hypertables, compression, auto-retention)        │
│   Redis (cache, pub/sub, capped lists)                          │
│   Pandas · NumPy · PyArrow                                      │
├──────────────────────────────────────────────────────────────────┤
│                        DATA SOURCES                              │
│   Angel One SmartAPI · NSE India Web API · yfinance             │
│   Playwright (headless browser) · Scrapling                     │
├──────────────────────────────────────────────────────────────────┤
│                        INFRASTRUCTURE                            │
│   Docker · Docker Compose                                        │
│   pre-commit · ruff · mypy · pytest · hypothesis                │
│   GitHub Actions (CI/CD)                                         │
└──────────────────────────────────────────────────────────────────┘
</pre>

---

## 🧪 Development

```bash
# Lint
ruff check .  && ruff format --check .

# Type check
mypy api/ variance/ headless/ data/

# Run all tests
pytest -q

# Run with live logging
pytest -v --tb=long tests/integration/test_variance_system.py

# Pre-commit
pre-commit run --all-files
```

### Operational Modes

| Mode | Description |
|------|-------------|
| `COLLECT` | Data collection only — Angel One OHLCV ingestion |
| `BACKTEST` | Historical prediction run with metrics |
| `VISUAL` | API + UI + MVE (development) |
| `HEADLESS` | Production loop: DQG → predict → emit (no API) |
| `TRAIN` | Fine-tuning pipeline |
| `PAPER` | Paper trading with simulated fills |

---

## 📊 Monitoring

### Prometheus Metrics (4 MVE gauges)

```
mve_composite_score          # Current MVS composite value
mve_vix_value                # Current VIX value
mve_collector_up{collector}  # Per-collector availability (1/0)
mve_mvs_age_seconds          # Seconds since last MVS update
```

### Health Check

```
GET /health → { "status": "ok", "mode": "VISUAL", "model_version": "..." }
```

---

## 📜 License

MIT — see [LICENSE](vendor/Kronos/LICENSE) for details.

---

<div align="center">

<svg width="400" height="24" viewBox="0 0 400 24" xmlns="http://www.w3.org/2000/svg">
  <text x="200" y="16" fill="#64748b" font-size="11" font-family="monospace" text-anchor="middle">Built by Bhavya Dhoot · 2026</text>
</svg>

</div>
