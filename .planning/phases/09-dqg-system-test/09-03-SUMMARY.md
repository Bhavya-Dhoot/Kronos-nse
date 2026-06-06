---
phase: 09-dqg-system-test
plan: 03
subsystem: database
tags: [timescaledb, migration, hypertable, asyncpg, mve, redis, startup-replay]

# Dependency graph
requires:
  - phase: 09-02
    provides: MVE runtime config overlay API pattern
  - phase: 08-api-ui
    provides: Redis mve:mvs:history list pattern (capped 1000, TTL 24h)
  - phase: 06-mve-orchestrator
    provides: MarketVarianceEngine with _recompute_mvs() and publish lifecycle
provides:
  - mve_history TimescaleDB hypertable with 1-day chunks, 7-day compression, 30-day retention
  - TimescaleClient.insert_mve_history() for persistent MVS storage
  - TimescaleClient.get_mve_history() for startup replay queries
  - Engine dual write (Redis + TimescaleDB) in _recompute_mvs()
  - Engine startup replay from TimescaleDB to Redis when Redis cache is empty
affects:
  - 09-04 (backtesting — uses mve_history for historical analysis)
  - 09-05 (integration tests — verifies dual write path)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual write: Redis (fast cache) + TimescaleDB (persistent storage)"
    - "Migration pattern: sequential .sql files with compression and retention policies"
    - "Non-blocking startup replay via asyncio.create_task"

key-files:
  created:
    - data/storage/migrations/003_mve_history.sql
  modified:
    - data/storage/timescale.py
    - variance/engine.py
    - api/main.py

key-decisions:
  - "Dimensions pruned to 4 fields (name, score, weight, is_stale) before JSONB insertion — keeps storage compact"
  - "insert_mve_history uses parameterized query with $N placeholders — no SQL injection risk"
  - "get_mve_history returns entries in chronological order via reversed(rows) — ready for replay"
  - "Startup replay is non-blocking (asyncio.create_task) — doesn't delay engine start"
  - "TimescaleDB writes are non-critical — failures logged but never propagated"

patterns-established:
  - "Migration pattern: create table → hypertable → indexes → compression settings → retention policy"
  - "TimescaleClient method pattern: pool guard → parameterized SQL → try/except with logger.exception"
  - "Engine external dependency pattern: optional parameter, None default, duck-typed usage"

requirements-completed: [DQG-03]

# Metrics
duration: 12min
completed: 2026-06-05
---

# Phase 9 - Plan 03: mve_history Hypertable Migration and Engine Dual Write

**TimescaleDB mve_history hypertable for persistent MVS tracking with engine dual write (Redis + TimescaleDB) and startup replay from TimescaleDB to Redis**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-05T...Z
- **Completed:** 2026-06-05T...Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Created `003_mve_history.sql` migration with mve_history hypertable: 1-day chunk interval (D-13), 7-day compression + 30-day retention (D-14), time DESC index (D-15)
- Added `TimescaleClient.insert_mve_history()` — parameterized insert with dimensions pruned to 4 core fields for compact JSONB storage
- Added `TimescaleClient.get_mve_history()` — fetches up to 1000 entries ordered chronologically for replay
- Wired MarketVarianceEngine to accept optional `timescale` parameter (default None, duck-typed)
- Added dual write in `_recompute_mvs()`: persists MVS to TimescaleDB immediately after Redis publish (D-16)
- Added `_replay_history_from_timescaledb()`: checks Redis history length, replays last 1000 entries from TimescaleDB to Redis mve:mvs:history list if empty (D-17)
- Startup replay is non-blocking via `asyncio.create_task` in `start()`
- TimescaleDB failures wrapped in try/except with `logger.exception` — non-critical, engine continues without crashing (T-09-09)
- Wired `ctx.db` (TimescaleClient from InferenceContext) as `timescale=` parameter in `api/main.py` lifespan

## Task Commits

Each task was committed atomically:

1. **Task 1: Create migration SQL and TimescaleClient methods** — `32d9463` (feat)
2. **Task 2: Wire engine dual write — TimescaleDB insertion in _recompute_mvs()** — `cda308b` (feat)
3. **Task 3: Wire TimescaleClient into engine creation in main.py lifespan** — `b40d85f` (feat)

## Files Created/Modified

- `data/storage/migrations/003_mve_history.sql` - New migration: mve_history hypertable DDL with compression and retention policies
- `data/storage/timescale.py` - Added insert_mve_history() and get_mve_history() methods to TimescaleClient
- `variance/engine.py` - Added timescale parameter, dual write in _recompute_mvs(), startup replay method, replay call in start()
- `api/main.py` - Pass ctx.db as timescale= parameter to MarketVarianceEngine constructor

## Decisions Made

- **Dimension pruning:** Stored dimensions are pruned to 4 fields (name, score, weight, is_stale) to keep JSONB compact — detail/collected_at are available in Redis cache if needed
- **chronological ordering:** get_mve_history() returns entries in chronological order (reversed from time DESC query) — ready for sequential replay to Redis list
- **duck-typing for timescale param:** Uses Any type hint to avoid module-level import of TimescaleClient, matching config pattern
- **startup replay bounded:** Limited to 1000 entries via SQL LIMIT — replay runs as asyncio.create_task so engine startup is never blocked (T-09-08)

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface

All mitigations from the plan's threat register are implemented:

| Threat ID | Category | Mitigation | Status |
|-----------|----------|------------|--------|
| T-09-07 | Tampering | Dimensions pruned to 4 fields; parameterized query — no SQL injection | ✅ |
| T-09-08 | Denial of Service | Bounded to 1000 entries; asyncio.create_task — non-blocking | ✅ |
| T-09-09 | Availability | try/except with logger.exception — non-critical path; engine continues | ✅ |
| T-09-10 | Info Disclosure | Accepted — MVS scores are non-sensitive aggregate data | ✅ |

## Issues Encountered

None

## User Setup Required

None — no external service configuration required. The migration will be applied during TimescaleClient.initialize() on next API startup.

## Next Phase Readiness

- mve_history hypertable ready for MVS persistence — backtesting (09-04) can query it for historical analysis
- Dual write path ready for integration test verification (09-05)
- Verifier can check: migration file schema, TimescaleClient method signatures, engine param acceptance, Redis replay logic

## Self-Check: PASSED

- ✅ `data/storage/migrations/003_mve_history.sql` — exists
- ✅ `data/storage/timescale.py` — exists
- ✅ `variance/engine.py` — exists
- ✅ `api/main.py` — exists
- ✅ Commit `32d9463` — migration + TimescaleClient methods
- ✅ Commit `cda308b` — engine dual write + startup replay
- ✅ Commit `b40d85f` — api/main.py lifespan wiring

---

*Phase: 09-dqg-system-test*
*Completed: 2026-06-05*
