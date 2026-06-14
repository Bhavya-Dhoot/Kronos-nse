-- Migration 001: Initial schema for Kronos NSE
-- TimescaleDB + PostgreSQL 15

-- ─────────────────────────────────────────────
-- 1. CANDLES (hypertable)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS candles (
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

SELECT create_hypertable(
    'candles',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Primary uniqueness constraint
CREATE UNIQUE INDEX IF NOT EXISTS candles_symbol_tf_time_idx
    ON candles (symbol, timeframe, time DESC);

-- Compression: store each (symbol, timeframe) segment together
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
-- 2. PREDICTION LEDGER
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prediction_ledger (
    id                SERIAL          PRIMARY KEY,
    symbol            TEXT            NOT NULL,
    timeframe         TEXT            NOT NULL,
    mode              TEXT            NOT NULL,   -- VISUAL/HEADLESS/PAPER

    pred_open         FLOAT8[]        NOT NULL DEFAULT '{}',
    pred_high         FLOAT8[]        NOT NULL DEFAULT '{}',
    pred_low          FLOAT8[]        NOT NULL DEFAULT '{}',
    pred_close        FLOAT8[]        NOT NULL DEFAULT '{}',
    pred_volume       FLOAT8[]        NOT NULL DEFAULT '{}',
    pred_timestamps   TIMESTAMPTZ[]   NOT NULL DEFAULT '{}',

    actual_close      FLOAT8[]                 DEFAULT '{}',

    mae               FLOAT8,
    directional_acc   FLOAT8,

    model_version     TEXT            NOT NULL,
    generated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS prediction_ledger_symbol_tf_idx
    ON prediction_ledger (symbol, timeframe, generated_at DESC);

CREATE INDEX IF NOT EXISTS prediction_ledger_unresolved_idx
    ON prediction_ledger (symbol, generated_at)
    WHERE resolved_at IS NULL;


-- ─────────────────────────────────────────────
-- 3. MODEL REGISTRY
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_registry (
    version              TEXT         PRIMARY KEY,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    val_mae              FLOAT8,
    val_directional_acc  FLOAT8,
    train_symbols        TEXT[]       NOT NULL DEFAULT '{}',
    timeframe            TEXT         NOT NULL,
    is_production        BOOLEAN      NOT NULL DEFAULT FALSE,
    promoted_at          TIMESTAMPTZ
);

-- Only one production model at a time
CREATE UNIQUE INDEX IF NOT EXISTS model_registry_single_prod_idx
    ON model_registry (is_production)
    WHERE is_production = TRUE;


-- ─────────────────────────────────────────────
-- 4. DQG REPORTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dqg_reports (
    id              SERIAL       PRIMARY KEY,
    symbol          TEXT         NOT NULL,
    timeframe       TEXT         NOT NULL,
    mode            TEXT         NOT NULL,
    status          TEXT         NOT NULL,   -- PASS / PARTIAL / FAIL
    coverage_pct    FLOAT8,
    days_collected  INT,
    checks          JSONB        NOT NULL DEFAULT '{}',
    recommendation  TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS dqg_reports_symbol_time_idx
    ON dqg_reports (symbol, timeframe, created_at DESC);


-- ─────────────────────────────────────────────
-- 5. CONTINUOUS AGGREGATE: 5-min OHLCV from 1-min candles
-- ─────────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS candles_5min
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

SELECT add_continuous_aggregate_policy(
    'candles_5min',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '2 minutes',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);
