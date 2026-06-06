"""PredictionModifier — MVS-driven prediction modification.

Applies 5 layers of modification to Kronos predictions using MVS-derived
properties from MarketVarianceEngine. Pre-inference: temperature scaling.
Post-inference: directional bias + band scaling + OHLCV constraints +
confidence override.

Per D-18: Modification order is bias → bands → constraints → confidence.

Dependencies
------------
- MarketVarianceEngine (type-checking only): reads ``last_mvs`` dict
  containing temperature_adjustment, directional_bias,
  band_width_multiplier, confidence_override.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from variance.engine import MarketVarianceEngine

logger = logging.getLogger(__name__)


class PredictionModifier:
    """Applies MVS-driven modifications to Kronos predictions.

    Holds an optional reference to MarketVarianceEngine for reading the
    current Market Variance Score (MVS). If MVE is None or not ready,
    all modification methods become no-ops per D-04 / T-07-02.

    Parameters
    ----------
    mve : MarketVarianceEngine | None
        MVE instance with ``is_ready`` and ``last_mvs`` properties.
        Defaults to None (all modifications disabled).
    """

    def __init__(
        self, mve: MarketVarianceEngine | None = None
    ) -> None:
        self._mve = mve

    # ── pre-inference ────────────────────────────────────────────────────

    def modify_pre_inference(self, temperature: float) -> float:
        """Adjust model temperature based on MVS VIX adjustment.

        Combines the regime-influenced temperature with the MVE-derived
        VIX adjustment per D-05 through D-09.

        Formula per D-05::

            effective = max(temperature, 0.7 + temperature_adjustment)

        where *temperature* is already the regime-influenced value from
        ContextBuilder (TRENDING=0.6, RANGING=0.7, VOLATILE=0.85, or
        model default 0.7 if no override).

        Parameters
        ----------
        temperature : float
            Regime-influenced temperature from ContextBuilder.

        Returns
        -------
        float
            Effective temperature — raised if VIX adjustment exceeds
            the regime temperature, otherwise unchanged.
        """
        # No-op when MVE not available or not yet ready (T-07-02)
        if not self._mve or not self._mve.is_ready:
            return temperature

        mvs_dict = self._mve.last_mvs
        if mvs_dict is None:
            return temperature

        temp_adj = mvs_dict.get("temperature_adjustment", 0.0)
        effective = max(temperature, 0.7 + temp_adj)

        if effective != temperature:
            logger.debug(
                "PredictionModifier: temp %.2f -> %.2f (VIX adj=%.3f)",
                temperature,
                effective,
                temp_adj,
            )

        return effective

    # ── post-inference ───────────────────────────────────────────────────

    def modify_post_inference(self, prediction: dict) -> dict:
        """Apply all post-inference modifications to a prediction dict.

        Modification order per D-18::

            1. Directional bias on pred_close (D-10 through D-14)
            2. Band scaling on pred_high / pred_low (D-15 through D-16)
            3. OHLCV constraints (D-17)
            4. Confidence override flag (D-19 through D-21)

        Parameters
        ----------
        prediction : dict
            Raw prediction dict with at least ``pred_close`` and
            optionally ``pred_high``, ``pred_low``, ``pred_open``,
            ``pred_volume`` keys.

        Returns
        -------
        dict
            Modified prediction dict (mutated in place and returned).
        """
        # No-op when MVE not available or not yet ready (T-07-02)
        if not self._mve or not self._mve.is_ready:
            return prediction

        mvs_dict = self._mve.last_mvs
        if mvs_dict is None:
            return prediction

        # ── Layer 1: Directional Bias (D-10 through D-14) ─────────────────
        bias = mvs_dict.get("directional_bias", 0.0)
        pred_close: list[float] | None = prediction.get("pred_close")

        if pred_close is not None and len(pred_close) > 0 and bias != 0.0:
            N = len(pred_close)
            denom = max(N - 1, 1)
            min_shift = float("inf")
            max_shift = float("-inf")

            for i in range(N):
                bias_scale = 1.0 - 0.5 * (i / denom)  # D-12 decay
                shift_pct = bias * bias_scale * 0.01  # D-11 shift
                pred_close[i] = round(pred_close[i] * (1.0 + shift_pct), 4)
                min_shift = min(min_shift, shift_pct)
                max_shift = max(max_shift, shift_pct)

            logger.debug(
                "Bias: composite=%.3f, shift range [%.4f, %.4f]",
                bias,
                min_shift,
                max_shift,
            )

        # ── Layer 2: Band Scaling (D-15 through D-16) ─────────────────────
        band_mult = mvs_dict.get("band_width_multiplier", 1.0)
        pred_high: list[float] | None = prediction.get("pred_high")
        pred_low: list[float] | None = prediction.get("pred_low")

        if band_mult != 1.0 and pred_high is not None and pred_low is not None:
            N = min(len(pred_high), len(pred_low))
            for i in range(N):
                mid = (pred_high[i] + pred_low[i]) / 2.0  # D-15 midpoint
                new_high = mid + (pred_high[i] - mid) * band_mult
                new_low = mid - (mid - pred_low[i]) * band_mult
                pred_high[i] = round(new_high, 4)
                pred_low[i] = round(max(new_low, 0.0), 4)

        # ── Layer 3: OHLCV Constraints (D-17) ─────────────────────────────
        pred_open: list[float] | None = prediction.get("pred_open")
        pred_volume: list[float] | None = prediction.get("pred_volume")
        n_bars_clipped = 0

        # Determine max bar count across all OHLCV lists present
        bar_count = 0
        if pred_open is not None:
            bar_count = max(bar_count, len(pred_open))
        if pred_high is not None:
            bar_count = max(bar_count, len(pred_high))
        if pred_low is not None:
            bar_count = max(bar_count, len(pred_low))
        if pred_close is not None:
            bar_count = max(bar_count, len(pred_close))

        if bar_count > 0 and all(
            lst is not None
            for lst in [pred_open, pred_high, pred_low, pred_close]
        ):
            N = min(
                len(pred_open), len(pred_high), len(pred_low), len(pred_close)
            )
            for i in range(N):
                hi = pred_high[i]
                lo = pred_low[i]
                op = pred_open[i]
                cl = pred_close[i]

                # Track originals for clip detection
                orig_hi = hi
                orig_lo = lo

                # Clamp: high is highest, low is lowest
                hi = max(hi, op, cl)
                lo = min(lo, op, cl)

                # Safety: ensure high >= low
                if hi < lo:
                    hi = lo

                if hi != orig_hi or lo != orig_lo:
                    n_bars_clipped += 1

                pred_high[i] = round(hi, 4)
                pred_low[i] = round(lo, 4)

        # Volume non-negative
        if pred_volume is not None:
            for i in range(len(pred_volume)):
                if pred_volume[i] < 0.0:
                    pred_volume[i] = 0.0
                    n_bars_clipped += 1

        if n_bars_clipped > 0:
            logger.debug(
                "OHLCV constraints clipped %d bars", n_bars_clipped
            )

        # ── Layer 4: Confidence Override (D-19 through D-21) ──────────────
        conf_override = mvs_dict.get("confidence_override")
        if conf_override is not None:
            prediction["mve_confidence"] = conf_override
        else:
            # Clean state — ensure key is absent when no override
            prediction.pop("mve_confidence", None)

        return prediction
