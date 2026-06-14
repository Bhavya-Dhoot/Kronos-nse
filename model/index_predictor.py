"""Index prediction runner — runs Kronos on index candles and generates option signals.

Usage:
    python -m model.index_predictor --symbol NIFTY50 --mode live
    python -m model.index_predictor --symbol BANKNIFTY --mode backtest --date 2025-05-20
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import torch

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def _load_kronos_pipeline(
    tokenizer_path: str,
    predictor_path: str,
    device: torch.device,
) -> Any:
    """Load the Kronos prediction pipeline (tokenizer + predictor)."""
    from training.kronos_bridge import KronosPredictor, load_predictor, load_tokenizer

    tokenizer = load_tokenizer(tokenizer_path, device)
    predictor = load_predictor(predictor_path, device)
    return KronosPredictor(predictor, tokenizer, device=str(device), max_context=512)


async def fetch_index_candles(
    symbol: str,
    token: int,
    lookback_bars: int,
    timeframe: str = "5min",
) -> pd.DataFrame:
    """Fetch recent index candles from TimescaleDB."""
    from data.collector.context import load_config
    from data.storage.timescale import TimescaleClient

    config = load_config()
    db = TimescaleClient(config["database_url"])
    await db.initialize()
    try:
        df = await db.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            limit=lookback_bars + 100,  # buffer for gaps
        )
        if df is not None and len(df) > 0:
            df = df.sort_index()
            return df.tail(lookback_bars)
        return pd.DataFrame()
    finally:
        await db.close()


def run_index_prediction(
    kronos: Any,
    candles: pd.DataFrame,
    lookback: int = 400,
    pred_len: int = 60,
    temperature: float = 0.8,
    top_p: float = 0.9,
    sample_count: int = 5,
) -> dict[str, Any]:
    """Run Kronos prediction on index candles.

    Returns:
        Dict with:
            - "mean_prediction": pd.DataFrame (average across samples)
            - "sample_predictions": list[pd.DataFrame]
            - "current_price": float
    """
    if len(candles) < lookback:
        raise ValueError(f"Need at least {lookback} candles, got {len(candles)}")

    # Prepare input
    x_df = candles.tail(lookback)[["open", "high", "low", "close", "volume"]].copy()
    if "amount" not in x_df.columns:
        x_df["amount"] = x_df["close"] * x_df["volume"]

    x_ts = candles.tail(lookback).index

    # Generate future timestamps (5-min intervals, skip non-market hours)
    last_ts = x_ts[-1]
    future_ts = pd.date_range(
        start=last_ts + timedelta(minutes=5),
        periods=pred_len,
        freq="5min",
    )

    current_price = float(x_df["close"].iloc[-1])

    # Run multiple samples for confidence estimation
    sample_predictions: list[pd.DataFrame] = []
    for i in range(sample_count):
        try:
            pred_df = kronos.predict(
                x_df,
                x_ts,
                future_ts,
                pred_len=pred_len,
                T=temperature,
                top_p=top_p,
                sample_count=1,
                verbose=False,
            )
            sample_predictions.append(pred_df)
        except Exception as e:
            logger.warning("Sample %d failed: %s", i, e)

    if not sample_predictions:
        raise RuntimeError("All prediction samples failed")

    # Compute mean prediction across samples
    all_close = [sp["close"].values.astype(float) for sp in sample_predictions]
    mean_close = pd.DataFrame(all_close).mean(axis=0).values

    mean_pred = sample_predictions[0].copy()
    mean_pred["close"] = mean_close

    if len(sample_predictions) > 1:
        all_open = [sp["open"].values.astype(float) for sp in sample_predictions]
        all_high = [sp["high"].values.astype(float) for sp in sample_predictions]
        all_low = [sp["low"].values.astype(float) for sp in sample_predictions]
        mean_pred["open"] = pd.DataFrame(all_open).mean(axis=0).values
        mean_pred["high"] = pd.DataFrame(all_high).max(axis=0).values
        mean_pred["low"] = pd.DataFrame(all_low).min(axis=0).values

    return {
        "mean_prediction": mean_pred,
        "sample_predictions": sample_predictions,
        "current_price": current_price,
        "lookback_candles": candles.tail(lookback),
    }


def format_signal_report(signal: Any) -> str:
    """Format an OptionSignal as a readable report."""
    lines = [
        "=" * 60,
        f"  OPTIONS SIGNAL: {signal.symbol}",
        "=" * 60,
        f"  Direction:      {signal.direction.value}",
        f"  Option Type:    {signal.option_type.value}",
        f"  Confidence:     {signal.confidence:.0%}",
        f"  Predicted Move: {signal.predicted_move_pct:+.2f}% ({signal.predicted_move_points:+.1f} pts)",
        f"  Current Price:  {signal.current_price:.2f}",
        f"  Strike:         {signal.suggested_strike}",
        f"  Expiry:         {signal.expiry_preference.value}",
        f"  Stop Loss:      {signal.stop_loss_pct:.0f}% of premium",
        f"  Target:         {signal.target_pct:.0f}% of premium",
        "-" * 60,
        f"  {signal.reasoning}",
        "=" * 60,
    ]
    return "\n".join(lines)


async def run_live_prediction(
    symbol: str,
    token: int,
    tokenizer_path: str,
    predictor_path: str,
    device: torch.device,
    lookback: int = 400,
    pred_len: int = 60,
    sample_count: int = 5,
) -> dict[str, Any]:
    """End-to-end: fetch latest data → predict → generate signal."""
    from model.options_signal import OptionsSignalGenerator

    # 1. Fetch candles
    logger.info("Fetching %d candles for %s (token=%d)...", lookback, symbol, token)
    candles = await fetch_index_candles(symbol, token, lookback)
    if candles.empty or len(candles) < lookback:
        raise RuntimeError(
            f"Insufficient data for {symbol}: need {lookback} bars, got {len(candles)}"
        )
    logger.info("Got %d candles, latest: %s", len(candles), candles.index[-1])

    # 2. Load model
    logger.info("Loading Kronos pipeline...")
    kronos = _load_kronos_pipeline(tokenizer_path, predictor_path, device)

    # 3. Predict
    logger.info(
        "Running prediction (samples=%d, pred_len=%d)...", sample_count, pred_len
    )
    result = run_index_prediction(
        kronos=kronos,
        candles=candles,
        lookback=lookback,
        pred_len=pred_len,
        sample_count=sample_count,
    )

    # 4. Generate signal
    generator = OptionsSignalGenerator()
    signal = generator.generate(
        symbol=symbol,
        current_price=result["current_price"],
        predicted_candles=result["mean_prediction"],
        lookback_candles=result["lookback_candles"],
        sample_predictions=result["sample_predictions"],
    )

    # 5. Report
    report = format_signal_report(signal)
    logger.info("Signal report:\n%s", report)

    return {
        "signal": signal,
        "prediction": result,
        "report": report,
    }


def main() -> None:
    from scripts.seed_instruments import INDICES_ONLY_TOKENS

    parser = argparse.ArgumentParser(
        description="Kronos Index Prediction → Options Signal"
    )
    parser.add_argument(
        "--symbol", default="NIFTY50", choices=list(INDICES_ONLY_TOKENS.keys())
    )
    parser.add_argument("--tokenizer", default="./checkpoints/production/tokenizer")
    parser.add_argument("--predictor", default="./checkpoints/production/predictor")
    parser.add_argument("--lookback", type=int, default=400)
    parser.add_argument("--pred-len", type=int, default=60)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    token = INDICES_ONLY_TOKENS[args.symbol]

    asyncio.run(
        run_live_prediction(
            symbol=args.symbol,
            token=token,
            tokenizer_path=args.tokenizer,
            predictor_path=args.predictor,
            device=device,
            lookback=args.lookback,
            pred_len=args.pred_len,
            sample_count=args.samples,
        )
    )


if __name__ == "__main__":
    main()
