---
phase: 08-api-ui
plan: 01
subsystem: api
tags: [fastapi, variance, mvs, pydantic, redis]
requires:
  - phase: 06-orchestrator
    provides: MarketVarianceEngine in app.state.mve, RedisCache in app.state.mve_redis
  - phase: 05-global-macro
    provides: collector infrastructure
provides:
  - GET /api/v1/variance/score — current composite MVS as VarianceScoreResponse
  - GET /api/v1/variance/dimensions/{name} — per-dimension detail with raw_value
  - GET /api/v1/variance/history — historical MVS entries from Redis list
  - Pydantic schemas: VarianceScoreResponse, DimensionDetailResponse, VarianceHistoryResponse, DimensionScoreSchema
affects:
  - 08-02 (WebSocket variance stream)
  - 08-03 (MarketVariancePanel React component)
tech-stack:
  added: []
  patterns:
    - "Private engine attributes accessed by routes (mve._scores, mve_redis._client) per established codebase pattern"
    - "204 No Content for engine-not-ready state (not 200 with null body)"
    - "Graceful Redis failure returns empty history with warning log"
key-files:
  created:
    - api/routes/variance.py — variance router with 3 GET endpoints
  modified:
    - api/schemas.py — 4 new Pydantic response models
    - api/main.py — variance router registration
key-decisions:
  - "Used 204 No Content for not-ready/no-MVS state per API-01 requirement (not 200 with null)"
  - "Access mve._scores directly for per-dimension data — established pattern in codebase"
  - "Access mve_redis._client.lrange() for history — RedisCache has no dedicated list method"
  - "raw_value derived from collector._last_successful_result when available, None otherwise"
  - "History endpoint wraps Redis LRANGE error silently with empty response + logger.warning"
patterns-established:
  - "API routes access private engine attributes as established in prior phases"
requirements-completed:
  - API-01
  - API-02
  - API-03
duration: 6min
completed: 2026-06-05
---

# Phase 8 Plan 1: Variance REST API Router Summary

**Three GET endpoints exposing MVS score, per-dimension detail, and historical time-series data via FastAPI, with Pydantic v2 response schemas and engine-state-aware error handling**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-05
- **Completed:** 2026-06-05
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added 4 Pydantic v2 response models (`DimensionScoreSchema`, `VarianceScoreResponse`, `DimensionDetailResponse`, `VarianceHistoryResponse`) following existing schema patterns
- Created `api/routes/variance.py` with 3 GET endpoints: score (204 when not ready), dimensions/{name} (404 for unknown), and history (empty list when Redis unavailable)
- Registered the variance router in `create_app()` under `/api/v1` prefix alongside existing route modules
- All verifications pass: schemas import, router loads with 3 routes, app creates with `/api/v1/variance/*` routes visible

## Task Commits

Each task was committed atomically:

1. **Task 1: Add variance Pydantic response schemas** - `a195c6d` (feat)
2. **Task 2: Create variance router with GET endpoints** - `dfc13c2` (feat)
3. **Task 3: Register variance router in api/main.py** - `260cb01` (feat)

## Files Created/Modified

- `api/schemas.py` - Added `DimensionScoreSchema`, `VarianceScoreResponse`, `DimensionDetailResponse`, `VarianceHistoryResponse`
- `api/routes/variance.py` - New module with 3 GET endpoints on `/variance/*` prefix
- `api/main.py` - Added import and `app.include_router` for variance routes

## Decisions Made

None - plan executed as written. All design decisions (204 for not-ready, private attribute access, Redis _client.lrange, raw_value from collector) were specified in the plan.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all three endpoints read from live engine/Redis state. When engine is not ready, they return 204 or 404 as specified. When Redis is unavailable, history returns empty list with a warning log.

## Threat Flags

None - all four threats from the plan's threat model were accepted/mitigated as documented (T-08-01 through T-08-04). No new security-relevant surface was introduced beyond what the plan described.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- REST API surface for variance data is complete and available for WebSocket route (08-02) and UI components (08-03, 08-04)
- Existing test suites should be verified for regression after each phase plan

---
*Phase: 08-api-ui*
*Completed: 2026-06-05*
