"""Options signal generator — maps Kronos index predictions to option positions.

Takes predicted index candles (NIFTY50 / BANKNIFTY) and produces actionable
option position recommendations: direction, strike selection, expiry preference,
and confidence scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Direction(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class OptionType(StrEnum):
    CE = "CE"  # Call
    PE = "PE"  # Put
    STRADDLE = "STRADDLE"
    STRANGLE = "STRANGLE"
    IRON_CONDOR = "IRON_CONDOR"
    NONE = "NONE"


class ExpiryPreference(StrEnum):
    CURRENT_WEEK = "CURRENT_WEEK"
    NEXT_WEEK = "NEXT_WEEK"
    MONTHLY = "MONTHLY"


@dataclass
class OptionSignal:
    """A single option position recommendation."""

    symbol: str  # e.g. "NIFTY50" or "BANKNIFTY"
    direction: Direction
    option_type: OptionType
    confidence: float  # 0.0 - 1.0
    predicted_move_pct: float  # expected % move
    predicted_move_points: float  # absolute points move
    current_price: float  # current index level
    suggested_strike: int  # ATM/OTM strike price
    expiry_preference: ExpiryPreference
    stop_loss_pct: float  # suggested SL as % of premium
    target_pct: float  # suggested target as % of premium
    reasoning: str  # human-readable explanation
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Strike rounding ──────────────────────────────────────────────────────────

STRIKE_STEP = {
    "NIFTY50": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
}


def _round_strike(
    price: float, symbol: str, direction: Direction, otm_steps: int = 0
) -> int:
    """Round to nearest valid strike, optionally going OTM by N steps."""
    step = STRIKE_STEP.get(symbol, 50)
    atm = round(price / step) * step
    if direction == Direction.BULLISH:
        return int(atm + (otm_steps * step))
    elif direction == Direction.BEARISH:
        return int(atm - (otm_steps * step))
    return int(atm)


# ── Core signal generation ───────────────────────────────────────────────────


class OptionsSignalGenerator:
    """Generate option position signals from Kronos index predictions.

    Usage::

        gen = OptionsSignalGenerator()
        signal = gen.generate(
            symbol="NIFTY50",
            current_price=24500.0,
            predicted_candles=pred_df,     # Kronos output with OHLCV
            lookback_candles=lookback_df,  # recent history for context
        )
    """

    # Thresholds for directional conviction
    MIN_MOVE_PCT_FOR_DIRECTIONAL = 0.15  # < 0.15% = neutral
    STRONG_MOVE_PCT = 0.50  # > 0.50% = high confidence
    HIGH_CONFIDENCE_THRESHOLD = 0.65
    MIN_TRADEABLE_CONFIDENCE = 0.40

    # Volatility regime thresholds (annualised)
    LOW_VOL_THRESHOLD = 10.0
    HIGH_VOL_THRESHOLD = 20.0

    def __init__(
        self,
        *,
        otm_steps_default: int = 1,
        max_otm_steps: int = 4,
    ):
        self.otm_steps_default = otm_steps_default
        self.max_otm_steps = max_otm_steps

    def generate(
        self,
        symbol: str,
        current_price: float,
        predicted_candles: pd.DataFrame,
        lookback_candles: pd.DataFrame | None = None,
        sample_predictions: list[pd.DataFrame] | None = None,
    ) -> OptionSignal:
        """Generate an option signal from Kronos predictions.

        Args:
            symbol: Index symbol (NIFTY50, BANKNIFTY)
            current_price: Current index spot level
            predicted_candles: Kronos mean/median predicted OHLCV candles
            lookback_candles: Recent historical candles for vol context
            sample_predictions: Multiple Kronos sample runs for confidence estimation
        """
        pred_close = predicted_candles["close"].values.astype(float)

        # ── Direction & magnitude ─────────────────────────────────────────
        terminal_price = float(pred_close[-1])
        move_points = terminal_price - current_price
        move_pct = (move_points / current_price) * 100.0

        if abs(move_pct) < self.MIN_MOVE_PCT_FOR_DIRECTIONAL:
            direction = Direction.NEUTRAL
        elif move_pct > 0:
            direction = Direction.BULLISH
        else:
            direction = Direction.BEARISH

        # ── Confidence scoring ────────────────────────────────────────────
        confidence = self._compute_confidence(
            pred_close=pred_close,
            move_pct=move_pct,
            current_price=current_price,
            sample_predictions=sample_predictions,
        )

        # ── Volatility regime ─────────────────────────────────────────────
        vol_regime = self._estimate_vol_regime(lookback_candles, symbol)

        # ── Option type selection ─────────────────────────────────────────
        option_type, reasoning = self._select_option_type(
            direction=direction,
            confidence=confidence,
            move_pct=move_pct,
            vol_regime=vol_regime,
        )

        # ── Strike selection ──────────────────────────────────────────────
        otm_steps = self._select_otm_steps(confidence, abs(move_pct), vol_regime)
        strike = _round_strike(current_price, symbol, direction, otm_steps)

        # ── Expiry preference ─────────────────────────────────────────────
        pred_horizon_bars = len(pred_close)
        expiry = self._select_expiry(pred_horizon_bars, confidence)

        # ── Risk management ───────────────────────────────────────────────
        stop_loss_pct, target_pct = self._compute_risk_targets(
            confidence=confidence,
            move_pct=abs(move_pct),
            vol_regime=vol_regime,
        )

        return OptionSignal(
            symbol=symbol,
            direction=direction,
            option_type=option_type,
            confidence=round(confidence, 3),
            predicted_move_pct=round(move_pct, 4),
            predicted_move_points=round(move_points, 2),
            current_price=current_price,
            suggested_strike=strike,
            expiry_preference=expiry,
            stop_loss_pct=round(stop_loss_pct, 1),
            target_pct=round(target_pct, 1),
            reasoning=reasoning,
            metadata={
                "vol_regime": vol_regime,
                "otm_steps": otm_steps,
                "pred_horizon_bars": pred_horizon_bars,
                "terminal_price": terminal_price,
            },
        )

    def _compute_confidence(
        self,
        pred_close: np.ndarray,
        move_pct: float,
        current_price: float,
        sample_predictions: list[pd.DataFrame] | None,
    ) -> float:
        """Multi-factor confidence score [0, 1]."""
        scores: list[float] = []

        # Factor 1: Magnitude — stronger moves = higher conviction if consistent
        mag_score = min(abs(move_pct) / self.STRONG_MOVE_PCT, 1.0)
        scores.append(mag_score * 0.3)

        # Factor 2: Monotonicity — is the predicted trajectory consistent?
        if len(pred_close) > 2:
            diffs = np.diff(pred_close)
            if move_pct > 0:
                monotonic_pct = np.mean(diffs > 0)
            elif move_pct < 0:
                monotonic_pct = np.mean(diffs < 0)
            else:
                monotonic_pct = 0.5
            scores.append(float(monotonic_pct) * 0.25)
        else:
            scores.append(0.1)

        # Factor 3: Sample agreement — if multiple Kronos runs agree on direction
        if sample_predictions and len(sample_predictions) > 1:
            terminal_moves = []
            for sp in sample_predictions:
                sp_close = sp["close"].values.astype(float)
                sp_terminal = float(sp_close[-1])
                terminal_moves.append(sp_terminal - current_price)

            directions_agree = sum(
                1 for m in terminal_moves if (m > 0) == (move_pct > 0)
            ) / len(terminal_moves)
            scores.append(float(directions_agree) * 0.3)

            # Spread: tight spread = high confidence
            spread = np.std(terminal_moves) / max(abs(current_price), 1e-6)
            spread_score = max(0, 1.0 - spread * 100)
            scores.append(spread_score * 0.15)
        else:
            scores.append(0.15)  # no samples = moderate default
            scores.append(0.05)

        return min(sum(scores), 1.0)

    def _estimate_vol_regime(
        self,
        lookback: pd.DataFrame | None,
        symbol: str,
    ) -> str:
        """Estimate current volatility regime from lookback data."""
        if lookback is None or len(lookback) < 20:
            return "medium"

        close = lookback["close"].values.astype(float)
        log_returns = np.diff(np.log(close + 1e-10))
        # Annualize 5-min vol: sqrt(75 bars/day * 252 trading days)
        ann_vol = float(np.std(log_returns) * np.sqrt(75 * 252) * 100)

        if ann_vol < self.LOW_VOL_THRESHOLD:
            return "low"
        elif ann_vol > self.HIGH_VOL_THRESHOLD:
            return "high"
        return "medium"

    def _select_option_type(
        self,
        direction: Direction,
        confidence: float,
        move_pct: float,
        vol_regime: str,
    ) -> tuple[OptionType, str]:
        """Select option strategy based on conviction and vol regime."""
        if confidence < self.MIN_TRADEABLE_CONFIDENCE:
            return OptionType.NONE, (
                f"Confidence {confidence:.0%} below {self.MIN_TRADEABLE_CONFIDENCE:.0%} "
                f"minimum. No trade recommended."
            )

        if direction == Direction.NEUTRAL:
            if vol_regime == "low":
                return OptionType.STRADDLE, (
                    f"Neutral direction ({move_pct:+.2f}%) in low-vol regime. "
                    f"ATM straddle for potential vol expansion."
                )
            elif vol_regime == "high":
                return OptionType.IRON_CONDOR, (
                    f"Neutral direction ({move_pct:+.2f}%) in high-vol regime. "
                    f"Iron condor to sell elevated premiums."
                )
            return OptionType.STRANGLE, (
                f"Neutral direction ({move_pct:+.2f}%) in medium-vol. "
                f"OTM strangle for range-bound collection."
            )

        if direction == Direction.BULLISH:
            return OptionType.CE, (
                f"Bullish: predicted {move_pct:+.2f}% move. "
                f"Confidence {confidence:.0%}, vol regime: {vol_regime}. "
                f"Buy CE (call)."
            )
        else:
            return OptionType.PE, (
                f"Bearish: predicted {move_pct:+.2f}% move. "
                f"Confidence {confidence:.0%}, vol regime: {vol_regime}. "
                f"Buy PE (put)."
            )

    def _select_otm_steps(
        self,
        confidence: float,
        abs_move_pct: float,
        vol_regime: str,
    ) -> int:
        """How far OTM to go: higher confidence + bigger move = more aggressive."""
        if (
            confidence >= self.HIGH_CONFIDENCE_THRESHOLD
            and abs_move_pct > self.STRONG_MOVE_PCT
        ):
            # High confidence + strong move = ATM or 1 step OTM
            return 0 if vol_regime == "high" else 1
        elif confidence >= self.MIN_TRADEABLE_CONFIDENCE:
            # Moderate confidence = 1-2 steps OTM (cheaper premium)
            return min(2, self.otm_steps_default + (1 if vol_regime == "high" else 0))
        return self.otm_steps_default

    def _select_expiry(
        self, pred_horizon_bars: int, confidence: float
    ) -> ExpiryPreference:
        """Match expiry to prediction horizon.

        5-min bars: 75 bars = 1 trading day.
        """
        pred_days = pred_horizon_bars / 75.0

        if pred_days <= 1.5:
            return ExpiryPreference.CURRENT_WEEK
        elif pred_days <= 5:
            return (
                ExpiryPreference.NEXT_WEEK
                if confidence > 0.5
                else ExpiryPreference.CURRENT_WEEK
            )
        return ExpiryPreference.MONTHLY

    def _compute_risk_targets(
        self,
        confidence: float,
        move_pct: float,
        vol_regime: str,
    ) -> tuple[float, float]:
        """Compute stop-loss and target as % of premium paid.

        Returns (stop_loss_pct, target_pct).
        """
        # Base risk/reward scaled by confidence
        if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            sl_pct = 30.0  # tight stop
            target_pct = 60.0 + (move_pct * 20)  # ambitious target
        elif confidence >= self.MIN_TRADEABLE_CONFIDENCE:
            sl_pct = 40.0
            target_pct = 40.0 + (move_pct * 15)
        else:
            sl_pct = 50.0
            target_pct = 30.0

        # Adjust for vol regime
        if vol_regime == "high":
            sl_pct *= 1.3  # wider stops in high vol
            target_pct *= 1.2
        elif vol_regime == "low":
            sl_pct *= 0.8
            target_pct *= 0.8

        return min(sl_pct, 60.0), min(target_pct, 150.0)
