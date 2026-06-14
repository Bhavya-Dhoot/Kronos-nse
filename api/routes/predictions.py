"""Prediction HTTP endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, Query

from api.conviction import ConvictionState, ConvictionTracker
from api.dependencies import (
    get_context_builder,
    get_conviction_tracker,
    get_db,
    get_dqg,
    get_engine,
)
from api.helpers import dqg_mode, engine_result_to_prediction, resolve_universe
from api.schemas import (
    BatchPredictionResponse,
    CandleBar,
    CandleHistoryResponse,
    PredictionResponse,
    SkippedSymbol,
)
from data.quality.gate import DataQualityGate, DQGFailureError, DQGReport, DQGStatus
from model.context_builder import ContextBuilder
from model.engine import KronosEngine
from model.predictor import PredictionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get(
    "/batch/{universe}",
    response_model=BatchPredictionResponse,
    summary="Batch predict for a universe",
)
async def get_batch_predictions(
    universe: str,
    timeframe: str = Query("5min"),
    mode: str = Query("STANDARD"),
    pred_len: int = Query(20),
    sample_count: int = Query(2),
    dqg: Annotated[DataQualityGate, Depends(get_dqg)] = ...,
    context_builder: Annotated[ContextBuilder, Depends(get_context_builder)] = ...,
    engine: Annotated[KronosEngine, Depends(get_engine)] = ...,
) -> BatchPredictionResponse:
    """Run DQG for all symbols, predict passing ones, skip failures."""
    symbols = resolve_universe(universe)
    dqg_m = dqg_mode(mode)
    reports = await dqg.run_batch(symbols, timeframe, dqg_m)

    predictions: list[PredictionResponse] = []
    skipped: list[SkippedSymbol] = []

    for symbol in symbols:
        report = reports.get(symbol)
        if report is None or report.status != DQGStatus.PASS:
            skipped.append(
                SkippedSymbol(symbol=symbol, reason=f"DQG_{report.status.value}")
            )
            continue
        try:
            ctx = await context_builder.build(symbol, timeframe, mode)
            last_close = (
                float(ctx["df"]["close"].iloc[-1]) if not ctx["df"].empty else None
            )
            raw = await engine.predict(
                symbol=symbol,
                df=ctx["df"],
                x_ts=ctx["x_ts"],
                y_ts=ctx["y_ts"][:pred_len]
                if len(ctx["y_ts"]) >= pred_len
                else ctx["y_ts"],
                pred_len=pred_len,
                sample_count=sample_count,
                timeframe=timeframe,
                mode=dqg_m,
                skip_dqg=True,
            )
            raw["mode"] = mode
            predictions.append(
                engine_result_to_prediction(
                    raw,
                    dqg_status=report.status.value,
                    data_coverage=float(report.coverage_pct or 0.0),
                    last_close=last_close,
                )
            )
        except PredictionError as exc:
            skipped.append(SkippedSymbol(symbol=symbol, reason=str(exc)))

    return BatchPredictionResponse(predictions=predictions, skipped=skipped)


@router.get(
    "/history/{symbol}",
    response_model=CandleHistoryResponse,
    summary="Historical OHLCV candles for charting",
)
async def get_candle_history(
    symbol: str,
    timeframe: str = Query("5min"),
    limit: int = Query(500, ge=10, le=5000),
    db: Annotated[Any, Depends(get_db)] = ...,
) -> CandleHistoryResponse:
    """Return historical candles from TimescaleDB for the dashboard chart."""
    df = await db.get_candles(symbol, timeframe, limit=limit)
    candles: list[CandleBar] = []
    candle_data_age_seconds: float | None = None
    if not df.empty:
        now = datetime.now(UTC)
        last_ts = df.index[-1]
        if last_ts.tz is None:
            last_ts = last_ts.tz_localize("Asia/Kolkata")
        candle_data_age_seconds = abs((now - last_ts).total_seconds())
        for ts, row in df.iterrows():
            candles.append(
                CandleBar(
                    time=ts.isoformat(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return CandleHistoryResponse(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        candle_data_age_seconds=candle_data_age_seconds,
    )


@router.get(
    "/{symbol}", response_model=PredictionResponse, summary="Predict for one symbol"
)
async def get_prediction(
    symbol: str,
    timeframe: str = Query("5min"),
    mode: str = Query("STANDARD"),
    pred_len: int = Query(20),
    sample_count: int = Query(2),
    force_refresh: bool = Query(False),
    conviction_mode: bool = Query(True),
    dqg: Annotated[DataQualityGate, Depends(get_dqg)] = ...,
    context_builder: Annotated[ContextBuilder, Depends(get_context_builder)] = ...,
    engine: Annotated[KronosEngine, Depends(get_engine)] = ...,
    tracker: Annotated[ConvictionTracker, Depends(get_conviction_tracker)] = ...,
) -> PredictionResponse:
    """Return a prediction with optional conviction-based stickiness.

    When ``conviction_mode`` is active (default) the endpoint checks the
    :class:`ConvictionTracker` before recomputing.  If the active prediction
    is cached, it is returned immediately — skipping DQG, context building,
    and model inference.

    Conviction state is included in the response for the TUI to render.
    """
    dqg_m = dqg_mode(mode)

    # ── Conviction cache ─────────────────────────────────────────────────
    if conviction_mode and not force_refresh:
        entry = tracker.get_active(symbol, timeframe)
        if entry is not None:
            raw = dict(entry["result"])
            raw["cached"] = True
            raw["conviction_state"] = ConvictionState.CONFIRMED.value
            return engine_result_to_prediction(raw, data_age_seconds=None, atr_pct=None)

    # ── DQG ─────────────────────────────────────────────────────────────
    cached_dqg = await dqg._redis.get_dqg_report(symbol, timeframe)
    if cached_dqg and cached_dqg.get("status") == "PASS":
        report = DQGReport(
            symbol=symbol,
            timeframe=timeframe,
            mode=dqg_m,
            status=DQGStatus.PASS,
            created_at=datetime.now(UTC),
            last_candle_time=cached_dqg.get("last_candle_time"),
            coverage_pct=float(cached_dqg.get("coverage_pct", 0) or 0),
            days_collected=int(cached_dqg.get("days_collected", 0)),
            checks=cached_dqg.get("checks", {}),
        )
    else:
        report = await dqg.run(symbol, timeframe, dqg_m)
        if report.status != DQGStatus.PASS:
            raise DQGFailureError(report)

    # ── Context ─────────────────────────────────────────────────────────
    ctx = await context_builder.build(symbol, timeframe, mode)
    df_ctx = ctx.get("df")
    last_close = (
        float(df_ctx["close"].iloc[-1])
        if df_ctx is not None and not df_ctx.empty
        else None
    )
    temperature = ctx.get("temperature_override")

    atr_pct = None
    if df_ctx is not None and not df_ctx.empty and len(df_ctx) > 15:
        try:
            high = df_ctx["high"].astype(float)
            low = df_ctx["low"].astype(float)
            close = df_ctx["close"].astype(float)
            prev_close = close.shift(1)
            tr = pd.concat(
                [
                    (high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_pct = (
                float(atr / close.iloc[-1] * 100)
                if pd.notna(atr) and close.iloc[-1] > 0
                else None
            )
        except Exception:
            logger.debug("Failed to compute ATR%%", exc_info=True)

    now = datetime.now(UTC)
    data_age_seconds = None
    if df_ctx is not None and not df_ctx.empty:
        try:
            last_ts = df_ctx.index[-1]
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize("Asia/Kolkata")
            data_age_seconds = abs((now - last_ts).total_seconds())
        except Exception:
            logger.debug("Failed to compute data_age for prediction", exc_info=True)

    # ── VIX from engine ─────────────────────────────────────────────────
    vix_level = engine.get_vix_level()

    # ── Engine ──────────────────────────────────────────────────────────
    raw = await engine.predict(
        symbol=symbol,
        df=ctx["df"],
        x_ts=ctx["x_ts"],
        y_ts=ctx["y_ts"][:pred_len] if len(ctx["y_ts"]) >= pred_len else ctx["y_ts"],
        pred_len=pred_len,
        sample_count=sample_count,
        force=force_refresh,
        temperature=temperature,
        timeframe=timeframe,
        mode=dqg_m,
        skip_dqg=True,
        vix_level=vix_level,
    )
    raw["mode"] = mode
    raw["conviction_state"] = ConvictionState.CONFIRMED.value

    # ── Store in conviction tracker ─────────────────────────────────────
    if conviction_mode:
        tracker.set_active(symbol, timeframe, raw)

    return engine_result_to_prediction(
        raw,
        dqg_status=report.status.value,
        data_coverage=float(report.coverage_pct or 0.0),
        last_close=last_close,
        data_age_seconds=data_age_seconds,
        atr_pct=atr_pct,
    )
