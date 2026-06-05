# Phase 7: PredictionModifier — Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Build `PredictionModifier` — applies 5 layers of MVS-driven modification to Kronos predictions. Pre-inference: VIX-based temperature adjustment. Post-inference: directional bias with decay, band scaling, signal threshold adjustment, and confidence override. Integrates into `KronosEngine.predict()` and `HeadlessRunner._compute_signal()`.

All 5 MVS-derived properties already exist in `MarketVarianceScore` (score.py:75-103). The modifier consumes these properties — it does not recompute them.

</domain>

<decisions>
## Implementation Decisions

### Modifier Architecture (MOD-01, MOD-07)
- **D-01:** Standalone `PredictionModifier` class in `variance/modifier.py`
- **D-02:** Two public methods: `modify_pre_inference(temperature, mvs) → float` (temperature adjustment) and `modify_post_inference(prediction: dict, mvs) → dict` (all post-inference modifications)
- **D-03:** Class is injected into `KronosEngine.__init__()` as optional param `modifier: PredictionModifier | None = None`. If None, no modifications applied (existing behavior preserved).
- **D-04:** `PredictionModifier` holds a reference to `MarketVarianceEngine` (set via `set_mve(mve)` or constructor) to read current MVS when `modify_pre_inference()`/`modify_post_inference()` are called — no MVS passed as argument.

### Temperature Composition (MOD-01)
- **D-05:** Effective temperature = `max(regime_temp, base_temp + mve_adjustment)` where:
  - `regime_temp` = ContextBuilder's temperature_override (TRENDING=0.6, RANGING=0.7, VOLATILE=0.85) or model default (0.7) if no override
  - `base_temp` = model default temperature (0.7)
  - `mve_adjustment` = `mvs.temperature_adjustment` = `(vix - 15) * 0.015` if VIX > 15, else 0.0, capped at +0.3
- **D-06:** Example: VIX=25 (adjustment=+0.15), VOLATILE regime (0.85) → effective = max(0.85, 0.7+0.15) = max(0.85, 0.85) = 0.85
- **D-07:** Example: VIX=25 (adjustment=+0.15), TRENDING regime (0.6) → effective = max(0.6, 0.7+0.15) = max(0.6, 0.85) = 0.85 (MVE overrides trending)
- **D-08:** Example: VIX=12 (adjustment=0.0) → effective = max(regime_temp, 0.7+0.0) = regime-based (unchanged from current behavior)
- **D-09:** `modify_pre_inference()` reads current MVS and regime temp, computes effective temp, returns it. Called in `KronosEngine.predict()` before `self._predictor.predict(...)`.

### Directional Bias Mechanics (MOD-02)
- **D-10:** Only `pred_close` sequence is modified (Open, High, Low, Volume unchanged by bias)
- **D-11:** Bias application per bar: `shift_pct = mvs.directional_bias * bias_scale * 0.01` where `bias_scale` decays linearly from 1.0 (bar 0) to 0.5 (last bar)
- **D-12:** For bar `i` out of `N` total: `bias_scale = 1.0 - 0.5 * (i / (N - 1))`
- **D-13:** `pred_close[i] = pred_close[i] * (1.0 + shift_pct)` — multiplicative shift (positive bias raises closes, negative bias lowers)
- **D-14:** Example: composite=+0.5, pred_len=12. Bar 0: shift=0.5*1.0*0.01=0.005→+0.5%. Bar 11: shift=0.5*0.5*0.01=0.0025→+0.25%

### Band Scaling & OHLCV Constraints (MOD-03, MOD-06)
- **D-15:** Widen around midpoint: `mid = (high + low) / 2`, `new_high = mid + (high - mid) * band_width_multiplier`, `new_low = mid - (mid - low) * band_width_multiplier`
- **D-16:** Applied after directional bias, using `mvs.band_width_multiplier` (1.0 + (VIX-15)*0.008, or 1.0 if VIX≤15)
- **D-17:** OHLCV constraints enforced in `modify_post_inference()` after all modifications (bias + bands):
  - `new_high = max(new_high, open, close)` — high is highest
  - `new_low = min(new_low, open, close)` — low is lowest
  - Open and Close must be between High and Low
  - Volume unchanged and non-negative
- **D-18:** Application order: bias (shift pred_close) → bands (widen H/L) → constraints (clamp)

### Confidence Override (MOD-05)
- **D-19:** Dual path:
  - **Path 1 (PredictionModifier):** `modify_post_inference()` reads `mvs.confidence_override` and if not None, sets `prediction["mve_confidence"] = override` in the pred dict
  - **Path 2 (HeadlessRunner):** `_compute_signal()` reads MVS from engine and after computing its own confidence, overrides with `mvs.confidence_override` if set
- **D-20:** API helpers (`compute_confidence` in `api/helpers.py`) also check `mve_confidence` flag on the prediction dict and override if present — ensures API responses show correct confidence
- **D-21:** Direction is NOT affected by confidence override — direction remains based on expected move pct

### Signal Threshold for HeadlessRunner (MOD-08)
- **D-22:** HeadlessRunner reads MVS directly from engine: `self._engine.mve.last_mvs["signal_threshold"]` (or falls back to 0.005 if MVE not available/not ready)
- **D-23:** In `_compute_signal()`, replace hardcoded `0.005` with `signal_threshold` from MVS for direction classification
- **D-24:** The modifier does not set this on the prediction dict — HeadlessRunner reads MVS directly (coupling is acceptable — runner already owns the engine)

### File Organization
- **D-25:** `variance/modifier.py` — `PredictionModifier` class
- **D-26:** `model/engine.py` — `KronosEngine` updated to accept and use PredictionModifier in `predict()`
- **D-27:** `headless/runner.py` — `HeadlessRunner._compute_signal()` updated to read MVS signal_threshold and confidence_override
- **D-28:** `api/helpers.py` — `compute_confidence()` updated to check `mve_confidence` flag

### Claude's Discretion
- Exact constructor signature of PredictionModifier (MVE reference injection)
- Error handling when MVS is not ready (fallback to no-op)
- Logging level and messages
- Test implementation details (10 test cases per success criteria)
- Edge cases: VIX=None, composite=0.0, all modifications at boundary values
- How KronosEngine.predict() retrieves current MVS (from engine.mve or from modifier's internal reference)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Project overview, architecture decisions
- `.planning/REQUIREMENTS.md` §PredictionModifier — MOD-01 through MOD-08
- `.planning/ROADMAP.md` §Phase 7 — Success criteria, 9 acceptance checks

### Prior Phase Decisions
- `.planning/phases/06-mve-orchestrator/06-CONTEXT.md` — Phase 6 decisions (engine lifecycle, MVS access via app.state.mve, Prometheus)
- `.planning/phases/01-scaffold-score/01-CONTEXT.md` — Phase 1 decisions (MarketVarianceScore dataclass with derived properties)

### Existing Code to Reference
- `variance/score.py` — `MarketVarianceScore` with all 5 derived properties (temperature_adjustment, directional_bias, band_width_multiplier, signal_threshold, confidence_override)
- `model/engine.py` — `KronosEngine.__init__()`, `predict()` method (where modifier hooks in), `_df_to_result()`
- `model/context_builder.py:190-201` — Regime-based temperature_override logic (TRENDING=0.6, RANGING=0.7, VOLATILE=0.85)
- `headless/runner.py:188-238` — `HeadlessRunner._compute_signal()` (where signal_threshold replaces hardcoded 0.005 and confidence_override applies)
- `api/helpers.py:26-35` — `compute_confidence()` (where mve_confidence flag is checked)
- `model/predictor.py:87-152` — `KronosPredictorWrapper.predict()` — receives temperature, passes it as `T` to model
- `model/factory.py:22-35` — `InferenceContext` if modifier needs to be wired there
- `variance/engine.py` — `MarketVarianceEngine` with `is_ready`, `last_mvs` properties (source of MVS for modifier)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `MarketVarianceScore` with all 5 properties (score.py) — modifier reads these
- `KronosEngine.predict()` takes `temperature` param — modifier pre-adjusts it
- `HeadlessRunner._compute_signal()` — threshold + confidence logic to modify

### Established Patterns
- Standalone class in `variance/` with optional injection (same as MarketVarianceEngine in engine.py)
- Optional constructor params with None defaults (backward compatible when modifier absent)
- Async methods for lifecycle (same pattern as engine and collectors)

### Integration Points
- `variance/modifier.py` — New file, PredictionModifier class
- `model/engine.py` — Inject modifier in __init__, call in predict()
- `headless/runner.py` — Use MVS signal_threshold + confidence_override
- `api/helpers.py` — Check mve_confidence flag
- `config/base.yaml` — Optional: modification config (already has modification section)

</code_context>

<specifics>
## Specific Ideas

- Bias applied as multiplicative percentage shift on pred_close only (no OHLCV movement)
- Decay formula: `scale[i] = 1.0 - 0.5 * (i / (N-1))` — full at bar 0, half at last bar
- Temperature: MVE adjustment on top of max(regime, base) — ensures temperature only increases
- OHLCV constraints after all mods: high ≥ max(O,C), low ≤ min(O,C)
- Confidence override is dual-path — both in modifier flag AND in HeadlessRunner direct read — for defensive coverage
- Signal threshold replaces hardcoded 0.5% in HeadlessRunner with dynamic value from MVS

</specifics>

<deferred>
None — discussion stayed within phase scope.
</deferred>

---

*Phase: 07-prediction-modifier*
*Context gathered: 2026-06-04*
