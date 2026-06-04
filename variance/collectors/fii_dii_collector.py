"""FIIDIICollector — polls FII/DII net flow data every 1800s via NseIndiaApi.

Combined score weights FII 70% and DII 30% to reflect institutional flow sentiment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from variance.base_collector import BaseVarianceCollector
from variance.collectors._nse import _fetch_fii_dii_data
from variance.schemas import ParseResult


class FIIDIICollector(BaseVarianceCollector):
    """Poll FII/DII net flow data every 1800s for institutional sentiment.

    Per D-11: combined = FII * 0.7 + DII * 0.3.
    Score = combined / 4000.0, clamped to [-1.0, 1.0].
    """

    def __init__(self) -> None:
        super().__init__(name="fii_dii", poll_interval=1800)

    async def fetch(self) -> Any:
        """Fetch FII/DII net flow data via shared NseIndiaApi."""
        return await _fetch_fii_dii_data()

    def parse(self, raw: Any) -> ParseResult:
        """Extract FII/DII net flows from response.

        Handles multiple response shapes:
        - Simple dict: {"fii_net": ..., "dii_net": ...}
        - Nested dict: {"fii": {"net": ...}, "dii": {"net": ...}}
        - Fallback: scans for keys containing 'fii' and 'dii' with float values
        """
        if not isinstance(raw, dict):
            raise ValueError(
                f"Expected dict for FII/DII data, got {type(raw).__name__}"
            )

        fii_net = self._extract_net(raw, "fii")
        dii_net = self._extract_net(raw, "dii")

        if fii_net is None or dii_net is None:
            raise ValueError(
                "Could not extract FII and DII net values from response"
            )

        combined_net = fii_net * 0.7 + dii_net * 0.3
        direction = 1 if combined_net > 0 else (-1 if combined_net < 0 else 0)
        magnitude = min(1.0, abs(combined_net) / 4000.0)

        return ParseResult(
            raw_value=combined_net,
            normalized=0.0,
            direction=direction,
            magnitude=magnitude,
            detail={
                "fii_net": fii_net,
                "dii_net": dii_net,
                "combined_net": round(combined_net, 2),
            },
            source="nse",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Score combined FII/DII flow: combined / 4000.0, clamped to [-1.0, 1.0].

        Per D-11: positive combined flow = positive sentiment (bullish),
        negative combined flow = negative sentiment (bearish).
        """
        combined = parsed["raw_value"]
        raw_score = combined / 4000.0
        return max(-1.0, min(1.0, raw_score))

    def _extract_net(self, data: dict[str, Any], prefix: str) -> float | None:
        """Try to extract net value for given prefix ('fii' or 'dii').

        Resolution order:
        1. Exact key: {prefix}_net -> direct value
        2. Nested object: {prefix} -> {"net": ...} dict
        3. Fallback key scan for keys containing the prefix
        """
        # 1. Exact key
        exact_key = f"{prefix}_net"
        if exact_key in data:
            val = self._to_float(data[exact_key])
            if val is not None:
                return val

        # 2. Nested object with "net" key
        nested = data.get(prefix)
        if isinstance(nested, dict):
            for sub_key in ("net", "net_flow", "value", "amount"):
                val = self._to_float(nested.get(sub_key))
                if val is not None:
                    return val

        # 3. Fallback: scan keys for prefix match
        for key, value in data.items():
            if prefix in key.lower() and key != exact_key:
                val = self._to_float(value)
                if val is not None:
                    return val

        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Safely convert a value to float, returning None on failure."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
