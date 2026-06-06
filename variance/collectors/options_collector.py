"""OptionsCollector — polls NIFTY options chain every 300s for PCR, Max Pain, ATM IV, OI concentration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from variance.base_collector import BaseVarianceCollector
from variance.collectors._nse import _fetch_option_chain
from variance.schemas import ParseResult


class OptionsCollector(BaseVarianceCollector):
    """Poll NIFTY option chain every 300s for sentiment analysis.

    Computes 4 metrics from the option chain (per D-08):
    - PCR (Put/Call Ratio): total PE OI / total CE OI
    - Max Pain: strike with highest total CE+PE open interest (simplified method per D-09)
    - ATM IV: implied volatility of nearest ATM strike (CE and PE)
    - OI concentration: top 5 strikes by total OI / total OI across all strikes

    Per D-10: Score is PCR-based with max-pain distance adjustment.
    """

    def __init__(self) -> None:
        super().__init__(name="options", poll_interval=300)

    async def fetch(self) -> Any:
        """Fetch NIFTY option chain via shared NseIndiaApi."""
        return await _fetch_option_chain("NIFTY")

    def parse(self, raw: Any) -> ParseResult:
        """Parse option chain data into structured metrics."""
        records = raw.get("records", {}) if isinstance(raw, dict) else {}
        data = records.get("data", [])
        underlying = self._to_float(records.get("underlyingValue"))

        if not data:
            raise ValueError("No option chain data found in NseIndiaApi response")

        total_ce_oi = 0.0
        total_pe_oi = 0.0
        oi_by_strike: dict[float, float] = {}

        for item in data:
            strike = self._to_float(item.get("strikePrice"))
            if strike is None:
                continue

            ce = item.get("CE", {})
            pe = item.get("PE", {})

            ce_oi_val = self._to_float(ce.get("openInterest"), 0.0)
            pe_oi_val = self._to_float(pe.get("openInterest"), 0.0)

            total_ce_oi += ce_oi_val
            total_pe_oi += pe_oi_val
            oi_by_strike[strike] = ce_oi_val + pe_oi_val

        pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0

        max_pain = max(oi_by_strike, key=oi_by_strike.get) if oi_by_strike else None

        atm_iv_ce: float | None = None
        atm_iv_pe: float | None = None
        if underlying is not None and oi_by_strike:
            strikes = sorted(oi_by_strike.keys())
            nearest_strike = min(strikes, key=lambda s: abs(s - underlying))
            for item in data:
                strike = self._to_float(item.get("strikePrice"))
                if strike is not None and abs(strike - nearest_strike) < 0.01:
                    ce = item.get("CE", {})
                    pe = item.get("PE", {})
                    iv_ce = self._to_float(ce.get("impliedVolatility"))
                    iv_pe = self._to_float(pe.get("impliedVolatility"))
                    if iv_ce is not None:
                        atm_iv_ce = round(iv_ce * 100, 2)
                    if iv_pe is not None:
                        atm_iv_pe = round(iv_pe * 100, 2)

        sorted_strikes = sorted(oi_by_strike.items(), key=lambda x: x[1], reverse=True)
        top5_oi = sum(oi for _, oi in sorted_strikes[:5])
        total_oi_all = sum(oi_by_strike.values())
        oi_concentration = top5_oi / total_oi_all if total_oi_all > 0 else 0.0

        spot_vs_max_pain_pct = None
        if underlying is not None and max_pain is not None and max_pain > 0:
            spot_vs_max_pain_pct = round((underlying - max_pain) / max_pain * 100, 2)

        detail: dict[str, Any] = {
            "pcr": round(pcr, 4),
            "max_pain": max_pain,
            "underlying_value": underlying,
            "iv_ce": atm_iv_ce,
            "iv_pe": atm_iv_pe,
            "oi_concentration": round(oi_concentration, 4),
            "spot_vs_max_pain_pct": spot_vs_max_pain_pct,
            "strike_count": len(oi_by_strike),
        }

        return ParseResult(
            raw_value=pcr,
            normalized=0.0,
            direction=1 if pcr > 1.0 else (-1 if pcr < 1.0 else 0),
            magnitude=abs(pcr - 1.0) * 0.5,
            detail=detail,
            source="nse",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Score options sentiment from PCR with max-pain distance adjustment.

        Per D-10:
        Base score from PCR mapped to [-0.6, +0.6].
        Adjusted by max-pain distance (within 0.5% → -0.15, above 2% → +0.15).
        """
        pcr = parsed["raw_value"]
        detail = parsed.get("detail", {})

        if pcr <= 0.5:
            base_score = -0.6
        elif pcr <= 1.0:
            base_score = -0.6 + (pcr - 0.5) * (0.6 / 0.5)
        elif pcr <= 1.5:
            base_score = (pcr - 1.0) * (0.4 / 0.5)
        elif pcr <= 2.0:
            base_score = 0.4 + (pcr - 1.5) * (0.2 / 0.5)
        else:
            base_score = 0.6

        spot_vs_max_pain = detail.get("spot_vs_max_pain_pct")
        if spot_vs_max_pain is not None:
            abs_distance = abs(spot_vs_max_pain)
            if abs_distance <= 0.5:
                base_score -= 0.15
            elif spot_vs_max_pain > 2.0:
                base_score += 0.15

        return max(-1.0, min(1.0, base_score))

    @staticmethod
    def _to_float(value: Any, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
