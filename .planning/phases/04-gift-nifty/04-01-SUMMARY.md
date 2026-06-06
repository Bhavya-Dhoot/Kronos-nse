---
phase: 04-gift-nifty
plan: 01
type: execute
subsystem: variance-collectors
tags: [gift-nifty, playwright, browser-singleton, angel-one-client]
dependency_graph:
  requires: [phase-01, phase-02, phase-03]
  provides: [GIFTNiftyCollector, get_previous_close, browser-singleton]
  affects: [04-02, phase-06-orchestrator, phase-07-prediction-modifier]
tech-stack:
  added:
    - playwright.async_api (browser automation for web scraping)
  patterns:
    - Lazy async singleton (_browser.py follows _nse.py / _angel.py pattern)
key-files:
  created:
    - variance/collectors/_browser.py
    - variance/collectors/gift_nifty_collector.py
  modified:
    - data/collector/angel_client.py
    - variance/collectors/__init__.py
    - config/base.yaml (verified, no changes needed)
decisions:
  - get_previous_close() added to AngelOneClient, returns float|None, never raises
  - Browser singleton in _browser.py lazily initialized on first _get_browser() call
  - GIFTNiftyCollector uses Groww.in primary, niftytrader.in fallback
  - Gap scoring: max(-1.0, min(1.0, gap_pct * 50)) per D-06
  - score returns 0.0 when prev_close unavailable per D-07
metrics:
  duration: 12m
  completed_date: 2026-06-04
---

# Phase 4 Plan 1: AngelOneClient.get_previous_close() + Playwright Browser Singleton + GIFTNiftyCollector

**One-liner:** Extended AngelOneClient with get_previous_close(), created Playwright browser singleton (_browser.py) and GIFTNiftyCollector with Groww/NiftyTrader scraping, gap computation, and linear scoring for GIFT Nifty pre-market indicator.

## Files Created/Modified

| File | Action | Lines | Description |
|------|--------|-------|-------------|
| `data/collector/angel_client.py` | Modified | +25 | Added `get_previous_close()` method — fetches last daily close via getCandleData, returns float\|None, never raises |
| `variance/collectors/_browser.py` | Created | 44 | Lazy async Playwright browser singleton (_get_browser / _close_browser), follows _nse.py pattern |
| `variance/collectors/gift_nifty_collector.py` | Created | 123 | GIFTNiftyCollector subclass of BaseVarianceCollector — fetches via Playwright, parses gap vs prev close, scores linearly |
| `variance/collectors/__init__.py` | Modified | +7 | Added `GIFTNiftyCollector` import and `__all__` export |
| `config/base.yaml` | Verified | — | gift_nifty section already present with primary_url, fallback_url, poll_interval=300 |

## Commit History

| Commit | Message |
|--------|---------|
| `d4431cb` | feat(04-01): add get_previous_close() to AngelOneClient |
| `61267c9` | feat(04-01): create Playwright browser singleton (_browser.py) |
| `1f46698` | feat(04-01): create GIFTNiftyCollector with Playwright-based scraping |
| `ea9339e` | feat(04-01): register GIFTNiftyCollector in collectors __init__.py |

## Implementation Details

### AngelOneClient.get_previous_close()
- Calls `self.get_historical(symbol_token, exchange, "1day", yesterday_start, yesterday_end)`
- Default token "99926000" for NIFTY 50 on NSE exchange
- Returns close from last row: `data[-1][4]` → float
- Returns None on empty data or parse error (never raises)

### Browser Singleton (_browser.py)
- Module-level `_browser: Browser | None = None` and `_playwright_instance`
- `_get_browser()` is async — launches headless Chromium on first call
- `_close_browser()` for clean shutdown
- Page creation/closure managed by callers (GIFTNiftyCollector)

### GIFTNiftyCollector
- **fetch()**: Gets browser → creates page → navigates to Groww primary → extracts number via regex → falls back to niftytrader.in → raises ValueError if both fail
- **parse()**: Extracts gift_nifty_value → gets prev_close via AngelOneClient → computes gap_pct = (gift - prev) / prev * 100 → builds ParseResult
- **score()**: `max(-1.0, min(1.0, gap_pct * 50))` — 0% gap→0.0, 1%→0.5, 2%→1.0 (capped). Returns 0.0 when gap_pct is None

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- ✓ `angel_client.py` syntax OK — contains `def get_previous_close`
- ✓ `_browser.py` syntax OK — 44 lines, exports `_get_browser` and `_close_browser`
- ✓ `gift_nifty_collector.py` syntax OK — 123 lines, GIFTNiftyCollector subclass of BaseVarianceCollector
- ✓ `__init__.py` exports `GIFTNiftyCollector`
- ✓ `config/base.yaml` has `gift_nifty` section with `primary_url` and `fallback_url`
