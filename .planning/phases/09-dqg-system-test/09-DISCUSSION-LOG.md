# Phase 9: DQG & System Test — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion record.

**Date:** 2026-06-05
**Phase:** 09-dqg-system-test
**Mode:** discuss

## Areas Discussed

1. check_mve_health() design
2. PATCH /api/v1/variance/config endpoint
3. mve_history hypertable
4. Backtesting with/without MVE
5. Integration test scope

## Discussion Record

### Area 1: check_mve_health() Design
- **Severity:** Warning-level (non-critical, like volume_sanity/corporate_action_suspected)
- **Fields:** active_dimensions count (N/6), stale_dimensions list (>30s), circuit_broken_dimensions list
- **Placement:** Inline in existing DQG checks dict — function in checks.py, imported in gate.py
- **Pass condition:** active_dimensions >= 3 (matches engine ready gate D-11)

### Area 2: PATCH /api/v1/variance/config
- **Persistence:** Ephemeral in-memory overlay (restart restores YAML defaults)
- **Hot-reloadable fields:** weights, modification factors, poll intervals
- **Validation:** Full validation before applying any changes. Reject with 422 + detail on invalid.
- **Response:** Full merged config snapshot after update
- **Endpoint:** New router api/routes/variance_config.py with PATCH /api/v1/variance/config

### Area 3: mve_history Hypertable
- **Schema:** Composite + market_state + vix_value + dimensions (JSONB) + 4 derived fields
- **Chunk interval:** 1 day (matching candles pattern)
- **Compression:** After 7 days, retention 30 days
- **Migration:** 003_mve_history.sql
- **Write strategy:** Dual write to Redis + TimescaleDB on every MVS recompute
- **Startup replay:** From TimescaleDB to Redis if Redis history is empty

### Area 4: Backtesting with/without MVE
- **Method:** Single run, toggle modify_post_inference() on predictions
- **Metrics:** MAE (primary), directional accuracy, average confidence
- **Comparison:** Unmodified vs Modified vs Difference
- **Output:** Console table + JSON file

### Area 5: Integration Tests
- **Type:** Async tests with mocked collectors (AsyncMock), not TestClient
- **Scope:** Engine start/dimension/MVS cycle, fear state threshold, degraded mode, modifier injection, check_mve_health() states
- **Approach:** Direct engine control with programmatic dimension injection

## Deferred Ideas

None — all discussion stayed within phase scope.
