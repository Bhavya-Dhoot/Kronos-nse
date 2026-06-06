# Plan 02-01: NseIndiaApi Singleton + VIXCollector — Summary

**Status:** Complete

## Tasks
1. ✅ Create `variance/collectors/_nse.py` — NseIndiaApi singleton with lazy init, shared instance, async wrappers (_fetch_all_indices, _fetch_option_chain)
2. ✅ Create `variance/collectors/vix_collector.py` — VIXCollector subclassing BaseVarianceCollector, polls INDIAVIX via NseIndiaApi, piecewise linear scoring
3. ✅ Update `variance/collectors/__init__.py` — Exports VIXCollector
4. ✅ Create `variance/tests/test_vix_collector.py` — 13 tests

## Files Created/Modified
- `variance/collectors/_nse.py` (new)
- `variance/collectors/vix_collector.py` (new)
- `variance/collectors/__init__.py` (modified — added VIXCollector export)
- `variance/tests/test_vix_collector.py` (new)

## Verification
- ✅ 13/13 VIX collector tests passing
- ✅ VIX scoring anchors: 30→-1.0, 20→-0.3, 15→0.0, 10→0.8
- ✅ Clamping: below 10 → 0.8, above 30 → -1.0
- ✅ Linear interpolation verified at VIX 12.5 and 25.0
- ✅ Import guard for missing nse package (try/except pattern matching angel_client.py)

## Deviations
- Added import guard in `_nse.py` for missing `nse` package (production install will provide it)
- Added `__all__` export list to collectors/__init__.py alongside VIXCollector import
