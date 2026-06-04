# Phase 1: Scaffold & Score Foundation — Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Create the `variance/` directory tree with all subdirectories and `__init__.py` files, install MVE dependencies, add MVE configuration to the existing config system, build the `BaseVarianceCollector` abstract base class, and implement the `MarketVarianceScore` dataclass with full test coverage.

This is pure foundation — no collector logic, no engine, no modification. Every downstream MVE phase depends on these being correct.

</domain>

<decisions>
## Implementation Decisions

### Config Structure
- **D-01:** MVE config lives in `config/base.yaml` — extend the existing file with a `variance:` section
- **D-02:** Use same YAML env var interpolation pattern as rest of the project (`${VAR_NAME:default}`)
- **D-03:** Config structure follows the spec: `variance.enabled`, `variance.poll_interval_seconds`, `variance.weights.{dimension}`, `variance.modification.{settings}`, `variance.gift_nifty.{urls}`

### Redis Integration
- **D-04:** Use existing `RedisCache` class directly (`data/storage/redis_cache.py`) — no MVE-specific wrapper
- **D-05:** Key namespace: `mve:{dimension}` (e.g., `mve:vix`, `mve:options`, `mve:mvs`)
- **D-06:** Composite MVS published to `mve:mvs` key with TTL from config (`variance.cache_ttl_seconds`)
- **D-07:** Dimension history stored at `mve:{name}:history:{timestamp}` (for later time-series queries)

### Dependency Management
- **D-08:** All MVE deps added directly to `pyproject.toml` in `[project]dependencies`
- **D-09:** Use `pandas-ta` instead of `ta-lib` to avoid C header compilation requirement
- **D-10:** Dependencies to add: `nse @ git+https://github.com/BennyThadikaran/NseIndiaApi.git`, `yfinance>=0.2.40`, `scrapling>=0.4.0`, `playwright>=1.40`, `pandas-ta>=0.3.14b`

### Collector Interface Design
- **D-11:** `BaseVarianceCollector` abstract class with `fetch()`, `parse()`, `score()` abstract methods and concrete `poll()` method
- **D-12:** Sync libraries (NseIndiaApi, yfinance) called via `asyncio.to_thread()` — no separate async wrapper
- **D-13:** Circuit-breaker at 5 consecutive errors — after 5th failure, `is_available` returns False
- **D-14:** Stale values returned on error (not None) — the `is_stale` flag on the result signals freshness

### MarketVarianceScore API
- **D-15:** Implement all 5 derived properties as specified: `temperature_adjustment`, `directional_bias`, `band_width_multiplier`, `signal_threshold`, `market_state`
- **D-16:** Market state classification matches spec: FEAR (VIX>22 & composite<-0.4), PANIC (VIX>28), BULL_RUN (VIX<14 & composite>0.4), etc.
- **D-17:** Stale dimensions get half weight in composite calculation
- **D-18:** Standardized parse output schema shared by all collectors (raw_value, normalized, direction, magnitude, detail, source, as_of)

### Testing
- **D-19:** 8 unit tests for scoring math (composite weighting, stale handling, market state classification, all 5 derived properties)
- **D-20:** Use pytest — no additional test framework

### Claude's Discretion
- Exact directory tree structure (follows spec: `variance/collectors/`, `variance/tests/`)
- Test implementation details (assertions, fixtures, edge cases)
- Redis key TTL values (use config defaults, adjust if Redis constraints require)
- NseIndiaApi singleton management (module-level vs class-level initialization)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Spec
- `variance/__init__.py` — MVE directory scaffold (created in this phase, refer to PROMPT MVE-0 for structure)
- `config/base.yaml` — Extended with `variance:` section (see PROMPT MVE-0 for config structure)
- `data/storage/redis_cache.py` — Existing Redis async client to reuse

### Dependencies
- `pyproject.toml` — Existing deps, add MVE deps here
- `https://github.com/BennyThadikaran/NseIndiaApi` — NSE data source library
- `https://github.com/ranaroussi/yfinance` — Yahoo Finance data source

### Project Context
- `.planning/PROJECT.md` — Project overview and architecture
- `.planning/REQUIREMENTS.md` — Requirements for this phase: SCF-01/02/03/04, BASE-01/02/03/04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/storage/redis_cache.py` — `RedisCache(get, set, delete)` async Redis client with JSON serialization. Directly reusable for MVE storage. URL from `config.redis.url`.
- `config/base.yaml` — YAML config with env interpolation via `pyyaml`. Extend with `variance:` section.

### Established Patterns
- All config lives in a single `config/base.yaml` — extend this file
- Redis key convention: `{prefix}:{entity}:{qualifier}` — MVE uses `mve:{dimension}`
- All async I/O uses `asyncio` + `await` — sync calls wrapped in `asyncio.to_thread()`
- Tests in `tests/` using pytest

### Integration Points
- `variance/engine.py` (Phase 6) will import `BaseVarianceCollector` and `MarketVarianceScore`
- `variance/modifier.py` (Phase 7) will import `MarketVarianceScore` properties
- `config/base.yaml` `variance:` section will be read by engine config loader

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches for:
- Directory structure (PROMPT MVE-0 defines exact tree)
- Config section structure (PROMPT MVE-0 defines exact YAML)
- Base collector interface (PROMPT MVE-1 defines exact methods)
- Score dataclass (PROMPT MVE-1 defines exact properties and math)
- Test scenarios (PROMPT MVE-1 lists 8 test cases)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-scaffold-score*
*Context gathered: 2026-06-04*
