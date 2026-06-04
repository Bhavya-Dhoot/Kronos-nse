# Phase 2: VIX & Options Sentiment — Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the two most important NSE-specific dimension collectors: `VIXCollector` (60s poll) for India VIX volatility scoring and `OptionsCollector` (300s poll) for NIFTY options chain sentiment analysis. Both subclass `BaseVarianceCollector` from Phase 1.

Each collector implements `fetch()`, `parse()`, and `score()` using the established ABC interface. Scoring is deterministic linear heuristics, not ML.

</domain>

<decisions>
## Implementation Decisions

### NseIndiaApi Session Management
- **D-01:** Module-level singleton — single `NseIndiaApi` instance at `variance/collectors/_nse.py` lazily initialized on first use
- **D-02:** Both VIXCollector and OptionsCollector share the same instance
- **D-03:** Lazy init: `_get_nse_api()` function with `_nse_api: NseIndiaApi | None = None` module var. First call creates session, subsequent calls return cached.
- **D-04:** NseIndiaApi is a sync library — all calls wrapped in `asyncio.to_thread()` (per D-12 from Phase 1)

### VIX Collector
- **D-05:** `VIXCollector.fetch()` calls `await asyncio.to_thread(self._api.get_all_indices)` and extracts INDIAVIX from result
- **D-06:** VIX scoring: piecewise linear between 4 anchor points (VIX 30→-1.0, 20→-0.3, 15→0.0, 10→0.8), clamped to [-1.0, 1.0]. Below VIX 10 → 0.8 (no higher). Above VIX 30 → -1.0 (no lower).

### Options Collector
- **D-07:** `OptionsCollector.fetch()` calls `await asyncio.to_thread(self._api.get_option_chain, symbol="NIFTY")` and fetches full option chain
- **D-08:** Parse computes 4 metrics from the chain: PCR (total PE OI / total CE OI), Max Pain (simplified method — strike with highest total CE+PE OI), ATM IV (nearest ATM strike's implied volatility for CE and PE), OI concentration (top 5 strikes by total OI / total OI across all strikes)
- **D-09:** Max Pain uses the simplified method (already proven in `scripts/tui_lib/fetcher.py:155-164`) — strike with the highest total CE+PE open interest. This is the standard market convention.
- **D-10:** Options scoring formula: base score from PCR mapped to [-0.6, +0.6] (PCR 0.5→-0.6, PCR 1.0→0.0, PCR 1.5→+0.4, PCR 2.0→+0.6), then adjusted by max-pain distance: if spot is within 0.5% of max pain, score shifts bearish by 0.15; if spot > 2% above max pain, shift bullish by 0.15. ATM IV and OI concentration are included in `detail` but not used in scoring directly (used for context/display).
- **D-11:** `detail` dict includes: `pcr`, `max_pain`, `underlying_value`, `iv_ce`, `iv_pe`, `oi_concentration`, `spot_vs_max_pain_pct`, `strike_count`

### Claude's Discretion
- Test implementation details (assertions, fixtures, mock data)
- Exact NseIndiaApi method names (use actual library API surface — verify during implementation)
- Error handling messages and logging format (follow project's logzero/structlog pattern)
- File naming: `variance/collectors/vix_collector.py`, `variance/collectors/options_collector.py`, `variance/collectors/__init__.py` updated to export both
- NseIndiaApi init arguments (standard `NseIndiaApi()` — no auth required for public data)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Project overview, architecture decisions, key decisions log
- `.planning/REQUIREMENTS.md` §VIX Collector, §Options Collector — Exact requirement wording (VIX-01/02/03, OPT-01/02/03/04/05/06)
- `.planning/phases/01-scaffold-score/01-CONTEXT.md` — Phase 1 decisions (D-11 through D-14 for collector interface, D-12 for asyncio.to_thread pattern)

### Existing Code to Reference
- `variance/base_collector.py` — BaseVarianceCollector ABC (fetch/parse/score/poll interface)
- `variance/schemas.py` — ParseResult TypedDict (output type for all collectors)
- `scripts/tui_lib/fetcher.py:130-176` — Existing NSE options chain + VIX fetching (proven patterns for PCR, Max Pain, VIX extraction)
- `config/base.yaml` §variance — Poll intervals, dimension weights in config

### External Library
- `nse @ git+https://github.com/BennyThadikaran/NseIndiaApi.git` — NSE data source library (sync, manages own cookies/session)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseVarianceCollector` ABC in `variance/base_collector.py` — Both collectors subclass this
- `ParseResult` TypedDict in `variance/schemas.py` — Standard output format
- `scripts/tui_lib/fetcher.py:130-176` — Reference implementation for NSE options chain parsing (PCR, Max Pain, VIX extraction using httpx directly — useful as reference for expected data shapes)

### Established Patterns
- Sync libraries wrapped in `asyncio.to_thread()` (D-12, Phase 1)
- 5-error circuit-breaker with stale value fallback (D-13, D-14, Phase 1)
- Config values from `config/base.yaml` (poll_interval_seconds, weights)
- Tests use pytest with `@pytest.mark.asyncio` and `AsyncMock`

### Integration Points
- `variance/collectors/__init__.py` — Export both collectors for engine (Phase 6) to import
- `config/base.yaml` §variance.poll_interval_seconds.vix and options — Poll intervals
- Redis `mve:` key prefix (Phase 1 RedisCache methods) — Data persistence

</code_context>

<specifics>
## Specific Ideas

- VIX scoring curve: piecewise linear between anchors, clamped edges
- Max Pain: simplified method (strike with max total OI) — same as existing fetcher.py
- Options score: PCR-based with max-pain distance adjustment
- Single shared NseIndiaApi instance for all collectors using it

</specifics>

<deferred>
None — discussion stayed within phase scope.
</deferred>

---

*Phase: 02-vix-options*
*Context gathered: 2026-06-04*
