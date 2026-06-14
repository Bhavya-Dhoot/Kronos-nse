-- Migration 004: Add non-unique lookup index on candles for fast symbol/timeframe queries
-- The existing UNIQUE index (001) may not exist if there were duplicate rows during creation.
-- A non-unique index is sufficient for query performance and avoids uniqueness constraints.

CREATE INDEX IF NOT EXISTS candles_symbol_tf_time_lookup_idx
    ON candles (symbol, timeframe, time DESC);
