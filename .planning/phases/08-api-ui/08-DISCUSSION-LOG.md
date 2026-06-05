# Phase 8: API & UI — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion record.

**Date:** 2026-06-05
**Phase:** 08-api-ui
**Mode:** discuss

## Areas Discussed

1. UI Framework + Chart Library
2. MarketVariancePanel Layout
3. CandleChart MVS Tint + FEAR/PANIC
4. DQG Panel MVE Row
5. WS Protocol + History Keys

## Discussion Record

### Area 1: UI Framework + Chart Library
- **Framework:** React + TypeScript (Recommended) — richest ecosystem for financial dashboards, existing config references .tsx names, mature chart ecosystem
- **Chart library:** TradingView lightweight-charts (Recommended) — 2KB, purpose-built for financial charts, built-in candlestick series + primitives for overlay
- **Frontend directory:** Rename from `FModel Trainingkronos-nseui/` to `ui/`, add React + lightweight-charts deps

### Area 2: MarketVariancePanel Layout
- **Gauge style:** Arc gauge (semi-circular, red-yellow-green gradient with needle)
- **Panel placement:** Right sidebar
- **Dimension bars:** Horizontal stacked bars within sidebar panel

### Area 3: CandleChart MVS Tint + FEAR/PANIC
- **MVS tint:** Background gradient (light green for bullish MVS → light red for bearish MVS) behind candlesticks
- **FEAR/PANIC:** Thin red border (2px) around chart + "HIGH VOLATILITY" banner above chart

### Area 4: DQG Panel MVE Row
- **Fields:** Compact row — active dimensions count (N/6), current MVS composite, market state badge, last update time

### Area 5: WS Protocol + History Keys
- **History storage:** Redis list `mve:mvs:history`, capped 1000 entries, TTL 24h
- **WS message:** `{"type": "mvs_update", "payload": {...}}` matching existing typed message pattern

## Deferred Ideas

None — all discussion stayed within phase scope.
