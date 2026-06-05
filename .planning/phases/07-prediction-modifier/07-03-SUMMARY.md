---
phase: 07-prediction-modifier
plan: 03
subsystem: signal
tags: [signal-threshold, confidence-override, mvs, headless-runner, api-helpers]

requires:
  - phase: 07-02
    provides: KronosEngine._mve attribute, PredictionModifier class

provides:
  - Dynamic signal_threshold for direction classification in HeadlessRunner
  - MVS confidence_override propagation through both HeadlessRunner and API helpers

affects:
  - 07-prediction-modifier (entire phase)
  - api routes that call engine_result_to_prediction

tech-stack:
  added: []
  patterns:
    - "MVS helper methods on HeadlessRunner with safe getattr fallback pattern"
    - "Optional mve_confidence parameter in compute_confidence() for override chain"

key-files:
  modified:
    - headless/runner.py
    - api/helpers.py

key-decisions:
  - "HeadlessRunner._get_mvs_threshold() and _get_mvs_confidence_override() use getattr chain for safe fallback when MVE not configured"
  - "_compute_signal() changed from staticmethod to instance method to access engine MVS"
  - "compute_confidence() accepts optional mve_confidence parameter for override chain"
  - "Direction unchanged by confidence override — only confidence label changes (D-21)"

requirements-completed: [MOD-04, MOD-05, MOD-08]

duration: 8min
completed: 2026-06-05
---

# Phase 7: PredictionModifier — Plan 03 Summary

**Dynamic signal_threshold from MVS for direction classification and confidence_override propagation through HeadlessRunner and API helpers**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-05T05:10:00Z
- **Completed:** 2026-06-05T05:18:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- HeadlessRunner._compute_signal() now reads dynamic signal_threshold from engine MVS instead of hardcoded 0.005 (D-22/D-23)
- MVS confidence_override applied after computed confidence in HeadlessRunner (D-19/D-20)
- API helpers compute_confidence() checks mve_confidence flag for override chain (D-20)
- Safe fallback to defaults when MVE not configured or not ready

## Task Commits

Each task was committed atomically:

1. **Task 1: Update HeadlessRunner._compute_signal()** - `e061db4` (feat)
2. **Task 2: Update API helpers compute_confidence()** - `29d22cd` (feat)

## Files Created/Modified

- `headless/runner.py` - Added `_get_mvs_threshold()`, `_get_mvs_confidence_override()` helpers; changed `_compute_signal()` from staticmethod to instance method; replaced hardcoded 0.005 with dynamic threshold; added confidence override
- `api/helpers.py` - Added optional `mve_confidence` parameter to `compute_confidence()`; wired it through `engine_result_to_prediction()`

## Decisions Made

- **`_compute_signal` instance method:** Changed from `@staticmethod` to instance method to access `self._engine._mve` for MVS data. All call sites already pass `self` implicitly.
- **Safe getattr fallback:** Both MVS helper methods use `getattr(self._engine, "_mve", None)` chain so they degrade gracefully when MVE is not configured or not ready.
- **Direction unchanged by confidence override:** The direction (BULLISH/BEARISH/NEUTRAL) is computed from expected move vs threshold and is not affected by the confidence override — only the confidence label is replaced (per D-21).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None

## Self-Check: PASSED

All files exist and all commits are accounted for.

## Next Phase Readiness

- HeadlessRunner and API helpers are ready for MVS-driven signal adjustments
- Phase 7 integration (modifier → engine → runner → API) is complete
- Next step: end-to-end testing and verification

---

*Phase: 07-prediction-modifier*
*Completed: 2026-06-05*
