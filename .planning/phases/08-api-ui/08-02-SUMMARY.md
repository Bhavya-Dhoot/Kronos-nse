---
phase: 08-api-ui
plan: 02
subsystem: api
tags: [fastapi, websocket, redis, mvs, variance]
requires:
  - phase: 08-api-ui
    plan: 01
    provides: GET /api/v1/variance/score, dimension detail, and history endpoints
  - phase: 06-mve-orchestrator
    provides: MarketVarianceEngine in app.state.mve, Redis pub/sub on mve:mvs:updates
provides:
  - WS /ws/variance endpoint with typed mvs_update messages via Redis pub/sub listener
  - Redis history persistence: mve:mvs:history list (1000 cap, 24h TTL)
  - MVE dependency getters: get_mve_engine() and get_mve_redis()
affects:
  - 08-03 (MarketVariancePanel React component consuming WS)
  - 08-05 (MVS gauge trend display reading history)
tech-stack:
  added: []
  patterns:
    - "WebSocket endpoints follow existing ConnectionManager + Redis pub/sub pattern without _ctx helper"
    - "History listener as asyncio task in lifespan with cancel on shutdown"
    - "List operations via mve_redis._client.rpush/ltrim/expire since RedisCache lacks dedicated list methods"
key-files:
  modified:
    - api/dependencies.py — added get_mve_engine(), get_mve_redis()
    - api/routes/websocket.py — added /ws/variance endpoint
    - api/main.py — added _variance_history_listener() with launch and cancel in lifespan
key-decisions:
  - "Access app.state.mve_redis directly via getattr in WS endpoint instead of _ctx helper — WS doesn't need InferenceContext"
  - "Use app.state.mve_redis to check availability at launch time (not local variable redis which is scoped to try block)"
  - "History listener uses _client.rpush/ltrim/expire for list operations — RedisCache has no dedicated list methods"
  - "Graceful MVE-not-available path: accept WS → send error JSON → close (not crash)"
patterns-established:
  - "WS endpoints without _ctx access app.state directly via getattr for optional dependencies"
  - "History listener follows same asyncio Task lifecycle as REFRESH_TASK (create_task, cancel in finally)"
requirements-completed:
  - API-04
  - D-10
  - D-11
  - D-12
duration: 5min
completed: 2026-06-05
---

# Phase 8 Plan 2: WS Variance Endpoint & Redis History Listener Summary

**WS /ws/variance endpoint forwarding typed mvs_update messages via Redis pub/sub bridge, Redis history persistence with 1000-entry cap and 24h TTL, and MVE dependency getters for FastAPI route injection**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-05T09:30:58Z
- **Completed:** 2026-06-05T09:36:21Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `get_mve_engine()` and `get_mve_redis()` dependency functions to `api/dependencies.py` for FastAPI route injection of MVE and Redis from `app.state`
- Added `/ws/variance` WebSocket endpoint following existing ConnectionManager + Redis pub/sub pattern with typed `mvs_update` message envelope (D-11/D-12 format)
- Added `_variance_history_listener()` background task in `api/main.py` lifespan that subscribes to `mve:mvs:updates`, RPUSH-es to `mve:mvs:history`, LTRIMs to 1000 entries, and sets 24h TTL (EXPIRE 86400) per D-10
- Graceful degradation: WS returns error JSON when MVE unavailable; history listener skipped with warning when Redis unavailable
- All 6 existing integration tests pass (no regression)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add MVE dependency getters** - `dea4b42` (feat)
2. **Task 2: Add WS /ws/variance endpoint** - `3571d9a` (feat)
3. **Task 3: Add Redis history listener to lifespan** - `d586096` (feat)

## Files Modified

- `api/dependencies.py` - Added `get_mve_engine()` and `get_mve_redis()` with `MarketVarianceEngine` import
- `api/routes/websocket.py` - Added `@router.websocket("/variance")` endpoint with Redis pub/sub listener and typed `mvs_update` transform
- `api/main.py` - Added `_variance_history_listener()` inner function, launch after MVE startup, cancel in shutdown finally block

## Decisions Made

- Used `app.state.mve_redis` (not local variable `redis`) for availability check — the local variable is scoped inside the try block and inaccessible after the except clause
- Graceful MVE-not-available path in WS: accept connection, send error JSON, close — the client knows immediately instead of a silent disconnect
- History listener follows same asyncio Task lifecycle as `REFRESH_TASK`: `asyncio.create_task()` on startup, `.cancel()` in `finally` on shutdown

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed variable name mismatch in history listener launch**
- **Found during:** Task 3 (Add Redis history listener)
- **Issue:** The plan referenced `if mve_redis is not None` but the existing MVE startup block uses the local variable name `redis` (scoped inside the try block). This caused a `NameError` because `mve_redis` was never defined.
- **Fix:** Changed the guard to `if app.state.mve_redis is not None` — this checks the app state attribute that was set (or set to None) during MVE startup, avoiding the scoping issue.
- **Files modified:** `api/main.py`
- **Verification:** `NameError` resolved, app creates correctly, integration tests pass
- **Committed in:** `d586096` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix — the historical listener would never be launched without it. No scope creep.

## Issues Encountered

- Variable scoping issue in lifespan: the MVE startup block declares `redis` inside a try block, making it inaccessible after the except clause. Fixed by referencing `app.state.mve_redis` instead, which is set in both success and failure paths.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- WS endpoint ready for MarketVariancePanel React component (08-03) to consume via `ws://localhost:8000/ws/variance`
- Redis history being populated for GET /variance/history and MVS gauge trend display (08-05)
- All 6 existing integration tests pass — no regression

## Self-Check: PASSED

- [x] Dependencies import: `get_mve_engine`, `get_mve_redis` loadable
- [x] WS `/ws/variance` route registered in websocket router
- [x] Commit `dea4b42` (Task 1) exists
- [x] Commit `3571d9a` (Task 2) exists
- [x] Commit `d586096` (Task 3) exists
- [x] SUMMARY.md created at `.planning/phases/08-api-ui/08-02-SUMMARY.md`

---

*Phase: 08-api-ui*
*Completed: 2026-06-05*
