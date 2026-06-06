# Phase 9: DQG & System Test — Context

**Gathered:** 2026-06-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend DQG for MVE health check, add runtime config API for MVE tuning, create mve_history hypertable in TimescaleDB, build backtesting script comparing MAE with/without MVE modifications, and run full integration tests covering MVE lifecycle end-to-end.

This is the final v1 phase — after this, all 62 v1 requirements are covered and the system is ready for live validation.

</domain>

<decisions>
## Implementation Decisions

### DQG-01: check_mve_health() Design
- **D-01:** Warning-level check (non-critical, same severity as volume_sanity, corporate_action_suspected)
- **D-02:** Reports 3 fields:
  - `active_dimensions: str` — e.g., "4/6" (count of dimensions with data vs total)
  - `stale_dimensions: list[str]` — dimension names where last poll >30s ago
  - `circuit_broken_dimensions: list[str]` — dimensions in circuit-breaker state (5 consecutive errors)
- **D-03:** Fits inline with existing DQG checks dict — add check function to `checks.py`, import in `gate.py`, execute in `run()` sequence
- **D-04:** Check passes if active_dimensions >= 3 (matches engine ready gate from Phase 6 D-11), warns if < 3 or any circuit-broken dimensions

### DQG-02: PATCH /api/v1/variance/config
- **D-05:** Ephemeral in-memory overlay — updates apply to a runtime overlay dict, not written to YAML. Restart restores defaults.
- **D-06:** Hot-reloadable fields: weights (per-dimension), modification factors (temperature_base, band_width_per_vix_point, signal_base_threshold, etc.), poll_intervals (per-collector)
- **D-07:** Validation: validate all fields before applying any. Reject with 422 + detail if any value is invalid. Positive numbers for weights/intervals, ranges for factors.
- **D-08:** Response: returns full merged config snapshot (base + overlay) after successful update
- **D-09:** Endpoint: new router `api/routes/variance_config.py` with `PATCH /api/v1/variance/config`, registered in `api/main.py`
- **D-10:** Engine reads from merged config via a runtime config getter that checks overlay first, falls back to base config

### DQG-03: mve_history Hypertable
- **D-11:** New migration `data/storage/migrations/003_mve_history.sql`
- **D-12:** Schema columns:
  - `time` TIMESTAMPTZ NOT NULL — when the MVS was computed
  - `composite` FLOAT8 NOT NULL
  - `market_state` TEXT NOT NULL
  - `vix_value` FLOAT8
  - `dimensions` JSONB — array of dimension scores (name, score, weight, is_stale)
  - `temperature_adjustment` FLOAT8
  - `directional_bias` FLOAT8
  - `band_width_multiplier` FLOAT8
  - `signal_threshold` FLOAT8
- **D-13:** Hypertable with `chunk_time_interval = INTERVAL '1 day'`
- **D-14:** Compression after 7 days, retention 30 days (from config `mve_history.retention_days`)
- **D-15:** Index on `(time DESC)` for efficient history queries
- **D-16:** Dual write strategy: engine writes every MVS recompute to both Redis (fast cache, existing mve:mvs:history list) and TimescaleDB (mve_history hypertable)
- **D-17:** On engine startup, if Redis history is empty, replay from TimescaleDB to Redis (last 1000 entries)

### DQG-04: Backtesting with/without MVE
- **D-18:** Single backtest run — get predictions once, then compare modified vs unmodified by applying `modify_post_inference()` on the result
- **D-19:** Metrics: MAE of pred_close (primary), directional accuracy, average confidence
- **D-20:** Compare three states:
  - Unmodified (raw prediction output)
  - Modified with MVE (modifier applied)
  - Difference (modified - unmodified) — positive means MVE improved accuracy
- **D-21:** Symbols and timeframes from existing backtest config
- **D-22:** Output: console table + JSON file in backtest output directory

### DQG-05: Integration Tests
- **D-23:** Async integration tests (not TestClient) with full mocked collectors using AsyncMock
- **D-24:** Test cases:
  - Engine start → dimension arrives → MVS computed and published
  - Fear state raises signal_threshold (mock dimensions to push composite to fear range)
  - Degraded mode: stop enough collectors, verify engine is_ready=False but continues serving last MVS
  - Engine injection: verify PredictionModifier reads MVS correctly from running engine
  - check_mve_health() returns correct data for healthy/degraded states
- **D-25:** Direct engine control — create MarketVarianceEngine with mocked collectors, call start(), inject dimension updates manually via the callback

### Claude's Discretion
- Exact PATCH field validation rules and error messages
- TimescaleDB replay implementation (batch size, error handling)
- Backtest output formatting details
- Test fixture details for mock collectors
- Migration SQL index types and compression policy specifics
- How the engine's runtime config getter checks overlay vs base config
- Whether PATCH accepts partial updates or requires full payload

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Project overview, architecture decisions
- `.planning/REQUIREMENTS.md` §DQG Extension & Config — DQG-01 through DQG-05 exact requirement wording
- `.planning/ROADMAP.md` §Phase 9 — Success criteria, 7 acceptance checks

### Prior Phase Decisions
- `.planning/phases/06-mve-orchestrator/06-CONTEXT.md` — Phase 6 decisions (engine lifecycle, ready gate D-11: 3 of 6 dimensions, MVS publish on 1% change)
- `.planning/phases/07-prediction-modifier/07-CONTEXT.md` — Phase 7 decisions (modifier injection, modify_post_inference)
- `.planning/phases/08-api-ui/08-CONTEXT.md` — Phase 8 decisions (Redis mve:mvs:history, D-10 capped 1000 entries, API patterns)

### Existing Code Patterns
- `data/quality/gate.py` — DataQualityGate with run(), assert_pass(), DQGReport dataclass
- `data/quality/checks.py` — Individual check functions returning `{"passed": bool, "critical": bool, "detail": str}`
- `data/storage/migrations/001_initial_schema.sql` — Hypertable creation pattern (chunk_time_interval, compression, segmentby)
- `data/storage/migrations/002_signals_and_ledger.sql` — Migration numbering pattern
- `config/base.yaml` §variance — Existing MVE config (weights, modification factors, poll intervals, engine settings, mve_history.retention_days)
- `backtest/runner.py` — BacktestRunner with MAE/directional accuracy computation
- `api/routes/data_quality.py` — Existing DQG REST endpoints under /api/v1/dqg/
- `api/dependencies.py` — Dependency injection pattern for app.state access
- `variance/engine.py` — MarketVarianceEngine with is_ready, last_mvs, _scores, _collectors
- `variance/modifier.py` — PredictionModifier.modify_post_inference() to toggle for comparison

### Test Patterns
- `tests/data_quality/conftest.py` — Mock helpers for DQG tests
- `tests/data_quality/test_dqg_checks.py` — Individual check test pattern
- `tests/integration/test_variance_api.py` — MockMVE pattern for variance API tests

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/quality/checks.py` — check function pattern (return dict with passed/critical/detail)
- `data/quality/gate.py` — DataQualityGate class, DQGReport dataclass, run() sequence
- `data/storage/migrations/001_initial_schema.sql` — Hypertable creation with compression policy
- `backtest/runner.py` — Existing backtesting infrastructure (symbol iteration, MAE computation)
- `variance/engine.py` — MarketVarianceEngine (is_ready, last_mvs, _scores, _collectors)
- `variance/modifier.py` — PredictionModifier.modify_post_inference() for toggle comparison
- `config/base.yaml` §variance — Complete MVE config section with all weights/factors/intervals
- `api/routes/variance.py` — Existing variance router (GET endpoints from Phase 8)
- `tests/integration/test_variance_api.py` — MockMVE pattern for test fixtures

### Established Patterns
- DQG checks: standalone function in checks.py → import in gate.py → execute in run()
- TimescaleDB migrations: sequential .sql files in data/storage/migrations/
- API routers: APIRouter in api/routes/ → register in api/main.py
- Config: loaded once from YAML at startup via load_config()
- Engine mocking: AsyncMock with controlled is_ready/last_mvs/_sodesc attributes

### Integration Points
- `data/quality/checks.py` — Add check_mve_health() function
- `data/quality/gate.py` — Import and call check_mve_health() in run()
- `api/routes/variance_config.py` — New router for PATCH /api/v1/variance/config
- `api/main.py` — Register new router + inject MVE config overlay into app.state
- `data/storage/migrations/003_mve_history.sql` — New migration
- `data/storage/timescale.py` — TimescaleClient methods for mve_history insert/query
- `variance/engine.py` — Dual write (Redis + TimescaleDB) in _recompute_mvs(), runtime config overlay
- `backtest/runner.py` — MVE comparison logic
- `tests/integration/test_variance_api.py` — New test class for DQG-05 integration tests

</code_context>

<specifics>
## Specific Ideas

- check_mve_health(): warning check that passes if active_dimensions >= 3. Stale list shows names + seconds since last poll. Circuit-broken shows names after 5 consecutive errors per BaseVarianceCollector.
- PATCH /api/v1/variance/config: body example `{"weights": {"vix": 0.30, "options": 0.15}}`. Returns `{"status": "ok", "config": {...merged...}}`. Validate: weights must sum to reasonable range, intervals must be >= 10s.
- mve_history: time column is the recompute timestamp. dimensions stored as JSONB array to avoid schema changes when dimensions change. Retention and compression match existing candles pattern.
- Backtesting: engine_result_to_prediction() from api/helpers.py can produce comparable outputs. The "difference" metric shows whether MVE moved predictions closer to actuals.
- Integration tests: create MockMVE engine that exposes is_ready/last_mvs/_scores and lets tests inject dimension data programmatically.

</specifics>

<deferred>
None — all discussed areas stayed within phase scope.
</deferred>

---

*Phase: 09-dqg-system-test*
*Context gathered: 2026-06-05*
