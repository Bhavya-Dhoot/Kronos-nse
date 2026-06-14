# Kronos NSE — Agent Memory File

## Project context
Financial market prediction system using Kronos-small (24.7M params) fine-tuned
on NSE OHLCV data from Angel One Smart API. Predicts candlesticks 5-60 bars ahead.
Target latency: < 500ms from candle close to signal.

## Architecture decisions (do not re-debate these)
- Database: TimescaleDB (not ClickHouse, not plain Postgres) — hypertables needed
- Cache: Redis (not in-memory dict) — survives API restarts
- Model size: Kronos-small (not Kronos-base) — A2000 4GB VRAM constraint
- No Qlib dependency — custom NSEKronosDataset reads directly from TimescaleDB
- No SQLAlchemy ORM — asyncpg direct for performance

## Current status
- Phase: 0 (Infrastructure setup)
- DQG: not run yet
- Data collected: 0 days

## Known issues / gotchas
- Angel One historical API: 60-day limit per request — use get_historical_chunked()
- NSE market hours: 09:15–15:30 IST only — strip all other timestamps
- F&O expiry every Thursday — volatility spike expected in BANKNIFTY data
- TimescaleDB compression kicks in after 7 days — check decompression if querying old data

## Do not do these things
- Do not install Qlib — Windows/Linux compatibility issues, not needed
- Do not use SQLAlchemy — asyncpg pool is already set up
- Do not write to checkpoints/ without going through ModelRegistry
- Do not call KronosPredictor.predict() without running DQG first
