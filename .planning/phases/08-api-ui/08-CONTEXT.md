# Phase 8: API & UI — Context

**Gathered:** 2026-06-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose MVS through REST/WS API endpoints and build React dashboard with MVS gauge, market state badge, dimension bars, CandleChart MVS tint overlay, FEAR/PANIC banner, and DQG panel MVE status row. Frontend is greenfield — existing scaffold is bare Vite+TypeScript only.

API routes follow existing patterns (app.state DI, typed responses, router prefix/tags). WS follows existing ConnectionManager + Redis pub/sub pattern. MVE already initialized in lifespan across all modes (Phase 6 D-16).

</domain>

<decisions>
## Implementation Decisions

### UI Framework & Stack
- **D-01:** React + TypeScript for the frontend dashboard (not Vue, not vanilla TS)
- **D-02:** TradingView lightweight-charts for CandleChart rendering (not D3.js, not Canvas API)
- **D-03:** Frontend lives in `ui/` directory — rename existing `FModel Trainingkronos-nseui/` scaffold to `ui/`, add React + lightweight-charts dependencies

### MarketVariancePanel Layout
- **D-04:** MVS shown as an arc gauge (semi-circular, red-yellow-green gradient, needle indicator)
- **D-05:** Panel placed as right sidebar in the dashboard layout
- **D-06:** Five dimension bars shown as horizontal stacked bars within the sidebar panel, with dimension name, current score, and contribution to composite

### CandleChart MVS Tint & FEAR/PANIC
- **D-07:** MVS tint rendered as background gradient behind candlesticks (light green for bullish MVS → light red for bearish MVS)
- **D-08:** FEAR/PANIC states: thin red border (2px) around the chart area + "HIGH VOLATILITY" banner above the chart

### DQG Panel MVE Row
- **D-09:** Compact single row showing: active dimensions count (N/6), current MVS composite value, market state badge, last update time. Fits inline with existing DQG check rows.

### MVS History Storage (API-03)
- **D-10:** Redis key `mve:mvs:history` as a list, capped at 1000 entries, TTL 24 hours. Each entry is JSON with timestamp, composite score, and per-dimension scores.

### WebSocket Protocol (API-04)
- **D-11:** WS endpoint `WS /ws/variance` following existing typed message pattern: `{"type": "mvs_update", "payload": {...}}`
- **D-12:** Payload contains composite score, dimension scores, market state, timestamp. Pushed on every MVS recompute that passes the 1% change threshold.

### Claude's Discretion
- Exact Redis list operations (RPUSH + LTRIM for capping)
- WS message payload JSON field names
- Arc gauge implementation approach (SVG vs inline SVG vs CSS)
- React component hierarchy within MarketVariancePanel
- lightweight-charts React wrapper choice (direct DOM vs react-lightweight-charts)
- API schema Pydantic models for variance routes
- Color palette specifics for gauge, gradient, dimension bars
- How main.py serves static UI build files in VISUAL mode
- Exact CandleChart tint gradient opacity and positioning

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Project overview, architecture decisions
- `.planning/REQUIREMENTS.md` §API Routes & §UI Integration — API-01 through UI-05 exact requirement wording
- `.planning/ROADMAP.md` §Phase 8 — Success criteria, goal

### Prior Phase Decisions
- `.planning/phases/06-mve-orchestrator/06-CONTEXT.md` — Phase 6 decisions (MVE in lifespan, app.state.mve, Redis pub/sub on `mve:updates` channel)
- `.planning/phases/07-prediction-modifier/07-CONTEXT.md` — Phase 7 decisions (mve_confidence flag on prediction dict, signal_threshold)

### Existing Code Patterns to Follow
- `api/main.py` — FastAPI app factory, lifespan, CORS setup, router registration pattern
- `api/routes/predictions.py` — Endpoint pattern (typed responses, Query params, Depends, summary tags)
- `api/routes/websocket.py` — WebSocket endpoint pattern (ConnectionManager, Redis pub/sub, typed message format)
- `api/ws_manager.py` — ConnectionManager class (connect/disconnect/broadcast/redis listener lifecycle)
- `api/schemas.py` — Pydantic v2 model patterns (BaseModel, Field, response_model usage)
- `api/dependencies.py` — Dependency injection pattern (Annotated + Depends pulling from app.state)
- `api/helpers.py` — Existing helper functions (engine_result_to_prediction, compute_confidence)
- `config/base.yaml` §ui — Existing ui.websocket_url and ui.api_base_url config values
- `app/main.py` — FastAPI app module-level instance for uvicorn
- `headless/runtime.py` — ApplicationRuntime mode initialization (VISUAL/HEADLESS/PAPER/COLLECT)

### Existing UI Scaffold
- `FModel Trainingkronos-nseui/` — Bare Vite+TypeScript scaffold (to be renamed to `ui/`)
- `FModel Trainingkronos-nseui/package.json` — Current deps: typescript ~6.0.2, vite ^8.0.12

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `api/main.py` — CORS is already configured for `localhost:3000` (the Vite dev server default)
- `api/ws_manager.py` — ConnectionManager with Redis pub/sub bridging, reference-counted listeners
- `api/routes/websocket.py` — Pattern for WS endpoint: accept → register → listen → disconnect
- `api/dependencies.py` — Dependencies pulling from app.state (can add variance-specific dependencies)
- `api/schemas.py` — Pydantic models; add VarianceScoreResponse, DimensionDetailResponse, etc.
- `config/base.yaml` §ui — Websocket and API URLs already defined for UI config
- `app/main.py` — MVE initialized in lifespan, available as `app.state.mve` and `app.state.mve_redis`

### Established Patterns
- Router modules in `api/routes/` with `APIRouter(prefix=..., tags=...)` + registered in `api/main.py`
- WebSocket endpoints use ConnectionManager with Redis pub/sub listener tasks
- State accessed via `request.app.state.xxx` / `websocket.app.state.xxx`
- Response models defined in `api/schemas.py` using Pydantic v2 BaseModel
- FastAPI lifespan for startup/shutdown lifecycle management

### Integration Points
- `api/routes/variance.py` — New router file for /api/v1/variance/* endpoints
- `api/main.py` — Register new variance router + serve UI static files in VISUAL mode
- `api/schemas.py` — Add variance response models
- `api/dependencies.py` — Add MVE dependency if needed (or access directly via app.state)
- `api/ws_manager.py` — No changes needed (existing ConnectionManager handles WS)
- `variance/engine.py` — MarketVarianceEngine (source of MVS via last_mvs, is_ready)
- `FModel Trainingkronos-nseui/` → `ui/` — Rename and scaffold React + lightweight-charts
- `main.py` — UI-05: MVE already initialized in all modes via lifespan (may need serving static files)

</code_context>

<specifics>
## Specific Ideas

- MVS gauge: semi-circular arc, red (-1.0) → yellow (0.0) → green (+1.0), with needle pointing at current MVS
- CandleChart tint: subtle background gradient on the chart pane, opacity ~0.1 so candles remain visible
- FEAR/PANIC: 2px red border via CSS on chart container, "HIGH VOLATILITY" banner as sticky top bar
- DQG MVE row: compact, shows "3/6 active" badge, MVS value colored by state, last update as relative time
- WS message follows existing `{"type": "mvs_update", "payload": {...}}` pattern matching other WS endpoints
- Redis history capped at 1000 entries → represents ~17 hours at 1-min recompute rate, ~3 hours at 10s rate

</specifics>

<deferred>
None — all discussed areas stayed within phase scope.
</deferred>

---

*Phase: 08-api-ui*
*Context gathered: 2026-06-05*
