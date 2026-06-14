"""Optional Kronos model imports — replaced by mocks in dev mode.

The heavy ``transformers`` import is deferred: only ``kronos`` is
checked at module level (fast).  If absent, all three names are set to
``None``.  The caller (``KronosEngine._default_model_loader``) falls
back to a mock predictor when the real package is missing.
"""

from __future__ import annotations

Kronos = None  # type: ignore
KronosTokenizer = None  # type: ignore
KronosPredictor = None  # type: ignore

try:
    from kronos import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
except ImportError:
    pass

__all__ = ["Kronos", "KronosTokenizer", "KronosPredictor"]
