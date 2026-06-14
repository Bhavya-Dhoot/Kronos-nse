"""DQG reporting utilities for API and UI consumption."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from html import escape
from typing import Any

from data.quality.gate import DQGReport, DQGStatus


class DQGReporter:
    """Formats DQG reports for API responses and human inspection."""

    def generate_json_report(self, reports: dict[str, DQGReport]) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "reports": {sym: asdict(rep) for sym, rep in reports.items()},
        }

    def generate_html_report(self, reports: dict[str, DQGReport]) -> str:
        generated_at = datetime.utcnow().isoformat() + "Z"

        def color(status: DQGStatus) -> str:
            if status == DQGStatus.PASS:
                return "#16a34a"  # green
            if status == DQGStatus.PARTIAL:
                return "#f59e0b"  # amber
            return "#dc2626"  # red

        def icon(passed: bool) -> str:
            return "✅" if passed else "❌"

        rows = []
        for sym, rep in sorted(reports.items()):
            cov = "" if rep.coverage_pct is None else f"{rep.coverage_pct:.2f}%"
            rows.append(
                f"<tr>"
                f"<td>{escape(sym)}</td>"
                f"<td style='font-weight:700;color:{color(rep.status)}'>{escape(rep.status.value)}</td>"
                f"<td>{escape(cov)}</td>"
                f"<td>{rep.days_collected}</td>"
                f"<td>{escape(rep.last_candle_time or '')}</td>"
                f"</tr>"
            )

        detail_blocks = []
        for sym, rep in sorted(reports.items()):
            checks_html = []
            for name, result in rep.checks.items():
                passed = bool(result.get("passed"))
                critical = bool(result.get("critical"))
                detail = str(result.get("detail", ""))
                checks_html.append(
                    "<div class='check'>"
                    f"<span class='icon'>{icon(passed)}</span>"
                    f"<span class='name'>{escape(name)}{' (CRITICAL)' if critical else ''}</span>"
                    f"<span class='detail'>{escape(detail)}</span>"
                    "</div>"
                )

            detail_blocks.append(
                f"<section class='symbol'>"
                f"<h2>{escape(sym)} <span class='badge' style='background:{color(rep.status)}'>{escape(rep.status.value)}</span></h2>"
                f"<div class='meta'>timeframe={escape(rep.timeframe)} mode={escape(rep.mode)} last={escape(rep.last_candle_time or '')}</div>"
                f"{''.join(checks_html)}"
                f"</section>"
            )

        return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Kronos NSE — DQG Report</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; font-size: 14px; }}
    th {{ background: #f9fafb; text-align: left; }}
    .muted {{ color: #6b7280; }}
    .symbol {{ border: 1px solid #e5e7eb; padding: 12px; margin-top: 16px; border-radius: 8px; }}
    .badge {{ color: #fff; padding: 2px 8px; border-radius: 999px; font-size: 12px; vertical-align: middle; }}
    .meta {{ font-size: 12px; color: #6b7280; margin-bottom: 8px; }}
    .check {{ display: grid; grid-template-columns: 28px 220px 1fr; gap: 8px; padding: 6px 0; border-top: 1px dashed #e5e7eb; }}
    .check:first-child {{ border-top: none; }}
    .name {{ font-weight: 600; }}
    .detail {{ color: #111827; }}
  </style>
</head>
<body>
  <h1>Kronos NSE — Data Quality Gate Report</h1>
  <div class="muted">Generated at: {escape(generated_at)}</div>

  <h2>Summary</h2>
  <table>
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Status</th>
        <th>Coverage</th>
        <th>Days</th>
        <th>Last candle</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>

  <h2>Details</h2>
  {"".join(detail_blocks)}
</body>
</html>
""".strip()
