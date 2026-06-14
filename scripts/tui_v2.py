#!/usr/bin/env python3
"""Kronos NSE TUI v2.0 — Enhanced terminal trading dashboard."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from scripts.tui_lib import chart as c
from scripts.tui_lib.chart import _fmt_age, _fmt_price
from scripts.tui_lib.fetcher import (
    close_fetcher,
    fetch_candles,
    fetch_dqg,
    fetch_market_context,
    fetch_multi_timeframe,
    fetch_prediction,
    get_ws_states,
    reconnect_symbol_ws,
)
from scripts.tui_lib.levels import (
    classify_regime,
    compute_atr,
    compute_bollinger,
    compute_key_levels,
    compute_macd,
    compute_obv,
    compute_rsi,
    compute_volume_ratio,
)
from scripts.tui_lib.sidebar import (
    LevelsPanel,
    MarketPanel,
    ModelPanel,
    PredictionPanel,
    RegimePanel,
)
from scripts.tui_lib.store import AccuracyStore

VERSION = "2.0.0"
DEFAULT_SYMBOL = os.getenv("KRONOS_DEFAULT_SYMBOL", "RELIANCE")
CANDLE_LIMITS = [50, 100, 200]
TIMEFRAMES = ["1m", "3m", "5m", "15m", "1H"]
SIDEBAR_W = 38


class VolumeHistogram(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.candles: list[dict] = []
        self.n_pred: int = 0

    def update_data(self, candles: list[dict], n_pred: int = 0) -> None:
        self.candles = candles
        self.n_pred = n_pred
        self.refresh()

    def render(self) -> Text:
        w = max(self.size.width, 10)
        h = max(self.size.height, 3)
        if not self.candles:
            return Text("")

        axis_w = 11
        vol_h = h
        candle_w = w - axis_w
        if candle_w < 3:
            return Text("")
        candle_w = max(candle_w, 3)
        display = list(self.candles)
        n_pred = self.n_pred
        n_candle_cols = candle_w
        if n_pred > 0:
            n_candle_cols = max(candle_w - n_pred - 1, 1)
        display = display[-n_candle_cols:] if n_candle_cols < len(display) else display

        vols = [c["volume"] for c in display]
        all_zero = all(v == 0 for v in vols)

        v_max = max(vols) if vols else 1
        avg_vol = sum(vols) / len(vols) if vols else 1

        result = Text()
        if all_zero:
            for vrow in range(vol_h):
                vline = Text()
                if n_pred > 0:
                    vline.append(" ")
                    for _ in range(n_pred):
                        vline.append(" ", style="")
                label = "0 VOL" if vrow == vol_h // 2 else ""
                vline.append(Text(f"{label:>{axis_w}}", style="dim white"))
                result.append(vline)
                result.append("\n")
            return result

        for vrow in range(vol_h):
            vline = Text()
            frac_top_v = 1 - vrow / vol_h
            frac_bot_v = 1 - (vrow + 1) / vol_h
            is_avg_row = vrow == vol_h - 1
            for col_data in display:
                vn = col_data["volume"] / v_max
                col = "green" if col_data["close"] >= col_data["open"] else "red"
                if vn >= frac_top_v:
                    vline.append("█", style=f"dim {col}")
                elif vn >= frac_bot_v:
                    vline.append("▄", style=f"dim {col}")
                elif is_avg_row and avg_vol / v_max >= frac_bot_v:
                    vline.append("╴", style="dim white")
                else:
                    vline.append(" ", style="")
            if n_pred > 0:
                vline.append(" ")
                for _ in range(n_pred):
                    vline.append(" ", style="")

            if vrow == vol_h // 2:
                vline.append(Text(f"{'VOL':>{axis_w - 1}}", style="dim white"))
            else:
                vline.append(Text(f"{'':>{axis_w}}", style=""))
            result.append(vline)
            result.append("\n")
        return result


class IndicatorRow(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._indicators: dict = {}

    def update_data(self, indicators: dict) -> None:
        self._indicators = indicators
        self.refresh()

    def render(self) -> Text:
        ind = self._indicators
        parts = []

        rsi = ind.get("rsi")
        if rsi is not None:
            rsi_col = (
                "bold green"
                if rsi > 65
                else ("bold red" if rsi < 35 else "bold yellow")
            )
            parts.append(f"[{rsi_col}]RSI:{rsi:.1f}[/]")

        macd = ind.get("macd", {})
        if macd:
            m_val = macd.get("histogram", macd.get("macd", 0))
            m_col = "bold green" if m_val >= 0 else "bold #ff2d5b"
            parts.append(f"[{m_col}]MACD:{m_val:+.1f}[/]")

        atr = ind.get("atr")
        if atr is not None:
            parts.append(f"[dim]ATR:{atr:.2f}[/]")

        bb = ind.get("bollinger", {})
        bb_state = bb.get("state", "N/A")
        bb_col = {
            "SQUEEZE": "bold yellow",
            "EXPANDING": "bold cyan",
            "UPPER": "bold green",
            "LOWER": "bold #ff2d5b",
        }.get(bb_state, "dim white")
        parts.append(f"[{bb_col}]BB:{bb_state}[/]")

        vol_ratio = ind.get("vol_ratio")
        if vol_ratio is not None:
            vr_col = (
                "bold green"
                if vol_ratio > 1.5
                else ("bold yellow" if vol_ratio > 1.0 else "dim white")
            )
            parts.append(f"[{vr_col}]V/R:{vol_ratio:.2f}x[/]")

        obv = ind.get("obv_direction")
        if obv is not None:
            obv_col = (
                "bold green"
                if obv == "UP"
                else ("bold #ff2d5b" if obv == "DOWN" else "bold yellow")
            )
            parts.append(
                f"[{obv_col}]OBV:↗[/]"
                if obv == "UP"
                else f"[{obv_col}]OBV:↘[/]"
                if obv == "DOWN"
                else f"[{obv_col}]OBV:─[/]"
            )

        mtf = ind.get("multi_timeframe", {})
        for tf_key, tf_label in [("15m", "15m"), ("1h", "1H"), ("1d", "D")]:
            tf_data = mtf.get(tf_key, {})
            dir_val = tf_data.get("direction", "NEUT")
            tf_rsi = tf_data.get("rsi")
            dir_col = (
                "bold green"
                if dir_val == "BULL"
                else ("bold #ff2d5b" if dir_val == "BEAR" else "bold yellow")
            )
            rsi_str = f"RSI:{tf_rsi:.0f}" if tf_rsi is not None else ""
            parts.append(f"[{dir_col}]{tf_label}:{dir_val}[/] [dim]{rsi_str}[/]")

        text_str = "  |  ".join(parts) if parts else "[dim]indicators...[/]"
        return Text.from_markup(f"  {text_str}")


class AlertOverlay(ModalScreen[None]):
    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(
                "\n\n\n"
                "  [bold]Set Price Alert[/]\n\n"
                "  Enter price level then press Enter:\n"
                "    Price (e.g. 23500):\n\n"
                "  [dim]Press Escape to cancel[/]\n"
            )
        )

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]


class HelpScreen(ModalScreen[None]):
    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(
                "\n\n\n"
                "  [bold]Kronos NSE TUI v2.0 — Keybindings[/]\n\n"
                "  [bold]t[/]   Cycle timeframes: 1m→3m→5m→15m→1H→1m\n"
                "  [bold]r[/]   Force refresh predictions\n"
                "  [bold]c[/]   Cycle candle count (50/100/200)\n"
                "  [bold]p[/]   Toggle prediction overlay\n"
                "  [bold]v[/]   Toggle volume histogram\n"
                "  [bold]k[/]   Toggle key levels overlay\n"
                "  [bold]b[/]   Cycle band mode: dots / band+dots / band-only\n"
                "  [bold]m[/]   Toggle model stats sidebar panel\n"
                "  [bold]i[/]   Toggle market context sidebar panel\n"
                "  [bold]a[/]   Open alert configuration\n"
                "  [bold]h[/]   Show this help\n"
                "  [bold]q[/]   Quit\n\n"
                "  Type a ticker in the input bar and press Enter to switch.\n\n"
                "  [dim]DQG = Data Quality Gate.\n"
                "  ±1σ band shows prediction confidence range.\n"
                "  Key levels: R=Resistance, S=Support, V=VWAP, H=PDH, L=PDL[/]\n"
            )
        )

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
        ("h", "dismiss", "Close"),
    ]


class KronosTUI(App):
    TITLE = "Kronos NSE"
    SUB_TITLE = f"v{VERSION}"

    CSS = """
    Screen {
        layout: horizontal;
    }

    #main-area {
        width: 1fr;
        layout: vertical;
    }

    CandleChart {
        height: 1fr;
        margin: 0 1;
    }

    VolumeHistogram {
        height: 5;
        margin: 0 1;
        min-height: 3;
    }

    #indicator-row {
        height: 3;
        margin: 0 1;
    }

    #info-bar {
        height: 3;
        margin: 0 1;
    }

    #sidebar {
        width: 38;
        layout: vertical;
        background: $surface;
        border: solid $primary;
    }

    PredictionPanel {
        height: 9;
    }

    RegimePanel {
        height: 6;
    }

    MarketPanel {
        height: 8;
    }

    ModelPanel {
        height: 7;
    }

    LevelsPanel {
        height: 12;
    }

    #sidebar-sep {
        height: 1;
    }

    #bottom-bar {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }

    Input {
        width: 100%;
    }

    AlertOverlay, HelpScreen {
        align: center middle;
    }

    AlertOverlay > Static, HelpScreen > Static {
        width: 60%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "cycle_timeframe", "TF"),
        ("r", "refresh_now", "Refresh"),
        ("c", "cycle_candle_limit", "Candles"),
        ("p", "toggle_overlay", "Overlay"),
        ("v", "toggle_volume", "Vol"),
        ("k", "toggle_levels", "Levels"),
        ("b", "cycle_band", "Band"),
        ("m", "toggle_model", "Model"),
        ("i", "toggle_market", "Market"),
        ("a", "open_alerts", "Alerts"),
        ("h", "show_help", "Help"),
    ]

    def __init__(
        self,
        initial_symbol: str = "",
        initial_timeframe: str = "5m",
    ):
        super().__init__()
        self._symbol = (initial_symbol or DEFAULT_SYMBOL).upper()
        self._timeframe = initial_timeframe
        self._show_prediction = True
        self._show_volume = True
        self._show_levels = False
        self._show_model_panel = True
        self._show_market_panel = True
        self._band_mode = 0
        self._candle_limit = 200
        self._last_updated = ""
        self._cached = False
        self._force_refresh = False
        self._store = AccuracyStore(max_per_symbol=50)
        self._market_ctx: dict = {}
        self._mtf_data: dict = {}
        self._ltp: float | None = None
        self._prev_ltp: float | None = None
        self._fetch_in_progress: bool = False
        self._fetch_pending_params: list[dict] = []
        self._ws_pred_debounce_task: asyncio.Task | None = None
        self._candle_cache_key: tuple | None = None
        self._cached_indicators: dict = {}
        self._flash_pred_flip_until: float = 0
        self._flash_pred_text: str = ""
        self._flash_alert_until: float = 0
        self._flash_alert_msg: str = ""
        self._flash_latency_until: float = 0
        self._last_info_kwargs: dict | None = None
        self._ltp_ref_price: float | None = None
        self._stale_cycles: int = 0
        self._last_candle_digest: int | None = None
        self._stale_skip_until: float = 0
        self._active_prediction: dict | None = None
        self._conviction_state: str = "INITIAL"
        self._prediction_horizon: int = 0
        self._divergence_count: int = 0
        self._horizon_progress: float = 0.0

    def compose(self) -> ComposeResult:
        with Container(id="main-area"):
            yield CandleChart(symbol=self._symbol, timeframe=self._timeframe)
            yield VolumeHistogram(id="vol-hist")
            yield IndicatorRow(id="indicator-row")
            yield InfoBar(id="info-bar")
            with Container(id="bottom-bar"):
                yield Input(
                    id="ticker-input",
                    placeholder=f"Enter symbol — current: {self._symbol}",
                )
        with Container(id="sidebar"):
            yield PredictionPanel(SIDEBAR_W, id="panel-prediction")
            yield Static("─" * SIDEBAR_W, id="sidebar-sep-1")
            yield RegimePanel(SIDEBAR_W, id="panel-regime")
            yield Static("─" * SIDEBAR_W, id="sidebar-sep-2")
            yield MarketPanel(SIDEBAR_W, id="panel-market")
            yield Static("─" * SIDEBAR_W, id="sidebar-sep-3")
            yield ModelPanel(SIDEBAR_W, id="panel-model")
            yield Static("─" * SIDEBAR_W, id="sidebar-sep-4")
            yield LevelsPanel(SIDEBAR_W, id="panel-levels")
        yield Footer()

    async def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(30, self._refresh_data)
        self._market_timer = self.set_interval(60, self._refresh_market_context)
        self._ltp_timer = self.set_interval(2, self._push_ltp_update)
        self._connect_ws()
        self._load_data()
        await self._refresh_market_context()

    def _get_refresh_interval(self) -> int:
        """Return adaptive refresh interval in seconds based on conviction state and market hours."""
        import pandas as pd

        from scripts.seed_instruments import is_market_open

        # Base interval when market is open
        if is_market_open(pd.Timestamp.now(tz="Asia/Kolkata")):
            # During market hours: 30s for active states, 60s for CONFIRMED
            if self._conviction_state == "CONFIRMED":
                return 60
            return 30
        else:
            # Outside market hours: 5min for CONFIRMED, 2min for others
            if self._conviction_state == "CONFIRMED":
                return 300
            return 120

    def _reschedule_refresh(self) -> None:
        """Reschedule the refresh timer with adaptive interval."""
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()
        interval = self._get_refresh_interval()
        self._refresh_timer = self.set_interval(interval, self._refresh_data)
        logger.debug(
            "TUI refresh interval set to %ds (conviction=%s)",
            interval,
            self._conviction_state,
        )

    def _connect_ws(self) -> None:
        logger.info("Connecting WS for %s", self._symbol)
        reconnect_symbol_ws(
            self._symbol,
            on_tick=self._on_ws_tick,
            on_prediction=self._on_ws_prediction,
        )

    def _on_ws_tick(self, msg: dict) -> None:
        payload = msg.get("payload", msg)
        ltp_raw = payload.get("ltp") or payload.get("last_traded_price")
        if ltp_raw is not None:
            try:
                self._prev_ltp = self._ltp
                self._ltp = float(ltp_raw)
                self._check_prediction_validity(self._ltp)
            except (ValueError, TypeError):
                pass

    def _on_ws_prediction(self, msg: dict) -> None:
        payload = msg.get("payload", msg)
        if payload.get("type") == "prediction" or "pred_close" in payload:
            logger.debug(
                "WS prediction received for %s, debouncing reload", self._symbol
            )
            if self._ws_pred_debounce_task and not self._ws_pred_debounce_task.done():
                self._ws_pred_debounce_task.cancel()
            # Suppress CancelledError — it's intentional
            self._ws_pred_debounce_task = asyncio.create_task(self._debounced_reload())

    async def _debounced_reload(self) -> None:
        await asyncio.sleep(2.0)
        self._load_data()

    def _push_ltp_update(self) -> None:
        ltp = self._ltp
        if ltp is None:
            return
        chart = self.query_one(CandleChart)
        if chart.ltp == ltp:
            return
        chart.ltp = ltp
        chart.refresh()
        if self._last_info_kwargs is None:
            return
        ref = self._ltp_ref_price
        if ref is not None:
            chg = ltp - ref
            pct = (chg / ref) * 100 if ref else 0
            chg_sym = "+" if chg >= 0 else ""
            chg_tag = "bold green" if chg >= 0 else "bold #ff2d5b"
            ltp_str = f"LTP:[{chg_tag}]{_fmt_price(ltp)} ({chg_sym}{pct:.2f}%)[/]"
        else:
            ltp_str = f"LTP:[bold white]{_fmt_price(ltp)}[/]"
        kwargs = dict(self._last_info_kwargs)
        kwargs["ltp_change"] = ltp_str
        info = self.query_one("#info-bar", InfoBar)
        info.update(InfoBar.make(**kwargs))

    def _check_prediction_validity(self, ltp: float | None) -> None:
        """Compare current LTP against active prediction to update conviction state.
        Triggers a re-fetch when prediction is DIVERGING."""
        if self._active_prediction is None or ltp is None:
            return
        pred_close = self._active_prediction.get("pred_close", [])
        pred_timestamps = self._active_prediction.get(
            "timestamps"
        ) or self._active_prediction.get("pred_timestamps", [])
        if not pred_close:
            return
        pred_len = len(pred_close)

        # Compute horizon progress
        if pred_timestamps:
            try:
                t0 = datetime.fromisoformat(
                    pred_timestamps[0].replace("Z", "+00:00")
                ).timestamp()
                t_last = datetime.fromisoformat(
                    pred_timestamps[-1].replace("Z", "+00:00")
                ).timestamp()
                horizon_span = max(t_last - t0, 1)
                elapsed = time.time() - t0
                self._horizon_progress = min(1.0, elapsed / horizon_span)
            except Exception:
                self._horizon_progress = 0.0
        else:
            self._horizon_progress = 0.0

        # 80% horizon consumed → STALE
        if self._horizon_progress >= 0.8:
            if self._conviction_state != "STALE":
                self._conviction_state = "STALE"
                self._load_data()
                self._reschedule_refresh()
            return

        # Divergence check: compare LTP against expected price at current bar
        bar_idx = min(int(self._horizon_progress * pred_len), pred_len - 1)
        expected = pred_close[bar_idx]
        if expected == 0:
            return

        divergence_pct = abs(ltp - expected) / expected * 100

        # Confidence-based threshold
        conf_str = self._active_prediction.get("confidence", "MEDIUM")
        threshold = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.25}.get(conf_str, 0.5)

        if divergence_pct > threshold:
            self._divergence_count += 1
        else:
            self._divergence_count = 0

        if self._divergence_count >= 2:
            if self._conviction_state != "DIVERGING":
                self._conviction_state = "DIVERGING"
                self._load_data()
                self._reschedule_refresh()
        elif self._divergence_count == 1:
            if self._conviction_state != "WATCHING":
                self._conviction_state = "WATCHING"
                self._reschedule_refresh()
        else:
            if self._conviction_state != "CONFIRMED":
                self._conviction_state = "CONFIRMED"
                self._reschedule_refresh()

    def _compute_prediction_bands(self, prediction, ltp=None):
        if not prediction:
            return None, None, None, None
        pred_close = prediction.get("pred_close")
        pred_ts = prediction.get("timestamps")
        self._store.add(self._symbol, prediction, ltp=ltp)
        pred_upper = None
        pred_lower = None
        samples = prediction.get("samples")
        if samples and len(samples) > 0:
            all_preds = []
            for s in samples:
                sp = s.get("pred_close", [])
                if sp:
                    all_preds.append(sp)
            if len(all_preds) >= 2:
                nsteps = min(len(p) for p in all_preds)
                means = []
                stds = []
                for i in range(nsteps):
                    vals = [p[i] for p in all_preds if i < len(p)]
                    if vals:
                        m = sum(vals) / len(vals)
                        v = sum((x - m) ** 2 for x in vals) / len(vals)
                        std = math.sqrt(v)
                        means.append(m)
                        stds.append(std)
                if means:
                    pred_close = means
                    pred_upper = [m + s for m, s in zip(means, stds)]
                    pred_lower = [m - s for m, s in zip(means, stds)]
        return pred_close, pred_ts, pred_upper, pred_lower

    def _compute_accuracy_metrics(self, accuracy_records):
        if not accuracy_records:
            return None, "", ""
        accuracy_data = []
        for rec in accuracy_records:
            if rec.actual_close:
                accuracy_data.append(
                    {
                        "predicted": rec.pred_close,
                        "actual_close": rec.actual_close[-1]
                        if rec.actual_close
                        else None,
                    }
                )
        mae_str = ""
        dir_str = ""
        if accuracy_records and accuracy_records[-1].accuracy_checked:
            last_rec = accuracy_records[-1]
            if last_rec.mae is not None:
                mae_str = f"{last_rec.mae:.2f}"
            if last_rec.dir_accuracy is not None:
                dir_str = f"{last_rec.dir_accuracy:.0%}"
        return accuracy_data, mae_str, dir_str

    def _get_flash_message(self) -> str:
        now = time.time()
        if now < self._flash_alert_until:
            return self._flash_alert_msg
        if now < self._flash_pred_flip_until:
            return self._flash_pred_text
        if now < self._flash_latency_until:
            return "⚠ LAT SPIKE"
        return ""

    def _update_all(
        self, candles, prediction, dqg, accuracy_records, candle_data_age=None
    ):
        chart = self.query_one(CandleChart)

        _ltp_snapshot = self._ltp
        _prev_ltp_snapshot = self._prev_ltp

        pred_close, pred_ts, pred_upper, pred_lower = self._compute_prediction_bands(
            prediction, ltp=_ltp_snapshot
        )

        last_c = candles[-1].get("close") if candles else None
        dqg_status = ""
        coverage = 0.0
        if dqg:
            dqg_status = dqg.get("status", "")
            coverage = dqg.get("coverage_pct", 0.0)

        latency = prediction.get("latency_ms") if prediction else None
        if latency is not None:
            self._store.session.record_latency(latency)
            if latency > 500:
                self._flash_latency_until = time.time() + 3

        model_ver = prediction.get("model_version", "") if prediction else ""
        if not model_ver and dqg:
            model_ver = dqg.get("model_version", "")

        self._cached = prediction.get("cached", False) if prediction else False
        data_age = candle_data_age or (
            prediction.get("data_age_seconds") if prediction else None
        )

        accuracy_data, mae_str, dir_str = self._compute_accuracy_metrics(
            accuracy_records
        )

        self._last_updated = datetime.now().strftime("%H:%M:%S")

        key_levels = compute_key_levels(candles)
        regime = classify_regime(candles, pred_close, ltp=_ltp_snapshot)
        price_high = max(c["high"] for c in candles) if candles else 0
        price_low = min(c["low"] for c in candles) if candles else 0
        if pred_close:
            price_high = max(price_high, max(pred_close))
            price_low = min(price_low, min(pred_close))

        indicators = self._compute_indicators(candles)

        band_label = ""
        if self._band_mode == 1:
            band_label = "±1σ ON"
        elif self._band_mode == 2:
            band_label = "±1σ ONLY"

        chart.update_data(
            candles,
            symbol=self._symbol,
            timeframe=self._timeframe,
            pred_close=pred_close,
            pred_timestamps=pred_ts,
            pred_upper=pred_upper,
            pred_lower=pred_lower,
            band_mode=self._band_mode,
            accuracy_data=accuracy_data,
            last_close=last_c,
            dqg_status=dqg_status,
            coverage=coverage,
            latency=latency,
            model_version=model_ver,
            mae=mae_str,
            dir_acc=dir_str,
            last_updated=self._last_updated,
            cached=self._cached,
            data_age_seconds=data_age,
            key_levels=key_levels if self._show_levels else None,
            show_levels=self._show_levels,
            show_band_label=band_label,
            ltp=_ltp_snapshot,
            conviction_state=self._conviction_state,
        )

        n_pred = len(pred_close) if pred_close else 0
        vol_hist = self.query_one("#vol-hist", VolumeHistogram)
        vol_hist.update_data(candles, n_pred)

        ind_row = self.query_one("#indicator-row", IndicatorRow)
        ind_row.update_data(indicators)

        info = self.query_one("#info-bar", InfoBar)
        age_str = _fmt_age(data_age) if data_age is not None else ""
        latency_ms = self._store.session.get_latency()
        spark = self._store.session.get_sparkline(10)

        flip_alert = self._store.session.consume_flip_alert()
        if flip_alert:
            self._flash_pred_flip_until = time.time() + 5
            self._flash_pred_text = flip_alert

        flash_msg = self._get_flash_message()

        ltp_acc: dict = {}
        if pred_close and _ltp_snapshot is not None:
            pred_last = pred_close[-1] if len(pred_close) > 1 else None
            self._store.session.record_ltp_accuracy(
                pred_close[0], _ltp_snapshot, pred_last_close=pred_last
            )
            ltp_acc = self._store.session.get_ltp_accuracy()

        pred_volume = prediction.get("pred_volume") if prediction else None
        if pred_volume and candles and len(candles) > 0:
            actual_vol = candles[-1].get("volume", 0)
            if actual_vol and actual_vol > 0:
                pred_vol_last = pred_volume[-1] if len(pred_volume) > 1 else None
                self._store.session.record_vol_accuracy(
                    pred_volume[0], actual_vol, pred_last_vol=pred_vol_last
                )

        ltp_err_str = (
            f"LTP-Err:{ltp_acc.get('last_error', 0):.2f}"
            if ltp_acc.get("last_error") is not None
            else ""
        )

        ltp_change_str = ""
        ref_price = _prev_ltp_snapshot if _prev_ltp_snapshot is not None else last_c
        if _ltp_snapshot is not None and ref_price is not None:
            chg = _ltp_snapshot - ref_price
            pct = (chg / ref_price) * 100 if ref_price else 0
            chg_sym = "+" if chg >= 0 else ""
            chg_tag = "bold green" if chg >= 0 else "bold #ff2d5b"
            ltp_change_str = (
                f"LTP:[{chg_tag}]{_fmt_price(_ltp_snapshot)} ({chg_sym}{pct:.2f}%)[/]"
            )

        ws_states = get_ws_states()
        ws_ok = all(ws_states.values()) if ws_states else True

        self._last_info_kwargs = dict(
            symbol=self._symbol,
            dqg_status=dqg_status,
            coverage=coverage,
            latency=latency_ms,
            model_version=model_ver,
            mae=mae_str,
            dir_acc=dir_str,
            n_candles=len(candles) if candles else 0,
            show_overlay=self._show_prediction,
            timeframe=self._timeframe,
            candle_limit=self._candle_limit,
            last_updated=self._last_updated,
            cached=self._cached,
            data_age_str=age_str,
            sparkline=spark,
            flash_msg=flash_msg,
            ltp_err=ltp_err_str,
            ltp_change=ltp_change_str,
            ws_connected=ws_ok,
        )
        info.update(InfoBar.make(**self._last_info_kwargs))
        self._ltp_ref_price = (
            _prev_ltp_snapshot if _prev_ltp_snapshot is not None else last_c
        )

        # Compute prediction age for sidebar
        pred_age = ""
        if self._active_prediction and self._active_prediction.get("pred_timestamps"):
            try:
                pts = self._active_prediction["pred_timestamps"]
                t0 = datetime.fromisoformat(pts[0].replace("Z", "+00:00"))
                age_min = int((datetime.now() - t0).total_seconds() / 60)
                pred_age = f"{age_min}m"
            except Exception:
                pass
        self._update_sidebar_panels(
            prediction,
            regime,
            key_levels,
            price_low,
            price_high,
            ltp_acc,
            dqg=dqg,
            conviction_state=self._conviction_state,
            horizon_progress=self._horizon_progress,
            prediction_age=pred_age,
        )

    def _update_sidebar_panels(
        self,
        prediction,
        regime,
        key_levels,
        price_low,
        price_high,
        ltp_acc,
        dqg=None,
        conviction_state="",
        horizon_progress=0.0,
        prediction_age="",
    ):
        pred_panel = self.query_one("#panel-prediction", PredictionPanel)
        dqg_status = dqg.get("status", "") if dqg else ""
        dqg_detail = ""
        if dqg and dqg.get("checks"):
            failed = [
                k for k, v in dqg.get("checks", {}).items() if not v.get("passed", True)
            ]
            if failed:
                dqg_detail = ",".join(failed[:3])
            stale_warn = dqg.get("checks", {}).get("staleness", {}).get("warning")
            if stale_warn:
                dqg_detail = ("⚠ STALE," + dqg_detail) if dqg_detail else "⚠ STALE"
        pred_panel.update_data(
            prediction,
            band_active=(self._band_mode > 0),
            price_low=price_low,
            price_high=price_high,
            dqg_status=dqg_status,
            dqg_detail=dqg_detail,
            conviction_state=conviction_state,
            horizon_progress=horizon_progress,
            prediction_age=prediction_age,
        )

        regime_panel = self.query_one("#panel-regime", RegimePanel)
        regime_panel.update_data(regime)

        mkt_panel = self.query_one("#panel-market", MarketPanel)
        mkt_panel.update_data(dict(self._market_ctx))
        mkt_panel.display = self._show_market_panel

        model_panel = self.query_one("#panel-model", ModelPanel)
        model_panel.update_data(self._store, ltp_accuracy=ltp_acc)
        model_panel.display = self._show_model_panel

        lvl_panel = self.query_one("#panel-levels", LevelsPanel)
        lvl_panel.update_data(key_levels, show=self._show_levels)

    def _compute_indicators(self, candles):
        if not candles:
            return {}
        if len(candles) < 5:
            return {}
        last = candles[-1]
        key = (len(candles), last.get("time"), last.get("close"), last.get("volume"))
        if key == self._candle_cache_key:
            return self._cached_indicators
        result = {}
        rsi = compute_rsi(candles)
        if rsi is not None:
            result["rsi"] = rsi
        macd = compute_macd(candles)
        if macd:
            result["macd"] = macd
        atr = compute_atr(candles)
        if atr is not None:
            result["atr"] = atr
        bb = compute_bollinger(candles)
        if bb:
            result["bollinger"] = bb
        vol_ratio = compute_volume_ratio(candles)
        if vol_ratio is not None:
            result["vol_ratio"] = vol_ratio
        obv_data = compute_obv(candles)
        if obv_data:
            result["obv_direction"] = obv_data.get("direction", "FLAT")
        result["multi_timeframe"] = self._mtf_data
        self._candle_cache_key = key
        self._cached_indicators = result
        return result

    def _load_data(self) -> None:
        if self._fetch_in_progress:
            logger.debug(
                "Fetch already in progress, queuing pending for %s", self._symbol
            )
            self._fetch_pending_params.append(
                {"symbol": self._symbol, "timeframe": self._timeframe}
            )
            return
        logger.debug("Loading data for %s (%s)", self._symbol, self._timeframe)
        self._fetch_in_progress = True
        self.run_worker(self._run_fetch_chain())

    async def _run_fetch_chain(self) -> None:
        symbol = self._symbol
        tf = self._timeframe

        if self._stale_skip_until and time.time() < self._stale_skip_until:
            self._fetch_in_progress = False
            return

        chart = self.query_one(CandleChart)
        chart.is_refresh_lock = True
        chart.is_refreshing = True
        chart.refresh()

        self._force_refresh = False

        # Decide whether we need a new prediction
        needs_prediction = self._conviction_state in ("INITIAL", "DIVERGING", "STALE")
        force_refresh = self._conviction_state in ("DIVERGING", "STALE")

        try:
            candles_task = fetch_candles(symbol, timeframe=tf, limit=self._candle_limit)
            tasks = [candles_task]
            if needs_prediction:
                pred_task = fetch_prediction(
                    symbol, timeframe=tf, force_refresh=force_refresh
                )
                tasks.append(pred_task)
            dqg_task = fetch_dqg(symbol, timeframe=tf)
            tasks.append(dqg_task)

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            chart.is_refreshing = False
            self._fetch_in_progress = False
            return
        except Exception as e:
            logger.error("Fetch chain failed for %s: %s", symbol, e, exc_info=True)
            chart.is_refreshing = False
            if not chart.candles:
                chart.update_data([], symbol=symbol, error_msg=f"Error: {e}")
            else:
                chart.refresh()
            self._fetch_in_progress = False
            return

        # Unpack results (candles always first, then optional prediction, then dqg)
        _candles_result = results[0]
        prediction = results[1] if needs_prediction else self._active_prediction
        dqg = (
            results[2]
            if needs_prediction
            else (results[1] if len(results) > 1 else None)
        )

        error_msg = ""
        candle_data_age = None
        if isinstance(_candles_result, Exception):
            error_msg = f"History API: {_candles_result}"
            candles = None
        elif isinstance(_candles_result, tuple):
            candles, candle_data_age = _candles_result
        else:
            candles = _candles_result
        if needs_prediction and isinstance(prediction, Exception):
            error_msg = f"Prediction API: {prediction}"
            prediction = None
            if self._active_prediction is not None:
                prediction = self._active_prediction
        if dqg is not None and isinstance(dqg, Exception):
            error_msg = f"DQG API: {dqg}"
            dqg = None

        chart.is_refreshing = False

        if candles is None or not candles:
            if not chart.candles or chart._sym != symbol:
                chart.update_data(
                    [], symbol=symbol, error_msg=error_msg or "No data available"
                )
            else:
                chart.refresh()
            self._fetch_in_progress = False
            if self._fetch_pending_params:
                self._fetch_pending_params.clear()
                self._load_data()
            return

        # Store new prediction as active
        if prediction and prediction is not self._active_prediction:
            self._active_prediction = prediction
            new_state = prediction.get("conviction_state", "CONFIRMED")
            if new_state != self._conviction_state:
                self._conviction_state = new_state
                self._reschedule_refresh()
            self._divergence_count = 0
            self._horizon_progress = 0.0
            self._prediction_horizon = len(prediction.get("pred_close", []))

        candles = candles or chart.candles
        if candles and not candle_data_age:
            candle_data_age = getattr(chart, "data_age_seconds", None)
        accuracy_records = self._store.get_comparisons(self._symbol, candles)
        self._update_all(
            candles, prediction, dqg, accuracy_records, candle_data_age=candle_data_age
        )

        if candles:
            digest = hash(tuple(c.get("close", 0) for c in candles[-10:]))
            if digest == self._last_candle_digest:
                self._stale_cycles += 1
            else:
                self._stale_cycles = 0
                self._stale_skip_until = 0
            self._last_candle_digest = digest
            if self._stale_cycles >= 3:
                self._stale_skip_until = time.time() + 120

        self._refresh_mtf()

        self._fetch_in_progress = False
        if self._fetch_pending_params:
            self._fetch_pending_params.clear()
            self._load_data()

    def _refresh_data(self) -> None:
        self._load_data()

    async def _refresh_market_context(self) -> None:
        ctx = await fetch_market_context()
        if ctx:
            self._market_ctx = ctx
            mkt_panel = self.query_one("#panel-market", MarketPanel)
            mkt_panel.update_data(self._market_ctx)

    async def _refresh_mtf(self) -> None:
        mtf = await fetch_multi_timeframe(self._symbol)
        if mtf:
            self._mtf_data = mtf

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip().upper()
        if val:
            self._ltp = None
            self._prev_ltp = None
            self._symbol = val
            chart = self.query_one(CandleChart)
            chart._sym = val
            chart.refresh()
            if self._last_info_kwargs:
                kwargs = dict(self._last_info_kwargs)
                kwargs["symbol"] = val
                info = self.query_one("#info-bar", InfoBar)
                info.update(InfoBar.make(**kwargs))
            reconnect_symbol_ws(
                self._symbol,
                on_tick=self._on_ws_tick,
                on_prediction=self._on_ws_prediction,
            )
            self._load_data()
        inp = self.query_one("#ticker-input", Input)
        inp.placeholder = f"Enter symbol — current: {self._symbol}"
        inp.clear()

    def action_cycle_timeframe(self) -> None:
        idx = TIMEFRAMES.index(self._timeframe) if self._timeframe in TIMEFRAMES else 4
        self._timeframe = TIMEFRAMES[(idx + 1) % len(TIMEFRAMES)]
        self._load_data()

    def action_toggle_overlay(self) -> None:
        self._show_prediction = not self._show_prediction
        self.refresh()

    def action_cycle_candle_limit(self) -> None:
        idx = CANDLE_LIMITS.index(self._candle_limit)
        self._candle_limit = CANDLE_LIMITS[(idx + 1) % len(CANDLE_LIMITS)]
        self._load_data()

    def action_refresh_now(self) -> None:
        self._force_refresh = True
        self._load_data()

    def action_toggle_volume(self) -> None:
        self._show_volume = not self._show_volume
        vol = self.query_one("#vol-hist", VolumeHistogram)
        vol.display = self._show_volume

    def action_toggle_levels(self) -> None:
        self._show_levels = not self._show_levels
        self._load_data()

    def action_cycle_band(self) -> None:
        self._band_mode = (self._band_mode + 1) % 3
        chart = self.query_one(CandleChart)
        chart.band_mode = self._band_mode
        chart.refresh()

    def action_toggle_model(self) -> None:
        self._show_model_panel = not self._show_model_panel
        panel = self.query_one("#panel-model", ModelPanel)
        panel.display = self._show_model_panel

    def action_toggle_market(self) -> None:
        self._show_market_panel = not self._show_market_panel
        panel = self.query_one("#panel-market", MarketPanel)
        panel.display = self._show_market_panel

    def action_open_alerts(self) -> None:
        self.push_screen(AlertOverlay())

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())


class InfoBar(Static):
    @staticmethod
    def make(
        symbol: str,
        dqg_status: str = "",
        coverage: float = 0.0,
        latency: float | None = None,
        model_version: str = "",
        mae: str = "",
        dir_acc: str = "",
        n_candles: int = 0,
        show_overlay: bool = True,
        timeframe: str = "5min",
        candle_limit: int = 200,
        last_updated: str = "",
        cached: bool = False,
        data_age_str: str = "",
        sparkline: str = "",
        flash_msg: str = "",
        ltp_err: str = "",
        ltp_change: str = "",
        ws_connected: bool = True,
    ) -> Text:
        parts = []

        dqg_col = {"PASS": "bold green", "FAIL": "bold red", "PARTIAL": "bold yellow"}
        dqg_st = dqg_col.get(dqg_status, "dim white")
        parts.append(f"DQG: [{dqg_st}]{dqg_status:<6}[/]")

        if not ws_connected:
            parts.append("[bold red]WS:OFF[/]")

        if ltp_change:
            parts.append(ltp_change)

        if latency is not None:
            lat_col = (
                "bold green"
                if latency < 150
                else ("bold yellow" if latency < 300 else "bold red")
            )
            parts.append(f"Lat:[{lat_col}]{latency:.0f}ms[/]")
            if sparkline:
                parts.append(f"[dim]{sparkline}[/]")

        if coverage > 0:
            parts.append(f"Cov: {coverage:.1f}%")
            parts.append(f"{n_candles}c")

        if model_version:
            mv = model_version[-8:] if len(model_version) > 8 else model_version
            parts.append(f"Model: {mv}")

        if mae:
            parts.append(f"MAE: {mae}")
        if dir_acc:
            parts.append(f"Dir: {dir_acc}")
        if cached:
            parts.append("[dim]cached[/]")

        overlay_st = "bold green" if show_overlay else "dim white"
        parts.append(
            f"[{overlay_st}]P:ON[/]" if show_overlay else f"[{overlay_st}]P:OFF[/]"
        )

        parts.append(f"[dim]{candle_limit}c[/]")
        if data_age_str:
            parts.append(f"[dim]{data_age_str}[/]")
        if last_updated:
            parts.append(f"[dim]{last_updated}[/]")

        if ltp_err:
            parts.append(f"[bold magenta]{ltp_err}[/]")

        if flash_msg:
            parts.append(f"[bold red]{flash_msg}[/]")

        keys_hint = "[dim]\\[t]tf \\[r]ref \\[v]vol \\[k]lvl \\[b]band \\[m]mdl \\[i]mkt \\[a]alrt[/]"
        parts.append(keys_hint)

        text = "  |  ".join(parts)
        return Text.from_markup(f"\n  {text}\n")


class CandleChart(Widget):
    def __init__(self, symbol: str = "", timeframe: str = "5min") -> None:
        super().__init__()
        self._sym = (symbol or DEFAULT_SYMBOL).upper()
        self._tf = timeframe
        self.candles: list[dict] = []
        self.pred_close: list[float] | None = None
        self.pred_timestamps: list[str] | None = None
        self.pred_upper: list[float] | None = None
        self.pred_lower: list[float] | None = None
        self.band_mode: int = 0
        self.accuracy_data: list[dict] | None = None
        self.last_close: float | None = None
        self.dqg_status: str = ""
        self.coverage: float = 0.0
        self.latency: float | None = None
        self.model_version: str = ""
        self.mae: str = ""
        self.dir_acc: str = ""
        self.error_msg: str = ""
        self.last_updated: str = ""
        self.is_refreshing: bool = False
        self.cached: bool = False
        self.data_age_seconds: float | None = None
        self.key_levels: dict[str, float] | None = None
        self.show_levels: bool = False
        self.show_band_label: str = ""
        self.ltp: float | None = None
        self.conviction_state: str = ""

    def update_data(
        self,
        candles: list[dict],
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        pred_close: list[float] | None = None,
        pred_timestamps: list[str] | None = None,
        pred_upper: list[float] | None = None,
        pred_lower: list[float] | None = None,
        band_mode: int = 0,
        accuracy_data: list[dict] | None = None,
        last_close: float | None = None,
        dqg_status: str = "",
        coverage: float = 0.0,
        latency: float | None = None,
        model_version: str = "",
        mae: str = "",
        dir_acc: str = "",
        error_msg: str = "",
        last_updated: str = "",
        is_refreshing: bool = False,
        cached: bool = False,
        data_age_seconds: float | None = None,
        key_levels: dict[str, float] | None = None,
        show_levels: bool = False,
        show_band_label: str = "",
        ltp: float | None = None,
        conviction_state: str = "",
    ) -> None:
        self.candles = candles
        if symbol is not None:
            self._sym = symbol.upper()
        if timeframe is not None:
            self._tf = timeframe
        self.pred_close = pred_close
        self.pred_timestamps = pred_timestamps
        self.pred_upper = pred_upper
        self.pred_lower = pred_lower
        self.band_mode = band_mode
        self.accuracy_data = accuracy_data
        self.last_close = last_close
        self.dqg_status = dqg_status
        self.coverage = coverage
        self.latency = latency
        self.model_version = model_version
        self.mae = mae
        self.dir_acc = dir_acc
        self.error_msg = error_msg
        self.last_updated = last_updated
        self.is_refreshing = is_refreshing
        self.cached = cached
        self.data_age_seconds = data_age_seconds
        self.key_levels = key_levels
        self.show_levels = show_levels
        self.show_band_label = show_band_label
        self.ltp = ltp
        self.conviction_state = conviction_state
        self.refresh()

    def render(self) -> Text:
        w = self.size.width
        h = self.size.height
        sym = self._sym
        tf = self._tf
        return c.render(
            self.candles,
            w,
            h,
            symbol=sym,
            timeframe=tf,
            pred_close=self.pred_close,
            pred_timestamps=self.pred_timestamps,
            pred_upper=self.pred_upper,
            pred_lower=self.pred_lower,
            band_mode=self.band_mode,
            accuracy=self.accuracy_data,
            show_volume=True,
            dqg_status=self.dqg_status,
            coverage=self.coverage,
            mae=self.mae,
            dir_acc=self.dir_acc,
            last_updated=self.last_updated,
            is_refreshing=self.is_refreshing,
            cached=self.cached,
            data_age_seconds=self.data_age_seconds,
            key_levels=self.key_levels,
            show_levels=self.show_levels,
            show_band_label=self.show_band_label,
            ltp=self.ltp,
            conviction_state=self.conviction_state,
        )


logger = logging.getLogger("kronos.tui")
_log_handler: logging.Handler | None = None


def _setup_logging(debug: bool = False) -> None:
    global _log_handler
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    logger.setLevel(level)
    logger.addHandler(handler)
    _log_handler = handler


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kronos NSE Terminal UI v2")
    parser.add_argument(
        "symbol",
        nargs="?",
        default=DEFAULT_SYMBOL,
        help="Initial symbol (default: RELIANCE)",
    )
    parser.add_argument(
        "--timeframe",
        "-tf",
        default="5min",
        help="Timeframe: 5min, 1day (default: 5min)",
    )
    parser.add_argument(
        "--candles",
        "-c",
        type=int,
        default=200,
        choices=CANDLE_LIMITS,
        help="Candle count (50/100/200, default: 200)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    _setup_logging(args.debug)

    app = KronosTUI(
        initial_symbol=args.symbol.upper(),
        initial_timeframe=args.timeframe,
    )
    app._candle_limit = args.candles
    try:
        app.run()
    finally:
        try:
            asyncio.run(close_fetcher())
        except (RuntimeError, OSError):
            pass


if __name__ == "__main__":
    main()
