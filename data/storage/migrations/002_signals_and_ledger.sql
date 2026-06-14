-- Migration 002: signals table + ledger actual high/low columns

ALTER TABLE prediction_ledger
    ADD COLUMN IF NOT EXISTS actual_high FLOAT8[] DEFAULT '{}';

ALTER TABLE prediction_ledger
    ADD COLUMN IF NOT EXISTS actual_low FLOAT8[] DEFAULT '{}';

CREATE TABLE IF NOT EXISTS signals (
    id                SERIAL       PRIMARY KEY,
    symbol            TEXT         NOT NULL,
    timeframe         TEXT         NOT NULL,
    direction         TEXT         NOT NULL,
    confidence        TEXT         NOT NULL,
    expected_move_pct FLOAT8,
    last_close        FLOAT8,
    pred_close        FLOAT8,
    model_version     TEXT,
    mode              TEXT         NOT NULL DEFAULT 'HEADLESS',
    generated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS signals_symbol_time_idx
    ON signals (symbol, generated_at DESC);

CREATE TABLE IF NOT EXISTS paper_trades (
    id            SERIAL       PRIMARY KEY,
    symbol        TEXT         NOT NULL,
    direction     TEXT         NOT NULL,
    entry_price   FLOAT8       NOT NULL,
    exit_price    FLOAT8,
    quantity      FLOAT8       NOT NULL DEFAULT 1,
    pnl           FLOAT8,
    signal_id     INT,
    opened_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    closed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS paper_trades_symbol_idx
    ON paper_trades (symbol, opened_at DESC);
