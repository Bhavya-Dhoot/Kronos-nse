# Plan 01-02 Summary — MVE Schemas, Scoring & Redis Integration

## Files created

### `variance/schemas.py`
- `ParseResult` — TypedDict for standardized collector parse output
- `DimensionScore` — TypedDict for individual dimension scores

### `variance/score.py`
- `MarketState` enum — PANIC, FEAR, UNCERTAIN, BULL_RUN, NEUTRAL
- `MarketVarianceScore` dataclass:
  - `build()` classmethod — weighted composite with stale-dimension halving
  - `_classify_state()` — VIX + composite-based market state classification
  - Computed properties: `temperature_adjustment`, `directional_bias`, `band_width_multiplier`, `signal_threshold`, `confidence_override`
  - `to_dict()` — full serialization

## Files modified

### `data/storage/redis_cache.py`
- Added `_MVE_KEY = "mve:{key}"` constant
- Added `set_mve()` — store MVE data with default 60s TTL
- Added `get_mve()` — retrieve MVE data
- Added `publish_mvs()` — publish MVS dict to `mve:mvs:updates` channel

## Verification results

| Check | Result |
|-------|--------|
| `from variance.schemas import ParseResult, DimensionScore` | OK |
| `from variance.score import MarketVarianceScore, MarketState` | OK |
| RedisCache has set_mve / get_mve / publish_mvs methods | OK (static) |
| MarketVarianceScore.build([], vix_value=25).to_dict() serializable | OK |
