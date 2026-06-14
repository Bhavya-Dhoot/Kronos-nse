"""VIXCollector — polls India VIX every 60s via NseIndiaApi."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from variance.base_collector import BaseVarianceCollector
from variance.collectors._nse import _fetch_all_indices
from variance.schemas import ParseResult


class VIXCollector(BaseVarianceCollector):
    """Poll India VIX index every 60s.

    Per D-05: fetch() calls _fetch_all_indices() and extracts INDIAVIX.
    Per D-06: VIX scoring uses piecewise linear between 4 anchor points:
    VIX 30→-1.0, VIX 20→-0.3, VIX 15→0.0, VIX 10→0.8. Clamped to [-1.0, 1.0].
    Below VIX 10 → 0.8 (no higher). Above VIX 30 → -1.0 (no lower).
    """

    def __init__(self) -> None:
        super().__init__(name="vix", poll_interval=300)

    async def fetch(self) -> Any:
        """Fetch all NSE indices and locate INDIAVIX entry."""
        return await _fetch_all_indices()

    def parse(self, raw: Any) -> ParseResult:
        """Extract INDIAVIX value from the list of index entries."""
        vix_value: float | None = None

        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and entry.get("key") == "INDIAVIX":
                    v = entry.get("value")
                    if v is not None:
                        vix_value = float(v)
                    break
            else:
                for entry in raw:
                    if isinstance(entry, dict):
                        for key in ("key", "index", "name", "symbol", "indexSymbol"):
                            if entry.get(key) in (
                                "INDIAVIX",
                                "INDIA VIX",
                                "VIX",
                                "India VIX",
                                "India VIX",
                            ):
                                for val_key in ("last", "value", "price", "lastPrice"):
                                    v = entry.get(val_key)
                                    if v is not None:
                                        vix_value = float(v)
                                        break
                    if vix_value is not None:
                        break

        if vix_value is None:
            raise ValueError("INDIAVIX not found in NseIndiaApi response")

        return ParseResult(
            raw_value=vix_value,
            normalized=0.0,
            direction=-1 if vix_value > 15 else (1 if vix_value < 15 else 0),
            magnitude=abs(vix_value - 15) / 15,
            detail={"vix_raw": vix_value, "vix_baseline": 15},
            source="nse",
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        """Score VIX value using piecewise linear mapping.

        Anchor points (per D-06):
        VIX 30 → -1.0, VIX 20 → -0.3, VIX 15 →  0.0, VIX 10 →  0.8
        """
        vix = parsed["raw_value"]
        anchors = [(10, 0.8), (15, 0.0), (20, -0.3), (30, -1.0)]

        if vix <= anchors[0][0]:
            return 0.8
        if vix >= anchors[-1][0]:
            return -1.0

        for i in range(len(anchors) - 1):
            x1, y1 = anchors[i]
            x2, y2 = anchors[i + 1]
            if x1 <= vix <= x2:
                return y1 + (vix - x1) * (y2 - y1) / (x2 - x1)

        return 0.0
