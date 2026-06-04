"""Dimension-specific collectors for MVE."""

from __future__ import annotations

from variance.collectors.vix_collector import VIXCollector
from variance.collectors.options_collector import OptionsCollector
from variance.collectors.fii_dii_collector import FIIDIICollector
from variance.collectors.oi_collector import OICollector
from variance.collectors.gift_nifty_collector import GIFTNiftyCollector
from variance.collectors.global_markets_collector import GlobalMarketsCollector

__all__ = [
    "VIXCollector",
    "OptionsCollector",
    "FIIDIICollector",
    "OICollector",
    "GIFTNiftyCollector",
    "GlobalMarketsCollector",
]
