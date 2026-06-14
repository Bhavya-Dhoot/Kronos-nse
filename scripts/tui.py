#!/usr/bin/env python3
"""Kronos NSE full terminal user interface — Textual TUI.

Usage:
  python scripts/tui.py
  python scripts/tui.py RELIANCE
  python scripts/tui.py --timeframe 1day
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Static

from scripts.tui_lib import chart as c
from scripts.tui_lib.fetcher import fetch_candles, fetch_dqg, fetch_prediction
from scripts.tui_lib.store import AccuracyStore

VERSION = "1.2.0"
DEFAULT_SYMBOL = "RELIANCE"
CANDLE_LIMITS = [50, 100, 200]


def _fmt_age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


# ── CandleChart Widget ─────────────────────────────────────────────────────────


class CandleChart(Widget):
    """Custom widget rendering a terminal candlestick chart."""

    def __init__(
        self,
        symbol: str = "",
        timeframe: str = "5min",
    ) -> None:
        super().__init__()
        self._sym = (symbol or DEFAULT_SYMBOL).upper()
        self._tf = timeframe
        self.candles: list[dict] = []
        self.pred_close: list[float] | None = None
        self.pred_timestamps: list[str] | None = None
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

    def update_data(
        self,
        candles: list[dict],
        *,
        pred_close: list[float] | None = None,
        pred_timestamps: list[str] | None = None,
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
    ) -> None:
        self.candles = candles
        self.pred_close = pred_close
        self.pred_timestamps = pred_timestamps
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
        self.refresh()

    def render(self) -> Text:
        w = max(self.size.width, 20)
        h = max(self.size.height, 5)

        if self.error_msg and not self.candles:
            return Text(f"\n  {self.error_msg}", style="bold red")

        if not self.candles:
            return Text(f"\n  Loading {self._sym}...", style="dim white")

        return c.render(
            self.candles,
            w,
            h,
            symbol=self._sym,
            timeframe=self._tf,
            pred_close=self.pred_close,
            pred_timestamps=self.pred_timestamps,
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
        )


# ── InfoBar Widget ─────────────────────────────────────────────────────────────


class InfoBar(Static):
    """Bottom info bar showing stats."""

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
    ) -> Text:
        parts = []

        dqg_col = {"PASS": "bold green", "FAIL": "bold red", "PARTIAL": "bold yellow"}
        dqg_st = dqg_col.get(dqg_status, "dim white")
        parts.append(f"DQG: [{dqg_st}]{dqg_status:<6}[/]")

        parts.append(f"Cov: {coverage:.1f}%")
        parts.append(f"Candles: {n_candles}")

        if latency is not None:
            parts.append(f"Lat: {latency:.0f}ms")
            if cached:
                parts.append("[dim]cached[/]")

        if model_version:
            mv = model_version[-12:] if len(model_version) > 12 else model_version
            parts.append(f"Model: {mv}")

        if mae:
            parts.append(f"MAE: {mae}")
        if dir_acc:
            parts.append(f"Dir: {dir_acc}")

        overlay_st = "bold green" if show_overlay else "dim white"
        parts.append(
            f"[{overlay_st}]P:ON[/]" if show_overlay else f"[{overlay_st}]P:OFF[/]"
        )

        parts.append(f"[dim]{candle_limit}c[/]")
        if data_age_str:
            parts.append(f"[dim]{data_age_str}[/]")
        if last_updated:
            parts.append(f"[dim]{last_updated}[/]")

        text = "  |  ".join(parts)
        return Text.from_markup(f"\n  {text}\n")


# ── Help Screen ────────────────────────────────────────────────────────────────


class HelpScreen(ModalScreen[None]):
    """Help overlay screen."""

    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(
                "\n\n\n"
                "  [bold]Kronos NSE TUI — Help[/]\n\n"
                "  [bold]q[/]     Quit\n"
                "  [bold]t[/]     Toggle timeframe (5min ↔ 1day)\n"
                "  [bold]p[/]     Toggle prediction overlay\n"
                "  [bold]c[/]     Cycle candle count (50/100/200)\n"
                "  [bold]r[/]     Force refresh\n"
                "  [bold]h[/]     Show this help\n\n"
                "  Type a ticker in the input bar and press Enter to switch symbols.\n\n"
                "  [dim]DQG = Data Quality Gate — checks data freshness & coverage.\n"
                "  The chart header shows confidence (DQG/Cov/Dir/MAE) in the top-left.\n"
                "  Prediction dots (cyan •) overlay on top of actual candles.\n"
                "  Accuracy is computed when prediction timestamps mature into candles.[/]\n"
            )
        )

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
        ("h", "dismiss", "Close"),
    ]


# ── Main App ───────────────────────────────────────────────────────────────────


class KronosTUI(App):
    """Kronos NSE Terminal User Interface."""

    TITLE = "Kronos NSE"
    SUB_TITLE = f"v{VERSION}"

    CSS = """
    Screen {
        layout: vertical;
    }

    CandleChart {
        height: 1fr;
        margin: 0 1;
    }

    #info-bar {
        height: 3;
        margin: 0 1;
    }

    #bottom-bar {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }

    Input {
        width: 100%;
    }

    HelpScreen {
        align: center middle;
    }

    HelpScreen > Static {
        width: 60%;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "toggle_timeframe", "Timeframe"),
        ("p", "toggle_overlay", "Overlay"),
        ("c", "cycle_candle_limit", "Candles"),
        ("r", "refresh_now", "Refresh"),
        ("h", "show_help", "Help"),
    ]

    def __init__(
        self,
        initial_symbol: str = "",
        initial_timeframe: str = "5min",
    ) -> None:
        super().__init__()
        self._symbol = (initial_symbol or DEFAULT_SYMBOL).upper()
        self._timeframe = initial_timeframe
        self._show_prediction = True
        self._candle_limit = 200
        self._last_updated = ""
        self._cached = False
        self._force_refresh = False
        self._store = AccuracyStore(max_per_symbol=20)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield CandleChart(symbol=self._symbol, timeframe=self._timeframe)
        yield InfoBar(id="info-bar")
        with Container(id="bottom-bar"):
            yield Input(
                id="ticker-input",
                placeholder=f"Enter symbol (e.g. RELIANCE, TCS, NIFTY50) — current: {self._symbol}",
            )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_timer = self.set_interval(30, self._refresh_data)
        self._load_data()

    def _update_chart(
        self, candles, prediction, dqg, accuracy_records, candle_data_age=None
    ) -> None:
        chart = self.query_one(CandleChart)

        pred_close = None
        pred_ts = None
        if prediction and self._show_prediction:
            pred_close = prediction.get("pred_close")
            pred_ts = prediction.get("timestamps")
            self._store.add(self._symbol, prediction)

        last_c = candles[-1].get("close") if candles else None

        dqg_status = ""
        coverage = 0.0
        if dqg:
            dqg_status = dqg.get("status", "")
            coverage = dqg.get("coverage_pct", 0.0)

        latency = prediction.get("latency_ms") if prediction else None
        model_ver = prediction.get("model_version", "") if prediction else ""
        if not model_ver and dqg:
            model_ver = dqg.get("model_version", "")

        self._cached = prediction.get("cached", False) if prediction else False
        data_age = candle_data_age or (
            prediction.get("data_age_seconds") if prediction else None
        )

        accuracy_data = None
        mae_str = ""
        dir_str = ""
        if accuracy_records:
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
            if accuracy_records and accuracy_records[-1].accuracy_checked:
                last = accuracy_records[-1]
                if last.mae is not None:
                    mae_str = f"{last.mae:.2f}"
                if last.dir_accuracy is not None:
                    dir_str = f"{last.dir_accuracy:.0%}"

        self._last_updated = datetime.now().strftime("%H:%M:%S")

        chart.update_data(
            candles,
            pred_close=pred_close,
            pred_timestamps=pred_ts,
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
        )

        info = self.query_one("#info-bar", InfoBar)
        age_str = _fmt_age(data_age) if data_age is not None else ""
        info.update(
            InfoBar.make(
                symbol=self._symbol,
                dqg_status=dqg_status,
                coverage=coverage,
                latency=latency,
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
            )
        )

    def _load_data(self) -> None:
        self.run_worker(self._run_fetch_chain())

    async def _run_fetch_chain(self) -> None:
        symbol = self._symbol
        tf = self._timeframe
        chart = self.query_one(CandleChart)

        chart.is_refreshing = True
        chart.refresh()

        force = self._force_refresh
        self._force_refresh = False

        try:
            candles_task = fetch_candles(symbol, timeframe=tf, limit=self._candle_limit)
            pred_task = fetch_prediction(symbol, timeframe=tf, force_refresh=force)
            dqg_task = fetch_dqg(symbol, timeframe=tf)
            results = await asyncio.gather(
                candles_task,
                pred_task,
                dqg_task,
                return_exceptions=True,
            )
        except Exception as e:
            chart.is_refreshing = False
            if not chart.candles:
                chart.update_data([], error_msg=f"Error: {e}")
            else:
                chart.refresh()
            return

        _candles_result, prediction, dqg = results
        if isinstance(_candles_result, Exception):
            candles = None
            candle_data_age = None
        elif isinstance(_candles_result, tuple):
            candles, candle_data_age = _candles_result
        else:
            candles = _candles_result
            candle_data_age = None
        if isinstance(prediction, Exception):
            prediction = None
        if isinstance(dqg, Exception):
            dqg = None

        chart.is_refreshing = False

        if (candles is None or not candles) and (prediction is None or not prediction):
            if not chart.candles:
                chart.update_data([], error_msg="No data available for this symbol")
            else:
                chart.refresh()
            return

        candles = candles or chart.candles
        accuracy_records = self._store.get_comparisons(self._symbol, candles)
        self._update_chart(
            candles, prediction, dqg, accuracy_records, candle_data_age=candle_data_age
        )

    def _refresh_data(self) -> None:
        self._load_data()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip().upper()
        if val:
            self._symbol = val
            self._load_data()
        inp = self.query_one("#ticker-input", Input)
        inp.placeholder = f"Enter symbol — current: {self._symbol}"
        inp.clear()

    def action_toggle_timeframe(self) -> None:
        self._timeframe = "1day" if self._timeframe == "5min" else "5min"
        self._load_data()

    def action_toggle_overlay(self) -> None:
        self._show_prediction = not self._show_prediction
        self._load_data()

    def action_cycle_candle_limit(self) -> None:
        idx = CANDLE_LIMITS.index(self._candle_limit)
        self._candle_limit = CANDLE_LIMITS[(idx + 1) % len(CANDLE_LIMITS)]
        self._load_data()

    def action_refresh_now(self) -> None:
        self._force_refresh = True
        self._load_data()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())


# ── entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kronos NSE Terminal UI")
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
    args = parser.parse_args()

    app = KronosTUI(
        initial_symbol=args.symbol.upper(),
        initial_timeframe=args.timeframe,
    )
    app._candle_limit = args.candles
    app.run()


if __name__ == "__main__":
    main()
