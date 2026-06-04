---
phase: 03-institutional-flow
plan: 02
subsystem: MVE - Aggregators
tags:
  - institutional
  - aggregator
  - dimension-score
dependency_graph:
  requires:
    - variance/schemas.py (DimensionScore TypedDict)
  provides:
    - InstitutionalDimensionAggregator for MarketVarianceScore.build()
  affects:
    - variance/aggregators (new subpackage)
tech-stack:
  added:
    - InstitutionalDimensionAggregator: standalone dataclass-like aggregator
key-files:
  created:
    - variance/aggregators/__init__.py
    - variance/aggregators/institutional.py
    - variance/tests/test_aggregators.py
  modified: []
decisions:
  - "Aggregator is a standalone class (not a collector) — no fetch/parse/poll contract"
  - "INSTITUTIONAL_WEIGHT = 0.25 exposed as module constant for config reuse"
  - "Weights stored as module constants (FII_DII_WEIGHT=0.7, OI_WEIGHT=0.3) for transparency"
  - "Partial data reduces active_weight proportionally rather than treating as stale"
  - "Both None → is_stale=True, active_weight=0.0, score=0.0"
metrics:
  duration: ~8 minutes
  completed_date: 2026-06-04
  tasks_completed: 3
  tasks_total: 3
  tests_passed: 18
  tests_failed: 0
  commits:
    - 2394377: InstitutionalDimensionAggregator with weight config and partial-data handling
    - 39285b1: 14 tests covering combination, partial data, clamping, detail, stale flags
---

# Phase 3 Plan 2: InstitutionalDimensionAggregator + tests

Built the `variance/aggregators/` subpackage and `InstitutionalDimensionAggregator` class that combines FII/DII (70%) and OI (30%) flow scores into a single `DimensionScore` weighted at 0.25 in the MVE composite. Handles partial data, stale flags, clamping, and rounding.

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| `variance/aggregators/` subpackage exists with `__init__.py` | ✅ |
| InstitutionalDimensionAggregator combines FII/DII (0.7) + OI (0.3) | ✅ |
| Aggregator is a standalone class (not a collector) | ✅ |
| compute() returns DimensionScore TypedDict | ✅ |
| 2+ tests pass | ✅ 18/18 |

## Implementation Details

- **Module constants:** `INSTITUTIONAL_WEIGHT=0.25`, `FII_DII_WEIGHT=0.7`, `OI_WEIGHT=0.3`
- **Both scores present:** weighted average, `active_weight=1.0`
- **Only FII/DII:** score = fii_dii, `active_weight=0.7`
- **Only OI:** score = oi, `active_weight=0.3`
- **Neither:** score=0.0, `is_stale=True`, `active_weight=0.0`
- **Clamping:** score clamped to [-1.0, 1.0]
- **Precision:** score rounded to 4 decimal places
- **Detail dict includes:** fii_dii_score, oi_score, fii_dii_stale, oi_stale, active_weight, fii_dii_weight, oi_weight
- **collected_at:** ISO-8601 UTC timestamp

## Artifacts

- `variance/aggregators/__init__.py` — package marker, exports `InstitutionalDimensionAggregator`
- `variance/aggregators/institutional.py` — `InstitutionalDimensionAggregator` class (109 lines)
- `variance/tests/test_aggregators.py` — 14 test methods + parametrized matrix (147 lines, 18 test cases)

## Test Results

```
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_combines_both_scores PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_combines_opposite_signs PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_fii_dii_only PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_oi_only PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_both_none_returns_zero PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_partial_data_not_stale PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_clamping_above_1 PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_clamping_below_neg1 PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_detail_contains_all_keys PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_stale_flags_passed_through PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_collected_at_is_isoformat PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_score_rounded_to_4_places PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_default_constructor_no_side_effects PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_parametrized_combinations[0.5-0.5-0.5] PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_parametrized_combinations[1.0--0.5-0.55] PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_parametrized_combinations[-0.3-0.1--0.18] PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_parametrized_combinations[0.0-1.0-0.3] PASSED
variance/tests/test_aggregators.py::TestInstitutionalDimensionAggregator::test_parametrized_combinations[-0.8--0.2--0.62] PASSED
============================== 18 passed in 2.71s ==============================
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All created files verified:
- `variance/aggregators/__init__.py` — exists ✅
- `variance/aggregators/institutional.py` — exists ✅
- `variance/tests/test_aggregators.py` — exists ✅
- Commit `2394377` — found ✅
- Commit `39285b1` — found ✅
