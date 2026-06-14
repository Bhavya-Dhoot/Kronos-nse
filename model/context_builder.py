"""Build model input context windows from TimescaleDB OHLCV."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from kronos_nse.common.instruments import INDEX_TOKENS, get_market_hours, is_trading_day

logger = logging.getLogger(__name__)
IST = "Asia/Kolkata"


class ContextBuilder:
    """Constructs Kronos context DataFrames and future timestamp indices."""

    def __init__(self, db: Any, config: dict[str, Any]) -> None:
        self.db = db
        self.config = config
        model_cfg = config.get("model") or {}
        self.lookback = int(model_cfg.get("lookback", 225))
        self.pred_len = int(model_cfg.get("default_pred_len", 12))

    async def build(self, symbol: str, timeframe: str, mode: str) -> dict[str, Any]:
        """Dispatch to mode-specific context builder."""
        mode_u = mode.upper()
        index_symbols = set(INDEX_TOKENS.keys())

        if symbol.upper() in index_symbols:
            return await self._build_index(symbol, timeframe)
        if mode_u in {"MULTI_TF", "MULTI"}:
            return await self._build_multi_tf(symbol, timeframe)
        if mode_u in {"REGIME", "REGIME_AWARE"}:
            return await self._build_regime(symbol, timeframe)
        return await self._build_standard(symbol, timeframe)

    async def _fetch_candles(
        self, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame:
        df = await self.db.get_candles(symbol, timeframe, limit=limit)
        return self._filter_trading_hours(df)

    def _filter_trading_hours(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = df.copy()
        if out.index.tz is None:
            out.index = out.index.tz_localize(IST)
        else:
            out.index = out.index.tz_convert(IST)

        # Detect daily timeframe (timestamps at midnight) — skip time filter
        first_ts = out.index[0]
        is_daily = first_ts.hour == 0 and first_ts.minute == 0

        market_open, market_close = get_market_hours()

        mask = []
        for ts in out.index:
            dt = ts.to_pydatetime()
            if not is_trading_day(dt):
                mask.append(False)
                continue
            if is_daily:
                mask.append(True)
            else:
                t = dt.time()
                mask.append(market_open <= t <= market_close)
        out = out.loc[mask]

        if out.empty:
            return out

        out = out[~out.index.duplicated(keep="last")]
        out = out.sort_index()
        if "amount" not in out.columns:
            out["amount"] = out["close"] * out["volume"]
        out = out.dropna(subset=["open", "high", "low", "close", "volume"])
        out = self._add_volume_features(out)
        return out

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Augment DataFrame with volume-derived features. Columns prefixed with
        ``vol_`` are auxiliary — the model's 6-channel tokenizer ignores them.
        Expand ``FEATURE_LIST`` and retrain to activate."""
        if df.empty or "volume" not in df.columns:
            return df

        vols = df["volume"].values.astype(np.float64)
        closes = df["close"].values.astype(np.float64)

        # Rolling vol z-score (lookback = 20)
        vol_mean = pd.Series(vols).rolling(20, min_periods=2).mean().values
        vol_std = pd.Series(vols).rolling(20, min_periods=2).std(ddof=0).values
        vol_z = np.divide(
            vols - vol_mean, vol_std, out=np.zeros_like(vols), where=vol_std > 1e-8
        )
        df["vol_zscore"] = np.nan_to_num(vol_z, nan=0.0)

        # Volume ratio: current / avg(20)
        vol_ratio = np.where(vol_mean > 1e-8, vols / vol_mean, 1.0)
        df["vol_ratio"] = np.nan_to_num(vol_ratio, nan=1.0)

        # Normalized OBV
        obv = np.zeros_like(vols)
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + vols[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - vols[i]
            else:
                obv[i] = obv[i - 1]
        obv_abs_max = max(np.abs(obv).max(), 1e-8)
        df["vol_obv_norm"] = obv / obv_abs_max

        return df

    def _trim_lookback(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) <= self.lookback:
            return df
        return df.iloc[-self.lookback :].copy()

    async def _build_standard(self, symbol: str, timeframe: str) -> dict[str, Any]:
        df = await self._fetch_candles(symbol, timeframe, limit=self.lookback + 50)
        if df.empty:
            raise RuntimeError(
                f"No trading data for {symbol} {timeframe} — "
                "all candles filtered by market-hours or symbol has no data"
            )
        df = self._trim_lookback(df)
        x_ts = df.index
        y_ts = self._generate_future_timestamps(x_ts[-1], timeframe, self.pred_len)

        # Dynamic temperature based on recent volatility
        temperature_override = None
        if len(df) >= 14:
            atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
            atr_pct = atr / max(df["close"].iloc[-1], 1e-6) * 100
            if atr_pct > 2.0:
                temperature_override = 0.85
            elif atr_pct < 0.5:
                temperature_override = 0.6

        result = {"df": df, "x_ts": x_ts, "y_ts": y_ts, "builder": "standard"}
        if temperature_override is not None:
            result["temperature_override"] = temperature_override
        return result

    async def _build_index(self, symbol: str, timeframe: str) -> dict[str, Any]:
        # Index symbols use same OHLCV path; token mapping is for data collection layer
        ctx = await self._build_standard(symbol, timeframe)
        ctx["builder"] = "index"
        ctx["index_token"] = INDEX_TOKENS.get(symbol.upper())
        return ctx

    async def _build_multi_tf(self, symbol: str, timeframe: str) -> dict[str, Any]:
        df_15 = await self._fetch_candles(symbol, "15min", limit=200)
        df_5 = await self._fetch_candles(symbol, "5min", limit=100)

        if not df_15.empty:
            df_15_rs = (
                df_15.resample("5min")
                .agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                )
                .dropna()
            )
        else:
            df_15_rs = df_15

        combined = pd.concat([df_15_rs, df_5]).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.tail(400)

        x_ts = combined.index
        y_ts = self._generate_future_timestamps(x_ts[-1], timeframe, self.pred_len)
        return {"df": combined, "x_ts": x_ts, "y_ts": y_ts, "builder": "multi_tf"}

    def _classify_regime(self, daily: pd.DataFrame) -> str:
        if len(daily) < 20:
            return "RANGING"
        high, low, close = daily["high"], daily["low"], daily["close"]
        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        close_last = float(close.iloc[-1])
        atr_ratio = float(atr / close_last) if close_last else 0.0

        up = close.diff()
        down = -up.clip(upper=0)
        up = up.clip(lower=0)
        rs = up.rolling(14).mean() / (down.rolling(14).mean() + 1e-9)
        adx_proxy = float(100 - (100 / (1 + rs.iloc[-1])))

        if adx_proxy > 25 and atr_ratio < 0.02:
            return "TRENDING"
        if atr_ratio > 0.025:
            return "VOLATILE"
        return "RANGING"

    async def _build_regime(self, symbol: str, timeframe: str) -> dict[str, Any]:
        ctx = await self._build_standard(symbol, timeframe)
        daily = await self._fetch_candles(symbol, "1day", limit=60)
        regime = self._classify_regime(daily)
        temperature_override = {
            "TRENDING": 0.6,
            "RANGING": 0.7,
            "VOLATILE": 0.85,
        }.get(regime, 0.7)
        ctx["builder"] = "regime"
        ctx["regime"] = regime
        ctx["temperature_override"] = temperature_override
        return ctx

    def _generate_future_timestamps(
        self,
        last_ts: pd.Timestamp,
        timeframe: str,
        n: int,
    ) -> pd.DatetimeIndex:
        """Generate n future market-valid timestamps in IST."""
        tf = timeframe.lower().strip()
        if tf.endswith("min"):
            step = timedelta(minutes=int(tf.replace("min", "")))
        elif tf in {"1h", "1hour"}:
            step = timedelta(hours=1)
        elif tf in {"1d", "1day"}:
            step = timedelta(days=1)
        else:
            step = timedelta(minutes=5)

        cur = pd.Timestamp(last_ts)
        if cur.tz is None:
            cur = cur.tz_localize(IST)
        else:
            cur = cur.tz_convert(IST)

        market_open, market_close = get_market_hours()
        market_open_delta = pd.Timedelta(
            hours=market_open.hour, minutes=market_open.minute
        )

        out: list[pd.Timestamp] = []
        while len(out) < n:
            cur = cur + step
            if tf in {"1d", "1day"}:
                while not is_trading_day(cur.to_pydatetime()):
                    cur = cur + timedelta(days=1)
                out.append(cur)
                continue

            if not is_trading_day(cur.to_pydatetime()):
                continue
            t = cur.time()
            if t < market_open:
                cur = cur.normalize() + market_open_delta
            elif t > market_close:
                cur = cur.normalize() + timedelta(days=1) + market_open_delta
                while not is_trading_day(cur.to_pydatetime()):
                    cur = cur + pd.Timedelta(days=1)
                continue
            out.append(cur)

        return pd.DatetimeIndex(out)
