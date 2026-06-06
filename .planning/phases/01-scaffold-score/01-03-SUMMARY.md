# Plan 01-03: BaseVarianceCollector ABC

## Built
- `variance/base_collector.py` — abstract base class for MVE dimension collectors

## What it provides
- `fetch()` / `parse()` / `score()` abstract methods subclasses must implement
- `poll()` — concrete method chaining fetch → parse → score with circuit-breaker (max_errors)
- `poll_loop()` — infinite async generator yielding results at `poll_interval`
- `is_available` property — checks error threshold
- Graceful degradation: returns stale data on failure if a previous success exists

## Verification
1. `from variance.base_collector import BaseVarianceCollector` → OK
2. `BaseVarianceCollector('test')` raises `TypeError` (ABC protection) → OK
3. `from variance import BaseVarianceCollector` (package export) → OK
