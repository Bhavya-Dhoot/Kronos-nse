"""Right sidebar panel widgets for Kronos NSE TUI v2."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.widgets import Static

from scripts.tui_lib.chart import _fmt_price
from scripts.tui_lib.levels import _to_float


class PredictionPanel(Static):
    def __init__(self, panel_width: int = 38, **kwargs):
        super().__init__(**kwargs)
        self._w = panel_width
        self._direction: str = "─"
        self._direction_label: str = "SIDEWAYS"
        self._probability: float = 50.0
        self._pred_horizon: int = 0
        self._confidence: float = 0.0
        self._confidence_str: str = ""
        self._band_active: bool = False
        self._pred_close: list[float] | None = None
        self._price_range: tuple[float, float] = (0, 0)
        self._dqg_status: str = ""
        self._dqg_detail: str = ""
        self._conviction_state: str = ""
        self._horizon_progress: float = 0.0
        self._prediction_age: str = ""

    def update_data(
        self,
        pred: dict[str, Any] | None = None,
        band_active: bool = False,
        price_low: float = 0,
        price_high: float = 0,
        dqg_status: str = "",
        dqg_detail: str = "",
        conviction_state: str = "",
        horizon_progress: float = 0.0,
        prediction_age: str = "",
    ) -> None:
        if pred and pred.get("pred_close"):
            pc = [_to_float(x, 0) for x in pred["pred_close"]]
            self._pred_close = pc
            self._pred_horizon = len(pc)
            first, last = pc[0], pc[-1]
            if last > first:
                self._direction = "▲"
                self._direction_label = "UP"
            elif last < first:
                self._direction = "▼"
                self._direction_label = "DOWN"
            else:
                self._direction = "─"
                self._direction_label = "SIDEWAYS"
            raw_conf = pred.get("confidence", pred.get("softmax_score", ""))
            if isinstance(raw_conf, str):
                self._confidence_str = raw_conf
                self._probability = (
                    50 if raw_conf == "LOW" else 65 if raw_conf == "MEDIUM" else 80
                )
            else:
                self._confidence_str = ""
                self._confidence = _to_float(raw_conf)
                self._probability = max(50, min(99, round(self._confidence * 100)))
        self._band_active = band_active
        self._price_range = (price_low, price_high)
        self._dqg_status = dqg_status
        self._dqg_detail = dqg_detail
        self._conviction_state = conviction_state
        self._horizon_progress = horizon_progress
        self._prediction_age = prediction_age
        self.refresh()

    def render(self) -> Text:
        w = self._w
        lines = []

        dir_color = (
            "bold green"
            if self._direction == "▲"
            else ("bold #ff2d5b" if self._direction == "▼" else "bold yellow")
        )
        lines.append("[bold]PREDICTION[/]".center(w))
        lines.append("")
        lines.append(
            f"  [{dir_color}]{self._direction} {self._direction_label}  {self._probability}%[/]"
        )

        bar_w = w - 6
        filled = max(1, round(bar_w * self._probability / 100))
        bar = "█" * filled + "░" * (bar_w - filled)
        lines.append(f"  {bar}")

        nh = self._pred_horizon
        if self._confidence_str:
            conf_color = (
                "bold green"
                if self._confidence_str == "HIGH"
                else ("bold yellow" if self._confidence_str == "MEDIUM" else "bold red")
            )
            lines.append(
                f"  [dim]Next {nh}c · Conf: [{conf_color}]{self._confidence_str}[/][/]"
            )
        else:
            lines.append(f"  [dim]Next {nh}c · Conf: {self._confidence:.2f}[/]")

        if self._pred_close and len(self._pred_close) >= 2:
            dot_width = min(w - 4, len(self._pred_close) * 2)
            step = max(1, len(self._pred_close) // (dot_width // 2))
            dot_col = "bold cyan"
            if self._conviction_state == "WATCHING":
                dot_col = "bold yellow"
            elif self._conviction_state == "DIVERGING":
                dot_col = "bold #ff2d5b"
            elif self._conviction_state == "STALE":
                dot_col = "dim white"
            dots = []
            for i in range(0, len(self._pred_close), step):
                dots.append(f"[{dot_col}]•[/]")
            lines.append(f"  {''.join(dots)}")

        # Conviction state + horizon progress
        if self._conviction_state:
            cs_colors = {
                "CONFIRMED": "bold green",
                "WATCHING": "bold yellow",
                "DIVERGING": "bold #ff2d5b",
                "STALE": "dim white",
                "INITIAL": "dim white",
            }
            cs_col = cs_colors.get(self._conviction_state, "dim white")
            lines.append(f"  [{cs_col}]{self._conviction_state}[/]")
            if self._horizon_progress > 0:
                bar_w = w - 8
                filled = round(bar_w * self._horizon_progress)
                bar = "▓" * filled + "░" * (bar_w - filled)
                pct = min(100, round(self._horizon_progress * 100))
                lines.append(f"  {bar} {pct}%")

        if self._prediction_age:
            lines.append(f"  [dim]Age: {self._prediction_age}[/]")

        if self._band_active:
            lines.append("  [dim]± 1σ band active[/]")

        if self._dqg_status in ("FAIL", "PARTIAL") and self._dqg_detail:
            lines.append(f"  [bold red]DQG:{self._dqg_status} {self._dqg_detail}[/]")
        elif self._dqg_status == "FAIL":
            lines.append("  [bold red]DQG:FAIL[/]")

        lines.append("")
        last_px = self._pred_close[-1] if self._pred_close else 0
        first_px = self._pred_close[0] if self._pred_close else 0
        if last_px and first_px:
            chg = last_px - first_px
            pct = (chg / first_px) * 100
            chg_color = "bold green" if chg >= 0 else "bold #ff2d5b"
            lines.append(
                f"  Price: {last_px:>10.2f}  [{chg_color}]{chg:+.2f} ({pct:+.2f}%)[/]"
            )

        text_str = "\n".join(lines)
        return Text.from_markup(text_str)


class RegimePanel(Static):
    def __init__(self, panel_width: int = 38, **kwargs):
        super().__init__(**kwargs)
        self._w = panel_width
        self._regime_data: dict = {}

    def update_data(self, regime: dict) -> None:
        self._regime_data = regime
        self.refresh()

    def render(self) -> Text:
        w = self._w
        lines = ["[bold]REGIME[/]".center(w)]
        lines.append("")

        if self._regime_data:
            label = self._regime_data.get("label", "─ RANGING")
            color = self._regime_data.get("color", "bold yellow")
            ds = self._regime_data.get("direction_strength", 0)
            bias = self._regime_data.get("bias", 50)
            lines.append(f"  [{color}]{label}[/]")
            bear_bias = 100 - bias
            lines.append(
                f"  [dim]Str: {ds:.1f} · Bias: {bias:.0f}% BULL / {bear_bias:.0f}% BEAR[/]"
            )
        else:
            lines.append("  [dim]computing...[/]")

        lines.append("")
        text_str = "\n".join(lines)
        return Text.from_markup(text_str)


class MarketPanel(Static):
    def __init__(self, panel_width: int = 38, **kwargs):
        super().__init__(**kwargs)
        self._w = panel_width
        self._ctx: dict[str, Any] = {}

    def update_data(self, ctx: dict[str, Any]) -> None:
        self._ctx = ctx
        self.refresh()

    def render(self) -> Text:
        w = self._w
        lines = ["[bold]MARKET CONTEXT[/]".center(w)]
        lines.append("")

        ctx = self._ctx
        vix = _to_float(ctx.get("vix"))
        pcr = _to_float(ctx.get("pcr"))
        max_pain = _to_float(ctx.get("max_pain"))
        iv_ce = _to_float(ctx.get("iv_ce"))
        iv_pe = _to_float(ctx.get("iv_pe"))

        if vix is not None and vix > 0:
            vix_color = (
                "bold green"
                if vix < 12
                else ("bold yellow" if vix < 20 else "bold red")
            )
            lines.append(f"  VIX: [{vix_color}]{vix:.2f}[/]")
        else:
            lines.append("  VIX: [dim]--[/]")

        if pcr is not None and pcr > 0:
            pcr_color = (
                "bold green"
                if pcr > 1.2
                else ("bold red" if pcr < 0.7 else "bold yellow")
            )
            lines.append(f"  PCR: [{pcr_color}]{pcr:.2f}[/]")
        else:
            lines.append("  PCR: [dim]--[/]")

        if max_pain is not None and max_pain > 0:
            lines.append(f"  Max Pain: [bold]{_fmt_price(max_pain)}[/]")
        else:
            lines.append("  Max Pain: [dim]--[/]")

        if iv_ce is not None and iv_pe is not None and iv_ce > 0 and iv_pe > 0:
            iv_diff_st = (
                "bold yellow"
                if abs(iv_ce - iv_pe) < 2
                else ("bold red" if iv_ce > iv_pe else "bold green")
            )
            lines.append(f"  [{iv_diff_st}]IV CE: {iv_ce:.2f}  IV PE: {iv_pe:.2f}[/]")
        else:
            lines.append("  IV: [dim]--[/]")

        fetched_at = _to_float(ctx.get("fetched_at"))
        if fetched_at is not None and fetched_at > 0:
            age_s = int(time.time() - fetched_at)
            if age_s < 120:
                age_str = f"[dim]{age_s}s ago[/]"
            elif age_s < 300:
                age_str = f"[bold yellow]{age_s}s ago[/]"
            else:
                age_str = f"[bold red]{age_s}s ago[/]"
            lines.append(f"  {age_str}")

        lines.append("")
        text_str = "\n".join(lines)
        return Text.from_markup(text_str)


class ModelPanel(Static):
    def __init__(self, panel_width: int = 38, **kwargs):
        super().__init__(**kwargs)
        self._w = panel_width
        self._store: Any = None
        self._ltp_accuracy: dict = {}

    def update_data(self, store: Any, ltp_accuracy: dict | None = None) -> None:
        self._store = store
        if ltp_accuracy is not None:
            self._ltp_accuracy = ltp_accuracy
        self.refresh()

    def render(self) -> Text:
        w = self._w
        lines = ["[bold]MODEL STATS[/]".center(w)]
        lines.append("")

        if self._store:
            s = self._store.session
            lines.append(
                f"  Acc/20: [bold]{s.acc20.pct():.1f}%[/]  Acc/50: [bold]{s.acc50.pct():.1f}%[/]"
            )
            lines.append(f"  Bull bias: {s.get_bull_bias():.0f}%")
            conf = _to_float(s.last_pred_confidence)
            lines.append(f"  Conf: [bold cyan]{conf:.2f}[/]")
            ltp = self._ltp_accuracy
            if ltp.get("count", 0) > 0:
                last_err = ltp.get("last_error")
                avg_err = ltp.get("avg_error", 0)
                dir_rate = ltp.get("direction_rate", 0)
                if last_err is not None:
                    lines.append(
                        f"  LTP-Err: [bold magenta]{last_err:.2f}[/] [dim]avg:{avg_err} dir:{dir_rate:.0f}%[/]"
                    )
            vol = s.get_vol_accuracy()
            if vol.get("count", 0) > 0:
                last_v = vol.get("last_error_pct")
                avg_v = vol.get("avg_error_pct", 0)
                v_dir = vol.get("direction_rate", 0)
                if last_v is not None:
                    lines.append(
                        f"  Vol-Err: [bold cyan]{last_v:.1f}%[/] [dim]avg:{avg_v:.1f}% dir:{v_dir:.0f}%[/]"
                    )
        else:
            lines.append("  Acc/20: [dim]--[/]  Acc/50: [dim]--[/]")
            lines.append("  Bull bias: [dim]--[/]")
            lines.append("  Conf: [dim]--[/]")

        lines.append("")
        text_str = "\n".join(lines)
        return Text.from_markup(text_str)


class LevelsPanel(Static):
    def __init__(self, panel_width: int = 38, **kwargs):
        super().__init__(**kwargs)
        self._w = panel_width
        self._levels: dict[str, float] = {}
        self._show: bool = True

    def update_data(self, levels: dict[str, float], show: bool = True) -> None:
        self._levels = levels
        self._show = show
        self.refresh()

    def render(self) -> Text:
        w = self._w
        lines = ["[bold]KEY LEVELS[/]".center(w)]
        lines.append("")

        if not self._show or not self._levels:
            lines.append("  [dim]hidden[/]")
        else:
            levels = self._levels
            now = _to_float(levels.get("NOW"))

            resistances = [("R3", ORG), ("R2", ORG), ("R1", ORG), ("PDH", ORG)]
            supports = [("S1", CYN), ("S2", CYN), ("S3", CYN), ("PDL", CYN)]

            for label, color in resistances:
                v = _to_float(levels.get(label))
                if v is not None and (now is None or v > now):
                    lines.append(f"  [{color}]{label}: {v:>10.2f}[/]")

            vwap = _to_float(levels.get("VWAP"))
            if vwap is not None:
                vwap_color = YLW if vwap != (now or 0) else "bold green"
                lines.append(f"  [{vwap_color}]VWAP: {vwap:>9.2f}[/]")

            poc = _to_float(levels.get("POC"))
            if poc is not None and poc != (now or 0):
                lines.append(f"  [bold #ffcc02]POC: {poc:>10.2f}[/]")

            if now is not None:
                lines.append(f"  [bold green]NOW: {now:>10.2f}[/]")

            for label, color in supports:
                v = _to_float(levels.get(label))
                if v is not None and now is not None and v < now:
                    lines.append(f"  [{color}]{label}: {v:>10.2f}[/]")

            lines.append("")
        text_str = "\n".join(lines)
        return Text.from_markup(text_str)


GRN = "bold green"
RED = "bold #ff2d5b"
CYN = "bold #00e5ff"
YLW = "bold #ffcc02"
ORG = "bold #ff9800"
DIM = "dim white"
