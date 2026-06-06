---
phase: 03-institutional-flow
plan: 01
subsystem: MVE - FII/DII Collector
tags:
  - institutional
  - collector
  - fii-dii
  - angel-client
dependency_graph:
  requires:
    - variance/schemas.py (ParseResult TypedDict)
    - variance/base_collector.py (BaseVarianceCollector ABC)
    - variance/collectors/_nse.py (NseIndiaApi singleton + _fetch_fii_dii_data)
    - data/collector/angel_client.py (AngelOneClient class)
  provides:
    - FIIDIICollector for institutional sentiment
    - _angel.py shared AngelOneClient singleton
    - _fetch_fii_dii_data() in _nse.py
  affects:
    - variance/collectors/__init__.py (new export)
    - variance/collectors/_angel.py (new singleton wrapper)
tech-stack:
  added:
    - FIIDIICollector: 1800s poll-interval institutional flow collector
    - AngelOneClient lazy singleton: config-injection pattern via _set_angel_config/_get_angel_client
key-files:
  created:
    - variance/collectors/_angel.py
    - variance/collectors/fii_dii_collector.py
    - variance/tests/test_fii_dii_collector.py
  modified:
    - variance/collectors/_nse.py
    - variance/collectors/__init__.py
decisions:
  - "AngelOneClient uses lazy singleton pattern (import-time safe) like NseIndiaApi"
  - "_set_angel_config must be called before first _get_angel_client — RuntimeError if not"
  - "FII/DII combined raw = FII*0.7 + DII*0.3 per D-11"
  - "Score = combined/4000.0 clamped to [-1.0, 1.0]"
  - "parse() handles 3 response shapes: simple dict (fii_net/dii_net), nested dict (fii/dii objects), and fallback key scan"
metrics:
  duration: ~8 minutes
  completed_date: 2026-06-04
  tasks_completed: 6
  tasks_total: 6
  tests_passed: 24
  tests_failed: 0
  commits:
    - 94bb92a: create AngelOneClient singleton wrapper
    - a18156b: add _fetch_fii_dii_data with method fallback
    - 33a693f: create FIIDIICollector
    - 7449278: register FIIDIICollector in __init__ exports
    - fbea66f: add FIIDIICollector tests (24 tests)
---

# Phase 3 Plan 1: AngelOneClient singleton + FIIDIICollector + tests

Built the shared `AngelOneClient` singleton in `_angel.py` following the same lazy-init pattern as `_nse.py`, added `_fetch_fii_dii_data()` to the NSE singleton with method-name fallback, and created `FIIDIICollector` — a 1800s-poll-interval institutional flow collector that combines FII (70%) and DII (30%) net flows into a `[-1.0, 1.0]` sentiment score.

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| `_angel.py` created with module-level `None` + `_set_angel_config`/`_get_angel_client` | ✅ |
| `_fetch_fii_dii_data()` appended to `_nse.py` with method-name fallback | ✅ |
| FIIDIICollector extends BaseVarianceCollector with fetch/parse/score | ✅ |
| Combined raw = FII*0.7 + DII*0.3, direction = sign, magnitude = min(1.0, abs/4000) | ✅ |
| Score = combined/4000.0 clamped to [-1.0, 1.0] | ✅ |
| Parse handles simple dict, nested dict, and fallback key scan | ✅ |
| FIIDIICollector exported from `__init__.py` | ✅ |
| 24 tests passing | ✅ 24/24 |

## Implementation Details

### `_angel.py` — AngelOneClient Singleton

- Module-level `_angel_client: AngelOneClient | None = None` (lazy init)
- `_angel_config: dict[str, Any] | None = None` stores config for first init
- `_set_angel_config(config)` — injects config, raises `RuntimeError` if client already initialized
- `_get_angel_client()` — creates `AngelOneClient(_angel_config)` on first call, returns cached thereafter
- Import error handled via try/except (same pattern as `_nse.py`)

### `_fetch_fii_dii_data()` in `_nse.py`

- Tries three method names on the NseIndiaApi instance: `get_fii_dii_data`, `get_fii_dii_net_flows`, `get_fii_dii`
- Falls back to `NotImplementedError` with descriptive message
- All calls wrapped in `asyncio.to_thread()` per D-04

### `FIIDIICollector`

- `name="fii_dii"`, `poll_interval=1800` (30 min)
- **`fetch()`** — delegates to `_fetch_fii_dii_data()`
- **`parse()`** — private `_extract_net()` with 3 resolution strategies:
  1. Exact key (`{prefix}_net`)
  2. Nested object (`{prefix}` → `{"net": ...}`)
  3. Fallback key scan (any key containing prefix)
- **`score()`** — `combined / 4000.0`, clamped to `[-1.0, 1.0]` per D-11
- **`_to_float()`** — safe float conversion returning `None` on failure

## Artifacts

- `variance/collectors/_angel.py` — AngelOneClient lazy singleton (52 lines)
- `variance/collectors/_nse.py` — added `_fetch_fii_dii_data()` (18 new lines)
- `variance/collectors/fii_dii_collector.py` — FIIDIICollector class (119 lines)
- `variance/collectors/__init__.py` — added FIIDIICollector export (3 lines changed)
- `variance/tests/test_fii_dii_collector.py` — 24 tests across 4 test classes (188 lines)

## Test Results

```
variance/tests/test_fii_dii_collector.py::TestFetch::test_fetch_calls_fii_dii_api PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_simple_dict PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_nested_dict PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_missing_data_raises PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_non_dict_raises PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_empty_dict_raises PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_direction_positive PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_direction_negative PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_direction_zero PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_magnitude_scaling PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_magnitude_partial PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_none_values_raise[100.0-None] PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_none_values_raise[None-100.0] PASSED
variance/tests/test_fii_dii_collector.py::TestParse::test_parse_none_values_raise[None-None] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[4000.0-0.0-0.7] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[-3000.0-1000.0--0.45] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[2000.0-1000.0-0.425] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[-5000.0--2000.0--1.0] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[6000.0-3000.0-1.0] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[0.0-0.0-0.0] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[10000.0-5000.0-1.0] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_parametrized[-8000.0--5000.0--1.0] PASSED
variance/tests/test_fii_dii_collector.py::TestScore::test_score_with_nested PASSED
variance/tests/test_fii_dii_collector.py::TestIntegration::test_poll_returns_parse_result_with_score PASSED
============================== 24 passed in 1.81s ==============================
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All created files verified:
- `variance/collectors/_angel.py` — exists ✅
- `variance/collectors/fii_dii_collector.py` — exists ✅
- `variance/tests/test_fii_dii_collector.py` — exists ✅
- `variance/collectors/_nse.py` — has `_fetch_fii_dii_data` ✅
- `variance/collectors/__init__.py` — has `FIIDIICollector` import ✅
- Commit `94bb92a` — found ✅
- Commit `a18156b` — found ✅
- Commit `33a693f` — found ✅
- Commit `7449278` — found ✅
- Commit `fbea66f` — found ✅
