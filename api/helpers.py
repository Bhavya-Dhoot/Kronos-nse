"""API helpers: response mapping, confidence scoring, universe resolution."""

from __future__ import annotations

from typing import Any

from data.quality.gate import DQGReport, DQGStatus
from api.schemas import CheckResult, DQGReportResponse, PredictionResponse


def resolve_universe(name: str) -> list[str]:
    """Return symbol list for a named universe."""
    from scripts.seed_instruments import get_universe

    return list(get_universe(name.upper()).keys())


def dqg_mode(mode: str) -> str:
    """Map API prediction modes to DQG-compatible mode names."""
    mode_u = mode.upper()
    if mode_u in {"STANDARD", "MULTI_TF", "MULTI", "REGIME", "REGIME_AWARE"}:
        return "VISUAL"
    return mode_u


def compute_confidence(
    pred_close: list[float],
    last_close: float | None,
    mve_confidence: str | None = None,
) -> str:
    """Classify confidence from expected move magnitude.

    If ``mve_confidence`` is provided (from MVS confidence_override
    per D-20), return it directly instead of computing.  Falls back to
    computed confidence when override is not set.
    """
    if mve_confidence is not None:
        return mve_confidence
    if not pred_close or not last_close:
        return "LOW"
    move_pct = abs(float(pred_close[-1]) - last_close) / last_close * 100
    if move_pct >= 1.0:
        return "HIGH"
    if move_pct >= 0.3:
        return "MEDIUM"
    return "LOW"


def compute_direction(pred_close: list[float], last_close: float | None) -> str:
    """Return BULLISH/BEARISH/NEUTRAL signal direction."""
    if not pred_close or not last_close:
        return "NEUTRAL"
    delta_pct = (float(pred_close[-1]) - last_close) / last_close * 100
    if delta_pct > 0.05:
        return "BULLISH"
    if delta_pct < -0.05:
        return "BEARISH"
    return "NEUTRAL"


def checks_to_schema(checks: dict[str, Any]) -> dict[str, CheckResult]:
    """Convert raw DQG check dicts to CheckResult models."""
    out: dict[str, CheckResult] = {}
    for name, raw in checks.items():
        if not isinstance(raw, dict):
            continue
        out[name] = CheckResult(
            passed=bool(raw.get("passed", False)),
            critical=bool(raw.get("critical", False)),
            detail=str(raw.get("detail") or raw.get("message") or ""),
        )
    return out


def dqg_report_to_response(report: DQGReport) -> DQGReportResponse:
    """Map DQGReport dataclass to API response."""
    return DQGReportResponse(
        symbol=report.symbol,
        timeframe=report.timeframe,
        status=report.status.value if isinstance(report.status, DQGStatus) else str(report.status),
        checks=checks_to_schema(report.checks),
        coverage_pct=float(report.coverage_pct or 0.0),
        days_collected=int(report.days_collected),
        last_candle_time=report.last_candle_time,
        recommendation=report.recommendation,
    )


def dqg_dict_to_response(payload: dict[str, Any]) -> DQGReportResponse:
    """Map cached Redis/DB DQG payload to API response."""
    checks_raw = payload.get("checks") or {}
    if isinstance(checks_raw, dict) and checks_raw and "status" in checks_raw:
        checks_raw = checks_raw.get("checks") or checks_raw
    return DQGReportResponse(
        symbol=str(payload.get("symbol", "")),
        timeframe=str(payload.get("timeframe", "5min")),
        status=str(payload.get("status", "NOT_RUN")),
        checks=checks_to_schema(checks_raw if isinstance(checks_raw, dict) else {}),
        coverage_pct=float(payload.get("coverage_pct") or 0.0),
        days_collected=int(payload.get("days_collected") or 0),
        last_candle_time=payload.get("last_candle_time"),
        recommendation=payload.get("recommendation"),
    )


def engine_result_to_prediction(
    result: dict[str, Any],
    *,
    dqg_status: str = "PASS",
    data_coverage: float = 0.0,
    last_close: float | None = None,
    data_age_seconds: float | None = None,
) -> PredictionResponse:
    """Map KronosEngine result dict to PredictionResponse."""
    pred_close = [float(x) for x in result.get("pred_close", [])]
    if last_close is None and pred_close:
        last_close = pred_close[0]

    return PredictionResponse(
        symbol=result["symbol"],
        timeframe=result.get("timeframe", "5min"),
        mode=result.get("mode", "STANDARD"),
        generated_at=str(result.get("generated_at", "")),
        model_version=str(result.get("model_version") or ""),
        pred_open=[float(x) for x in result.get("pred_open", [])],
        pred_high=[float(x) for x in result.get("pred_high", [])],
        pred_low=[float(x) for x in result.get("pred_low", [])],
        pred_close=pred_close,
        pred_volume=[float(x) for x in result.get("pred_volume", [])],
        timestamps=list(result.get("pred_timestamps") or result.get("timestamps") or []),
        dqg_status=dqg_status,
        data_coverage=data_coverage,
        confidence=compute_confidence(
            pred_close,
            last_close,
            mve_confidence=result.get("mve_confidence"),
        ),
        latency_ms=result.get("latency_ms"),
        cached=result.get("cached", False),
        data_age_seconds=data_age_seconds,
    )



