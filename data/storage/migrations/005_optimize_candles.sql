-- Migration 005: Optimize candles hypertable for query performance
-- TimescaleDB + PostgreSQL 15
-- Per Phase 1.1: Symbol partitioning + 1-day chunks + BRIN index

-- ─────────────────────────────────────────────
-- 1. Recreate candles hypertable with symbol partitioning + 1-day chunks
-- ─────────────────────────────────────────────

-- Drop existing compression policy first (required before altering hypertable)
SELECT remove_compression_policy('candles', if_exists => TRUE);

-- Drop existing continuous aggregate policy
SELECT remove_continuous_aggregate_policy('candles_5min', if_exists => TRUE);

-- Drop continuous aggregate view
DROP MATERIALIZED VIEW IF EXISTS candles_5min;

-- Drop indexes
DROP INDEX IF EXISTS candles_symbol_tf_time_idx;
DROP INDEX IF EXISTS candles_symbol_tf_time_lookup_idx;

-- Drop the hypertable (cascades to chunks)
DROP TABLE IF EXISTS candles CASCADE;

-- ─────────────────────────────────────────────
-- 2. Create optimized candles hypertable
-- ─────────────────────────────────────────────
CREATE TABLE candles (
    time         TIMESTAMPTZ    NOT NULL,
    symbol       TEXT           NOT NULL,
    timeframe    TEXT           NOT NULL,   -- e.g. "1m", "5m", "15m", "1d"
    open         FLOAT8         NOT NULL,
    high         FLOAT8         NOT NULL,
    low          FLOAT8         NOT NULL,
    close        FLOAT8         NOT NULL,
    volume       FLOAT8         NOT NULL DEFAULT 0,
    is_adjusted  BOOLEAN        NOT NULL DEFAULT FALSE,
    source       TEXT           NOT NULL DEFAULT 'angel_one',

    CONSTRAINT candles_ohlcv_check CHECK (
        high >= open AND high >= close AND
        low  <= open AND low  <= close AND
        volume >= 0
    )
);

-- Create hypertable with:
--   - 1-day chunk interval (instead of 7 days) for faster range scans
--   - 4 partitions by symbol hash (parallelizes inserts/queries across symbols)
SELECT create_hypertable(
    'candles',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    partitioning_column => 'symbol',
    number_partitions => 4,
    if_not_exists       => TRUE
);

-- ─────────────────────────────────────────────
-- 3. Indexes
-- ─────────────────────────────────────────────

-- Primary uniqueness constraint (symbol, timeframe, time)
CREATE UNIQUE INDEX IF NOT EXISTS candles_symbol_tf_time_idx
    ON candles (symbol, timeframe, time DESC);

-- Lookup index for fast symbol/timeframe queries
CREATE INDEX IF NOT EXISTS candles_symbol_tf_time_lookup_idx
    ON candles (symbol, timeframe, time DESC);

-- BRIN index on time for fast range scans on compressed chunks
CREATE INDEX IF NOT EXISTS candles_time_brin_idx
    ON candles USING BRIN (time);

-- ─────────────────────────────────────────────
-- 4. Compression
-- ─────────────────────────────────────────────
ALTER TABLE candles SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy(
    'candles',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- ─────────────────────────────────────────────
-- 5. Continuous Aggregate: 5-min OHLCV from 1-min candles
-- ─────────────────────────────────────────────
CREATE MATERIALIZED VIEW candles_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS time,
    symbol,
    '5m'                           AS timeframe,
    first(open,  time)             AS open,
    max(high)                      AS high,
    min(low)                       AS low,
    last(close,  time)             AS close,
    sum(volume)                    AS volume
FROM candles
WHERE timeframe = '1m'
GROUP BY time_bucket('5 minutes', time), symbol
WITH NO DATA;

-- Add continuous aggregate policy (runs every minute, processes last hour)
SELECT add_continuous_aggregate_policy(
    'candles_5min',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '2 minutes',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- Index on the continuous aggregate for fast queries
-- Note: Continuous aggregates don't support UNIQUE indexes, use regular index
CREATE INDEX IF NOT EXISTS candles_5min_symbol_time_idx
    ON candles_5min (symbol, time DESC);

-- ─────────────────────────────────────────────
-- 6. Retention policy (optional - keep 2 years)
-- ─────────────────────────────────────────────
SELECT add_retention_policy(
    'candles',
    INTERVAL '730 days',
    if_not_exists => TRUE
);