---
phase: 09-dqg-system-test
plan: 02
subsystem: MVE Runtime Config API
tags: [variance, config, patch, overlay, fastapi]
requires: [06-mve-orchestrator, 08-api-ui]
provides: [PATCH /api/v1/variance/config, config overlay engine methods]
affects: [variance/engine.py, api/routes/variance_config.py, api/schemas.py, api/main.py]
tech-stack:
  added:
    - "Pydantic VarianceConfigUpdate/MveConfigResponse models"
    - "FastAPI APIRouter for runtime config"
  patterns:
    - "Ephemeral in-memory config overlay per D-05"
    - "All-or-nothing validation per D-07"
    - "Dot-separated key navigation in _get_config"
key-files:
  created:
    - "api/routes/variance_config.py"
  modified:
    - "api/schemas.py"
    - "variance/engine.py"
    - "api/main.py"
decisions:
  - "D-05: Ephemeral in-memory overlay — not written to YAML"
  - "D-07: All fields validated before any apply — 422 + detail list"
  - "D-08: Response returns full merged config snapshot (base + overlay)"
  - "D-10: Engine reads via _get_config — overlay first, fallback to base"
metrics:
  duration: ~3 min
  completed: 2026-06-05
---

# Phase 9 Plan 2: MVE Runtime Config API — Summary

Added `PATCH /api/v1/variance/config` endpoint with ephemeral overlay, field validation, and engine runtime config getter. Enables operational tuning of MVE weights, modification factors, and poll intervals without restarting the API.

## Tasks

### Task 1 — Pydantic Schemas + Engine Runtime Config Overlay

**Hash:** `bf485d3`

**Files:** `api/schemas.py`, `variance/engine.py`

- Added `VarianceConfigUpdate` model — optional `weights`, `modification`, `poll_interval_seconds` fields for partial PATCH updates
- Added `MveConfigResponse` model — all 5 config sections (weights, modification, poll_interval_seconds, engine, mve_history)
- Added `self._config_overlay: dict[str, Any] = {}` to `MarketVarianceEngine.__init__`
- Added `_get_config(key, default)` — walks dot-separated key, checks overlay first, falls back to base config
- Added `apply_config_overlay(overlay)` — deep merge into overlay without YAML writes
- Added `get_merged_config()` — deep copy of base + overlay merged
- Added `config_overlay` read-only property

### Task 2 — PATCH /api/v1/variance/config Endpoint

**Hash:** `851d4d3`

**File:** `api/routes/variance_config.py` (created)

- New `APIRouter(prefix="/variance", tags=["variance-config"])`
- `_validate_config_update()` — validates weights ≤ 1.0, intervals ≥ 10s, non-negative modification factors, temperature_cap ≤ 1.0
- All-or-nothing validation per D-07: 422 + detail list on invalid values
- Partial updates supported — only non-None fields are applied to overlay
- Returns 503 if MVE engine not available
- Response returns full `MveConfigResponse` with merged config

### Task 3 — Router Registration in api/main.py

**Hash:** `bbdc60b`

**File:** `api/main.py`

- Added `variance_config` to route imports
- Added `app.include_router(variance_config.router, prefix="/api/v1")` after `variance_routes`
- No additional wiring needed — engine already exists on `app.state.mve` from lifespan

## Threat Mitigation

| Threat ID | Category | Component | Disposition | Covered In |
|-----------|----------|-----------|-------------|------------|
| T-09-03 | Tampering | PATCH endpoint | Mitigate | `_validate_config_update` — weighs ≤ 1.0, all-or-nothing 422 |
| T-09-04 | DoS | poll_interval_seconds | Mitigate | Minimum 10s enforced, prevents 0s intervals |
| T-09-05 | DoS | modification values | Mitigate | temperature_cap ≤ 1.0 enforced, non-negative validation |
| T-09-06 | Tampering | Overlay persistence | Accept | Ephemeral by design — restart restores defaults |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all files are production-ready with no placeholder values.

## Threat Flags

None — no new security-relevant surface introduced beyond what the plan's threat model covers.

## Self-Check: PASSED

- [x] `MarketVarianceEngine` has `_config_overlay` instance variable (empty dict at init)
- [x] `_get_config(key, default)` — returns overlay value first, falls back to base config ✓ (smoke tested)
- [x] `apply_config_overlay(overlay)` — merges without writing to YAML per D-05 ✓ (smoke tested)
- [x] `get_merged_config()` — returns deep copy of base + overlay merged per D-08 ✓ (smoke tested)
- [x] `VarianceConfigUpdate` — accepts optional `weights`, `modification`, `poll_interval_seconds` ✓ (model_fields verified)
- [x] `MveConfigResponse` — returns all 5 config sections ✓ (model_fields verified)
- [x] PATCH /api/v1/variance/config route exists and responds ✓ (router loads, route registered in app)
- [x] Config router registered in `create_app()` under `/api/v1/variance/config` ✓
- [x] All decisions D-05 through D-10 implemented ✓
