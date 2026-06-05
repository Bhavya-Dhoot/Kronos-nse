#!/usr/bin/env python3
"""MVE Backtest: compare prediction accuracy with/without MVE modifications.

Per D-18: Single backtest run — get predictions once, then compare modified
vs unmodified by applying modify_post_inference() on the result.

Usage:
    python scripts/backtest_mve.py [--config config/base.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.runner import BacktestRunner
from model.factory import build_inference_context, close_inference_context
from variance.modifier import PredictionModifier

logger = logging.getLogger(__name__)


def compute_mae(actual: list[float], predicted: list[float]) -> float | None:
    """Compute Mean Absolute Error between actual and predicted values."""
    if not actual or not predicted:
        return None
    return float(np.mean(np.abs(np.array(predicted) - np.array(actual))))


def compute_directional_accuracy(
    actual: list[float], predicted: list[float]
) -> float | None:
    """Compute directional accuracy (fraction of bars where direction matches)."""
    if len(actual) < 2 or len(predicted) < 2:
        return None
    n = min(len(actual), len(predicted))
    correct = 0
    total = 0
    for i in range(n - 1):
        pred_delta = predicted[i + 1] - predicted[i]
        actual_delta = actual[i + 1] - actual[i]
        if pred_delta == 0 and actual_delta == 0:
            correct += 1
        elif pred_delta == 0 or actual_delta == 0:
            correct += 0
        elif (pred_delta > 0) == (actual_delta > 0):
            correct += 1
        total += 1
    return correct / total if total else None


async def run_backtest(
    config_path: str,
    output_dir: str,
    max_symbols: int = 5,
) -> dict[str, Any]:
    """Run MVE backtest: predict once, compare modified vs unmodified.

    Per D-18: Single backtest run — get predictions once, then apply
    modify_post_inference() on the result for comparison.

    Parameters
    ----------
    config_path : str
        Path to the base YAML config file.
    output_dir : str
        Directory to write the JSON result file.
    max_symbols : int
        Maximum symbols to test (default 5).

    Returns
    -------
    dict[str, Any]
        Summary of per-state metrics and per-symbol detail.
    """
    # Load config
    with open(config_path) as f:
        raw_cfg = yaml.safe_load(f)

    bt_cfg = raw_cfg.get("backtest", {})
    start = bt_cfg.get("start_date", "2024-01-01")
    end = bt_cfg.get("end_date", "2024-06-01")
    timeframe = bt_cfg.get("timeframe", "5min")
    universe = bt_cfg.get(
        "universe", raw_cfg.get("collector", {}).get("universe", "NIFTY50")
    )

    # Build inference context (loads model, TimescaleDB, etc.)
    ctx = await build_inference_context()

    # Create PredictionModifier WITHOUT MVE — we'll control MVS injection manually
    # per D-18: single prediction pass, then compare by applying modifier
    modifier = PredictionModifier(mve=None)

    # Use a simple MVS dict for modification. This represents a moderate
    # bearish market state (~-0.3 composite, VIX=20)
    default_mvs = {
        "composite": -0.30,
        "market_state": "fear",
        "vix_value": 20.0,
        "temperature_adjustment": 0.075,  # (20-15)*0.015
        "directional_bias": -0.30,
        "band_width_multiplier": 1.04,  # 1.0 + (20-15)*0.008
        "signal_threshold": 0.006,  # 0.005 + (20-15)*0.0002
        "confidence_override": "LOW",
        "created_at": datetime.utcnow().isoformat(),
        "dimensions": [],
    }

    symbols = list(get_universe(universe).keys())[:max_symbols]

    results: dict[str, Any] = {
        "config": {
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "universe": universe,
        },
        "symbols": {},
        "summary": {},
    }

    all_unmodified: dict[str, list[float]] = {
        "mae": [],
        "dacc": [],
        "confidence": [],
    }
    all_modified: dict[str, list[float]] = {
        "mae": [],
        "dacc": [],
        "confidence": [],
    }

    for symbol in symbols:
        logger.info("Processing %s ...", symbol)

        # Fetch candles
        df = await ctx.db.get_candles(
            symbol,
            timeframe,
            limit=5000,
            start_date=datetime.fromisoformat(str(start)),
            end_date=datetime.fromisoformat(str(end)),
        )
        if df.empty or len(df) < 50:
            logger.warning("Skipping %s — insufficient data", symbol)
            continue

        # Build context and predict
        try:
            context = await ctx.context_builder.build(symbol, timeframe, "BACKTEST")
            result = await ctx.engine.predict(
                symbol=symbol,
                df=context["df"],
                x_ts=context["x_ts"],
                y_ts=context["y_ts"],
                timeframe=timeframe,
                mode="BACKTEST",
                skip_dqg=True,
            )
        except Exception:
            logger.exception("Predict failed for %s", symbol)
            continue

        # Actual close values (for computing accuracy)
        pred_close = result.get("pred_close", [])
        actual_close = df["close"].astype(float).tolist()[-len(pred_close) :]

        if not pred_close or not actual_close:
            continue

        # ── State 1: Unmodified (raw prediction) ───────────────────────────
        unmodified_result = dict(result)  # shallow copy

        # ── State 2: Modified with MVE ─────────────────────────────────────
        modified_result = dict(result)  # shallow copy
        # Inject a mock MVS into the modifier to simulate MVE being active
        mock_mve = _MockMVE(default_mvs)
        modifier_with_mve = PredictionModifier(mve=mock_mve)
        modified_result = modifier_with_mve.modify_post_inference(modified_result)

        # Compute metrics for both states
        unmodified_mae = compute_mae(
            actual_close, unmodified_result.get("pred_close", [])
        )
        modified_mae = compute_mae(
            actual_close, modified_result.get("pred_close", [])
        )

        unmodified_dacc = compute_directional_accuracy(
            actual_close, unmodified_result.get("pred_close", [])
        )
        modified_dacc = compute_directional_accuracy(
            actual_close, modified_result.get("pred_close", [])
        )

        unmodified_conf = _parse_confidence(
            unmodified_result.get("confidence", "MEDIUM")
        )
        modified_conf = _parse_confidence(
            modified_result.get(
                "mve_confidence", modified_result.get("confidence", "MEDIUM")
            )
        )

        symbol_result = {
            "unmodified": {
                "mae": unmodified_mae,
                "directional_accuracy": unmodified_dacc,
                "confidence_avg": unmodified_conf,
            },
            "modified": {
                "mae": modified_mae,
                "directional_accuracy": modified_dacc,
                "confidence_avg": modified_conf,
            },
            "difference": {
                "mae": (
                    (modified_mae - unmodified_mae)
                    if modified_mae is not None and unmodified_mae is not None
                    else None
                ),
                "directional_accuracy": (
                    (modified_dacc - unmodified_dacc)
                    if modified_dacc is not None and unmodified_dacc is not None
                    else None
                ),
            },
            "total_bars": len(pred_close),
        }

        results["symbols"][symbol] = symbol_result

        # Accumulate for global summary
        if unmodified_mae is not None:
            all_unmodified["mae"].append(unmodified_mae)
            all_modified["mae"].append(modified_mae)
        if unmodified_dacc is not None:
            all_unmodified["dacc"].append(unmodified_dacc)
            all_modified["dacc"].append(modified_dacc)
        all_unmodified["confidence"].append(unmodified_conf)
        all_modified["confidence"].append(modified_conf)

    # ── Summary ────────────────────────────────────────────────────────────
    def _avg(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    summary = {
        "unmodified": {
            "mean_mae": _avg(all_unmodified["mae"]),
            "mean_directional_accuracy": _avg(all_unmodified["dacc"]),
            "mean_confidence": _avg(all_unmodified["confidence"]),
        },
        "modified": {
            "mean_mae": _avg(all_modified["mae"]),
            "mean_directional_accuracy": _avg(all_modified["dacc"]),
            "mean_confidence": _avg(all_modified["confidence"]),
        },
        "difference": {
            "mae": (
                (_avg(all_modified["mae"]) - _avg(all_unmodified["mae"]))
                if all_unmodified["mae"] and all_modified["mae"]
                else None
            ),
            "directional_accuracy": (
                (
                    _avg(all_modified["dacc"]) - _avg(all_unmodified["dacc"])
                )
                if all_unmodified["dacc"] and all_modified["dacc"]
                else None
            ),
        },
        "symbols_tested": len(results["symbols"]),
        "total_bars": sum(
            s["total_bars"] for s in results["symbols"].values()
        ),
    }
    results["summary"] = summary

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "mve_backtest_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # ── Console output ─────────────────────────────────────────────────────
    _print_summary(summary)

    # Cleanup
    await close_inference_context(ctx)

    return results


class _MockMVE:
    """Minimal mock MVE for backtest comparison (D-18).

    Provides the same interface as MarketVarianceEngine but with
    a fixed MVS dict for deterministic comparison.
    """

    def __init__(self, mvs_dict: dict[str, Any]) -> None:
        self._mvs_dict = mvs_dict
        self.is_ready = True

    @property
    def last_mvs(self) -> dict[str, Any]:
        return self._mvs_dict


def _parse_confidence(conf: str) -> float:
    """Map confidence string to numeric value for averaging."""
    mapping = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0, "PANIC": -0.5}
    return mapping.get(str(conf).upper(), 0.5)


def _print_summary(summary: dict[str, Any]) -> None:
    """Print a console table of results per D-22."""
    u = summary["unmodified"]
    m = summary["modified"]
    d = summary["difference"]

    print()
    print("=" * 70)
    print("  MVE BACKTEST RESULTS")
    print("=" * 70)
    print(f"  Symbols tested: {summary['symbols_tested']}")
    print(f"  Total bars:     {summary['total_bars']}")
    print()
    print(
        f"  {'Metric':<30} {'Unmodified':<14} {'Modified':<14} {'Diff':<10}"
    )
    print(f"  {'-'*30} {'-'*14} {'-'*14} {'-'*10}")

    def _fmt(val) -> str:
        if val is None:
            return "N/A"
        return f"{val:.6f}"

    print(
        f"  {'MAE (pred_close)':<30} {_fmt(u['mean_mae']):<14} "
        f"{_fmt(m['mean_mae']):<14} {_fmt(d['mae']):<10}"
    )
    print(
        f"  {'Directional Accuracy':<30} {_fmt(u['mean_directional_accuracy']):<14} "
        f"{_fmt(m['mean_directional_accuracy']):<14} "
        f"{_fmt(d['directional_accuracy']):<10}"
    )
    print(
        f"  {'Avg Confidence':<30} {_fmt(u['mean_confidence']):<14} "
        f"{_fmt(m['mean_confidence']):<14}"
    )
    print()

    if d.get("mae") is not None:
        if d["mae"] < 0:
            print(
                f"  ✓ MVE improved MAE by {abs(d['mae']):.6f} "
                "(lower is better)"
            )
        elif d["mae"] > 0:
            print(f"  ⚠ MVE increased MAE by {d['mae']:.6f}")
        else:
            print("  ∼ MVE had no effect on MAE")

    print("=" * 70)
    print(f"  Full results: backtest/output/mve_backtest_results.json")
    print()


def get_universe(name: str) -> dict:
    """Wrapper around scripts.seed_instruments.get_universe."""
    from scripts.seed_instruments import get_universe as _get_universe

    return _get_universe(name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MVE Backtest: compare prediction accuracy with/without MVE"
    )
    parser.add_argument(
        "--config",
        default="config/base.yaml",
        help="Path to base YAML config (default: config/base.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        default="backtest/output",
        help="Output directory for JSON results (default: backtest/output)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=5,
        help="Maximum symbols to test (default: 5)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_backtest(args.config, args.output_dir, args.max_symbols))


if __name__ == "__main__":
    main()
