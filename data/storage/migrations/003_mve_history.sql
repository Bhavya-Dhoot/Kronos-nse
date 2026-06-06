-- Migration 003: mve_history hypertable for persistent MVS tracking
-- TimescaleDB + PostgreSQL 15
-- Per D-11 through D-17

CREATE TABLE IF NOT EXISTS mve_history (
    time                    TIMESTAMPTZ     NOT NULL,
    composite               FLOAT8          NOT NULL,
    market_state            TEXT            NOT NULL,
    vix_value               FLOAT8,
    dimensions              JSONB           NOT NULL DEFAULT '[]',
    temperature_adjustment  FLOAT8          NOT NULL DEFAULT 0,
    directional_bias        FLOAT8          NOT NULL DEFAULT 0,
    band_width_multiplier   FLOAT8          NOT NULL DEFAULT 1.0,
    signal_threshold        FLOAT8          NOT NULL DEFAULT 0.005
);

-- Hypertable with 1-day chunk interval (D-13)
SELECT create_hypertable(
    'mve_history',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Index on time DESC for efficient history queries (D-15)
CREATE INDEX IF NOT EXISTS mve_history_time_desc_idx
    ON mve_history (time DESC);

-- Compression after 7 days (D-14)
ALTER TABLE mve_history SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy(
    'mve_history',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Retention policy: 30 days per D-14 (from config mve_history.retention_days, default 30)
SELECT add_retention_policy(
    'mve_history',
    INTERVAL '30 days',
    if_not_exists => TRUE
);
