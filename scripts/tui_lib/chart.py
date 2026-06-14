"""Terminal candlestick chart renderer — v2 with key levels, confidence bands."""

from __future__ import annotations

import math
from typing import Any

from rich.text import Text

GRN = "bold green"
RED = "bold red"
CYN = "bold cyan"
YLW = "bold yellow"
DIM = "dim white"
WHT = "bold white"
GRY = "grey62"
ORG = "bold #ff9800"
PPL = "bold #bb86fc"
MGN = "bold #ff2d5b"


def _candle_char(o, h, lo, c, row_top, row_bot, up):
    body_top = max(o, c)
    body_bot = min(o, c)
    if row_bot > h or row_top < lo:
        return (" ", "")
    clr = "green" if up else "red"
    clr_b = f"bold {clr}"
    if row_bot <= body_top and row_top >= body_bot:
        return ("▉", clr_b)
    if row_bot <= h and row_top >= body_top:
        return ("│", clr_b)
    if row_bot <= body_bot and row_top >= lo:
        return ("│", clr_b)
    return (" ", "")


def _fmt_age(seconds: Any) -> str:
    try:
        seconds = float(seconds)
    except (ValueError, TypeError):
        return "--"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _fmt_price(p: Any) -> str:
    try:
        p = float(p)
    except (ValueError, TypeError):
        return "--"
    if p >= 100000:
        return f"{p:,.0f}"
    if p >= 1000:
        return f"{p:,.2f}"
    return f"{p:.2f}"


def _nice_ticks(low: float, high: float, n: int = 5) -> list[float]:
    if high <= low:
        return [low]
    step = (high - low) / max(n - 1, 1)
    if step == 0:
        return [low]
    exp = int(math.floor(math.log10(step)))
    mag = 10**exp
    step = round(step / mag) * mag
    if step == 0:
        step = mag / 10
    start = math.ceil(low / step) * step
    ticks = []
    v = start
    precision = max(0, -exp + 2)
    while v <= high + 1e-9:
        ticks.append(round(v, precision))
        v += step
    return ticks or [low]


def render(
    candles: list[dict[str, Any]],
    width: int,
    height: int,
    *,
    symbol: str = "",
    timeframe: str = "",
    pred_close: list[float] | None = None,
    pred_timestamps: list[str] | None = None,
    pred_upper: list[float] | None = None,
    pred_lower: list[float] | None = None,
    band_mode: int = 1,
    accuracy: list[dict[str, Any]] | None = None,
    show_volume: bool = True,
    dqg_status: str = "",
    coverage: float = 0.0,
    mae: str = "",
    dir_acc: str = "",
    last_updated: str = "",
    is_refreshing: bool = False,
    cached: bool = False,
    data_age_seconds: float | None = None,
    key_levels: dict[str, float] | None = None,
    show_levels: bool = False,
    show_band_label: str = "",
    ltp: float | None = None,
    conviction_state: str = "",
) -> Text:
    if not candles or height < 5 or width < 20:
        return Text("Not enough data to render chart", style=DIM)

    axis_w = 11
    vol_h = 2 if show_volume else 0
    header_h = 1
    chart_h = height - header_h - vol_h - 1
    chart_h = max(chart_h, 3)
    candle_w = width - axis_w
    candle_w = max(candle_w, 3)

    pred = list(pred_close) if pred_close else []
    n_pred = len(pred)

    levels = key_levels or {}

    n_candle_cols = candle_w
    if n_pred > 0:
        n_candle_cols = max(candle_w - n_pred - 1, 1)

    display = (
        list(candles[-n_candle_cols:])
        if n_candle_cols < len(candles)
        else list(candles)
    )
    len(candles) - len(display)
    n_candles = len(display)

    _highs = []
    _lows = []
    for c in display:
        try:
            _highs.append(float(c.get("high", 0)))
            _lows.append(float(c.get("low", 0)))
        except (ValueError, TypeError):
            _highs.append(0)
            _lows.append(0)
    price_high = max(_highs) if _highs else 0
    price_low = min(_lows) if _lows else 0
    if pred:
        pred_f = [float(x) for x in pred]
        price_high = max(price_high, max(pred_f))
        price_low = min(price_low, min(pred_f))
    if pred_upper:
        pu_f = [float(x) for x in pred_upper]
        price_high = max(price_high, max(pu_f))
    if pred_lower:
        pl_f = [float(x) for x in pred_lower]
        price_low = min(price_low, min(pl_f))
    if accuracy:
        for a in accuracy:
            pd = a.get("predicted")
            if pd:
                pd_f = [float(x) for x in pd]
                price_high = max(price_high, max(pd_f))
                price_low = min(price_low, min(pd_f))
            ac = a.get("actual_close")
            if ac is not None:
                try:
                    price_high = max(price_high, float(ac))
                    price_low = min(price_low, float(ac))
                except (ValueError, TypeError):
                    pass

    pad = (price_high - price_low) * 0.05 or 1
    price_high += pad
    price_low -= pad
    price_range = price_high - price_low

    ticks = _nice_ticks(price_low, price_high, max(3, chart_h // 3))
    ticks = [t for t in ticks if price_low <= t <= price_high]

    pred_rows = []
    for pv in pred:
        if price_range > 0:
            r = int((price_high - pv) / price_range * chart_h)
            r = max(0, min(chart_h - 1, r))
        else:
            r = chart_h // 2
        pred_rows.append(r)

    upper_rows = []
    if pred_upper:
        for uv in pred_upper:
            if price_range > 0:
                r = int((price_high - uv) / price_range * chart_h)
                r = max(0, min(chart_h - 1, r))
            else:
                r = chart_h // 2
            upper_rows.append(r)

    lower_rows = []
    if pred_lower:
        for lv in pred_lower:
            if price_range > 0:
                r = int((price_high - lv) / price_range * chart_h)
                r = max(0, min(chart_h - 1, r))
            else:
                r = chart_h // 2
            lower_rows.append(r)

    ltp_row = -1
    if ltp is not None and price_range > 0:
        r = int((price_high - ltp) / price_range * chart_h)
        ltp_row = max(0, min(chart_h - 1, r))

    result = Text()

    last_px = float(display[-1].get("close", 0)) if display else 0
    first_o = float(display[0].get("open", last_px)) if display else last_px
    chg = last_px - first_o
    pct = (chg / first_o) * 100 if first_o else 0
    chg_sym = "+" if chg >= 0 else ""
    chg_tag = "bold green" if chg >= 0 else "bold red"

    parts = []
    parts.append(f" {symbol:<12} {timeframe:<6}")
    if ltp is not None:
        parts.append(f"[{MGN}]LTP: {_fmt_price(ltp):>12}[/]")
    else:
        parts.append(f"Last: {_fmt_price(last_px):>12}")
    parts.append(f"[{chg_tag}]{chg_sym}{chg:.2f} ({chg_sym}{pct:.2f}%)[/]")

    dqg_col_map = {"PASS": "bold green", "FAIL": "bold red", "PARTIAL": "bold yellow"}
    dqg_st = dqg_col_map.get(dqg_status, "dim white")
    if dqg_status:
        parts.append(f"[{dqg_st}]DQG:{dqg_status}[/]")

    if coverage > 0:
        cov_col = "bold green" if coverage >= 90 else "bold yellow"
        parts.append(f"[{cov_col}]Cov:{coverage:.0f}%[/]")

    if show_band_label:
        parts.append(f"[dim]{show_band_label}[/]")

    if mae:
        parts.append(f"MAE:{mae}")
    if dir_acc:
        dir_col = (
            "bold green"
            if dir_acc.endswith("%") and float(dir_acc.rstrip("%")) >= 60
            else YLW
        )
        parts.append(f"[{dir_col}]Dir:{dir_acc}[/]")

    if cached:
        parts.append("[dim]cached[/]")
    if is_refreshing:
        parts.append("[dim]⟳[/]")

    if data_age_seconds is not None:
        age_str = _fmt_age(data_age_seconds)
        if data_age_seconds < 60:
            age_col = "bold green"
        elif data_age_seconds < 300:
            age_col = "bold yellow"
        else:
            age_col = "bold red"
        parts.append(f"[{age_col}]{age_str}[/]")

    if conviction_state:
        cs_colors = {
            "CONFIRMED": "bold green",
            "WATCHING": "bold yellow",
            "DIVERGING": "bold #ff2d5b",
            "STALE": "dim white",
            "INITIAL": "dim white",
        }
        cs_col = cs_colors.get(conviction_state, "dim white")
        parts.append(f"[{cs_col}]{conviction_state[:4]}[/]")

    if last_updated:
        parts.append(f"[dim]{last_updated}[/]")

    hdr = "  ".join(parts)
    result.append(Text.from_markup(hdr[:width]))
    result.append("\n")

    level_rows: dict[str, int] = {}
    if show_levels and levels and price_range > 0:
        for k, v in levels.items():
            if k == "NOW":
                continue
            if price_low <= v <= price_high:
                r = int((price_high - v) / price_range * chart_h)
                r = max(0, min(chart_h - 1, r))
                level_rows[k] = r

    for row in range(chart_h):
        frac_top = row / chart_h
        frac_bot = (row + 1) / chart_h
        price_top = price_high - frac_top * price_range
        price_bot = price_high - frac_bot * price_range

        total_cells = n_candles + 1 + n_pred
        cells: list[tuple[str, str]] = [("", "")] * total_cells

        for ci, c in enumerate(display):
            ch, st = _candle_char(
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                price_top,
                price_bot,
                c["close"] >= c["open"],
            )
            cells[ci] = (ch, st)

        gap_pos = n_candles
        if gap_pos < total_cells:
            cells[gap_pos] = ("│", "bold white") if n_pred > 0 else (" ", "")

        level_label = ""
        if show_levels and level_rows:
            for k, rnum in level_rows.items():
                if rnum == row:
                    lc = {
                        "R3": ORG,
                        "R2": ORG,
                        "R1": ORG,
                        "S1": CYN,
                        "S2": CYN,
                        "S3": CYN,
                        "VWAP": YLW,
                        "PDH": ORG,
                        "PDL": CYN,
                    }.get(k, DIM)
                    level_label += f"[{lc}]{k[:3]}[/] "

        band_fill = [False] * n_pred
        if band_mode > 0 and upper_rows and lower_rows:
            for pi in range(min(n_pred, len(upper_rows), len(lower_rows))):
                if lower_rows[pi] <= row <= upper_rows[pi]:
                    band_fill[pi] = True

        if ltp_row == row:
            for ci in range(total_cells):
                ch, st = cells[ci]
                if ch == " ":
                    cells[ci] = ("╌", MGN)
                elif ch == "│":
                    cells[ci] = ("┼", MGN)

        # Prediction dot color based on conviction
        pred_dot_col = CYN
        if conviction_state == "WATCHING":
            pred_dot_col = YLW
        elif conviction_state == "DIVERGING":
            pred_dot_col = MGN
        elif conviction_state == "STALE":
            pred_dot_col = DIM

        for pi in range(n_pred):
            col = n_candles + 1 + pi
            if col >= total_cells:
                break
            show_dot = pred_rows[pi] == row if n_pred > 0 else False

            if band_mode == 0 and show_dot:
                cells[col] = ("•", pred_dot_col)
            elif band_mode == 1 and show_dot:
                cells[col] = ("•", pred_dot_col)
            elif band_mode == 1 and band_fill[pi]:
                cells[col] = ("·", "dim cyan")
            elif band_mode == 2 and band_fill[pi]:
                cells[col] = ("·", "dim cyan")
            else:
                cells[col] = (" ", "")

        if accuracy:
            for ai, a in enumerate(accuracy):
                actual = a.get("actual_close")
                if actual is not None and price_bot <= actual <= price_top:
                    acol = n_candles + 1 + ai
                    if acol < total_cells:
                        cells[acol] = ("▊", YLW)

        line = Text()
        for ch, st in cells:
            line.append(ch, style=st)

        if level_label:
            line.append(" ")
            line.append(Text.from_markup(level_label.strip()))

        if ltp_row == row and ltp is not None:
            ltp_label = f" LTP:{_fmt_price(ltp)}"
            line.append(Text.from_markup(f"[{MGN}]{ltp_label}[/]"))

        tick_label = ""
        for t in ticks:
            if price_bot <= t <= price_top:
                tick_label = _fmt_price(t)
                break
        line.append(Text(f" {tick_label:>{axis_w - 1}}", style=DIM))
        result.append(line)
        result.append("\n")

    all_vol_zero = display and all(c["volume"] == 0 for c in display)
    show_v = show_volume and display and not all_vol_zero
    if show_v:
        vols = [v for c in display if (v := c.get("volume")) is not None]
        v_max = max(vols) if vols and max(vols) > 0 else 1
        avg_vol = sum(vols) / len(vols) if vols else 0
        avg_row_frac = avg_vol / v_max if v_max > 0 else 0
        for vrow in range(vol_h):
            vline = Text()
            frac_top_v = 1 - vrow / vol_h
            frac_bot_v = 1 - (vrow + 1) / vol_h
            for c in display:
                vn = c["volume"] / v_max
                col = "green" if c["close"] >= c["open"] else "red"
                is_avg_line = vrow == vol_h - 1 and avg_row_frac > 0
                if vn >= frac_top_v:
                    vline.append("█", style=f"dim {col}")
                elif vn >= frac_bot_v:
                    vline.append("▄", style=f"dim {col}")
                elif is_avg_line and avg_row_frac >= frac_bot_v:
                    vline.append("╴", style="dim white")
                else:
                    vline.append(" ", style="")
            if pred:
                vline.append(" ")
                for _ in pred:
                    vline.append(" ", style="")
            vline.append(Text(f"{'Vol':>{axis_w - 1}}", style=DIM))
            result.append(vline)
            result.append("\n")

    taxis = Text()

    label_interval = max(5, n_candles // max(candle_w // 12, 1))
    label_map: dict[int, tuple[str, str]] = {}
    for ci in range(0, n_candles, label_interval):
        ts = display[ci].get("time", "")
        label = ts[11:16] if len(ts) > 11 else ts[-5:]
        for j, ch in enumerate(label[:5]):
            col = ci + j
            if col < n_candles:
                label_map[col] = (ch, DIM)
    for ci in range(n_candles):
        if ci in label_map:
            ch, st = label_map[ci]
            taxis.append(ch, style=st)
        else:
            taxis.append(" ", style="")

    if pred:
        taxis.append(" ", style="")
        p_label_interval = max(5, n_pred // 4)
        p_label_map: dict[int, tuple[str, str]] = {}
        for pi in range(0, n_pred, p_label_interval):
            if pred_timestamps and pi < len(pred_timestamps):
                pt = pred_timestamps[pi]
                label = pt[11:16] if len(pt) > 11 else pt[-5:]
                st = CYN if pi == 0 else DIM
                for j, ch in enumerate(label[:5]):
                    col = pi + j
                    if col < n_pred:
                        p_label_map[col] = (ch, st)
        for pi in range(n_pred):
            if pi in p_label_map:
                ch, st = p_label_map[pi]
                taxis.append(ch, style=st)
            else:
                taxis.append(" ", style="")

    if show_levels and levels:
        taxis.append(" ")
        for k, v in sorted(levels.items(), key=lambda x: abs(x[1] - last_px)):
            if k == "NOW":
                continue
            pfx = {
                "R3": "R",
                "R2": "R",
                "R1": "R",
                "S1": "S",
                "S2": "S",
                "S3": "S",
                "VWAP": "V",
                "POC": "P",
                "PDH": "H",
                "PDL": "L",
                "PP": "pP",
            }.get(k, "?")
            lc = {
                "R3": ORG,
                "R2": ORG,
                "R1": ORG,
                "S1": CYN,
                "S2": CYN,
                "S3": CYN,
                "VWAP": YLW,
                "POC": YLW,
                "PDH": ORG,
                "PDL": CYN,
                "PP": YLW,
            }.get(k, DIM)
            taxis.append(f"[{lc}]{pfx}[/]")

    taxis.append(Text(f" {'Time':>{axis_w - 1}}", style=DIM))
    result.append(taxis)
    result.append("\n")

    return result
