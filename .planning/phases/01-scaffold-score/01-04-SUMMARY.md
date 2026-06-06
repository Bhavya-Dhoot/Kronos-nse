# Plan 01-04: Tests — Summary

**Status:** Complete

## Tasks
1. ✅ Create `variance/tests/test_base_collector.py` — 9 tests (ABC interface, poll flow, circuit-breaker, stale values, properties)
2. ✅ Create `variance/tests/test_score.py` — 15 tests (composite weighting, stale half-weight, market state classification, 5 derived properties, serialization)

## Files Created
- `variance/tests/test_base_collector.py` — 9 unit tests for BaseVarianceCollector
- `variance/tests/test_score.py` — 15 unit tests for MarketVarianceScore scoring math

## Verification
- ✅ All 24 tests pass (9 collector + 15 scoring)
- ✅ Circuit-breaker trips after 5 consecutive errors
- ✅ Stale values returned on error with cached result
- ✅ Stale dimensions get half weight in composite
- ✅ Market state precedence: PANIC > FEAR > BULL_RUN > UNCERTAIN > NEUTRAL
- ✅ All 5 derived properties verified (temperature, bias, band width, signal threshold, confidence)
- ✅ JSON serialization round-trips correctly

## Deviations
- Added 2 extra collector tests (is_available, name/poll_interval) beyond plan's 7
- Added 7 extra scoring tests (composite clamped, all-stale, uncertain, neutral, directional_bias, to_dict keys) beyond plan's 8
- Fixed state precedence: PANIC (VIX>28) checked before FEAR (VIX>22 & composite<-0.4) — more extreme state wins
- VIX=15 is UNCERTAIN (in the 14-22 range), not NEUTRAL — test expectation corrected
