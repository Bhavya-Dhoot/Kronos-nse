"""Unit tests for TUI library modules — store, levels, chart, sidebar."""

from __future__ import annotations

import pytest

from scripts.tui_lib.chart import _fmt_age, _fmt_price, _nice_ticks
from scripts.tui_lib.levels import (
    _cfloat,
    classify_regime,
    compute_obv,
    compute_volume_profile_poc,
    compute_volume_ratio,
)
from scripts.tui_lib.sidebar import PredictionPanel, RegimePanel
from scripts.tui_lib.store import (
    BullBiasTracker,
    LatencyHistory,
    LtpAccuracyTracker,
    PredictionRecord,
    RollingAccuracy,
    SessionAccuracyTracker,
    VolumeAccuracyTracker,
)


def test_cfloat_none() -> None:
    assert _cfloat(None) == 0.0
    assert _cfloat(None, 5.0) == 5.0


def test_cfloat_string() -> None:
    assert _cfloat("123.45") == 123.45
    assert _cfloat("abc", -1.0) == -1.0


def test_cfloat_number() -> None:
    assert _cfloat(42) == 42.0
    assert _cfloat(3.14) == 3.14


def test_ltp_tracker_empty() -> None:
    t = LtpAccuracyTracker()
    assert t.last_error() is None
    assert t.avg_error() == 0.0
    assert t.direction_rate() == 0.0
    assert t.count() == 0


def test_ltp_tracker_record() -> None:
    t = LtpAccuracyTracker(maxlen=5)
    t.record(100.0, 102.0)
    assert t.count() == 1
    assert t.last_error() == 2.0
    assert t.avg_error() == 2.0
    assert t.direction_rate() == 100.0

    t.record(100.0, 95.0)
    assert t.count() == 2
    assert t.last_error() == 5.0
    assert t.avg_error() == 3.5
    assert t.direction_rate() == 50.0


def test_ltp_tracker_maxlen() -> None:
    t = LtpAccuracyTracker(maxlen=3)
    for i in range(5):
        t.record(100.0, 100.0 + float(i))
    assert t.count() == 3


def test_session_ltp_accuracy() -> None:
    s = SessionAccuracyTracker()
    acc = s.get_ltp_accuracy()
    assert acc["count"] == 0
    assert acc["last_error"] is None

    s.record_ltp_accuracy(100.0, 103.0)
    acc = s.get_ltp_accuracy()
    assert acc["count"] == 1
    assert acc["last_error"] == 3.0
    assert acc["direction_rate"] == 100.0


def test_rolling_accuracy() -> None:
    r = RollingAccuracy(maxlen=5)
    assert r.pct() == 0.0
    assert r.count() == 0

    r.add(True)
    r.add(True)
    r.add(False)
    assert r.count() == 3
    assert r.pct() == 66.7

    r.clear()
    assert r.count() == 0
    assert r.pct() == 0.0


def test_classify_regime_ltp_accepts_param() -> None:
    candles = []
    for i in range(21):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 100.0,
                "high": 100.3,
                "low": 99.7,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    result = classify_regime(candles, pred_close=[100, 101, 102], ltp=95.0)
    assert "regime" in result
    assert result["direction_strength"] >= 0
    assert result["bias"] >= 0


def test_classify_regime_not_enough_candles() -> None:
    result = classify_regime([], pred_close=[100, 101])
    assert result["regime"] == "RANGING"


def test_classify_regime_no_pred_close() -> None:
    candles = []
    for i in range(22):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000.0,
            }
        )
    result = classify_regime(candles)
    assert "regime" in result
    assert result["direction_strength"] >= 0
    assert result["bias"] >= 0


# --- VolumeAccuracyTracker ---


def test_vol_tracker_empty() -> None:
    t = VolumeAccuracyTracker()
    assert t.last_error_pct() is None
    assert t.avg_error_pct() == 0.0
    assert t.direction_rate() == 0.0
    assert t.count() == 0


def test_vol_tracker_record() -> None:
    t = VolumeAccuracyTracker(maxlen=5)
    t.record(1000.0, 1100.0)
    assert t.count() == 1
    expected_pct = abs(1000 - 1100) / 1100 * 100
    assert t.last_error_pct() == pytest.approx(expected_pct, 1e-3)
    assert t.avg_error_pct() == pytest.approx(expected_pct, 1e-3)
    assert t.direction_rate() == 100.0

    t.record(1000.0, 800.0, pred_last_vol=1200.0)
    assert t.count() == 2
    expected_pct2 = abs(1000 - 800) / 800 * 100
    assert t.last_error_pct() == pytest.approx(expected_pct2, 1e-3)
    assert t.direction_rate() == 50.0


def test_vol_tracker_maxlen() -> None:
    t = VolumeAccuracyTracker(maxlen=3)
    for i in range(5):
        t.record(1000.0, 1000.0 + float(i))
    assert t.count() == 3


def test_session_vol_accuracy() -> None:
    s = SessionAccuracyTracker()
    acc = s.get_vol_accuracy()
    assert acc["count"] == 0
    assert acc["last_error_pct"] is None

    s.record_vol_accuracy(1000.0, 1050.0)
    acc = s.get_vol_accuracy()
    assert acc["count"] == 1
    assert acc["last_error_pct"] is not None
    assert acc["direction_rate"] == 100.0


# --- Volume ratio ---


def test_volume_ratio_normal() -> None:
    candles = []
    for i in range(25):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    candles[-1]["volume"] = 2000.0
    vr = compute_volume_ratio(candles)
    assert vr is not None
    # last-20 avg = (19*1000 + 2000)/20 = 1050, ratio = 2000/1050 ≈ 1.9
    assert vr == 1.9


def test_volume_ratio_too_few() -> None:
    assert compute_volume_ratio([{"volume": 1000}]) is None
    assert compute_volume_ratio([]) is None


def test_volume_ratio_zero_avg() -> None:
    candles = [{"volume": 0}] * 25
    for c in candles:
        c.update({"open": 100, "high": 101, "low": 99, "close": 100})
    assert compute_volume_ratio(candles) is None


# --- OBV ---


def test_obv_up_trend() -> None:
    candles = []
    for i in range(10):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000.0,
            }
        )
    obv = compute_obv(candles)
    assert obv["direction"] == "UP"
    assert obv["value"] > 0


def test_obv_down_trend() -> None:
    candles = []
    for i in range(10):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 110.0 - i,
                "high": 111.0 - i,
                "low": 109.0 - i,
                "close": 109.5 - i,
                "volume": 1000.0,
            }
        )
    obv = compute_obv(candles)
    assert obv["direction"] == "DOWN"
    assert obv["value"] < 0


def test_obv_too_few() -> None:
    obv = compute_obv([{"close": 100, "volume": 1000}])
    assert obv["direction"] == "FLAT"


# --- Volume Profile POC ---


def test_volume_profile_poc() -> None:
    candles = []
    for i in range(20):
        candles.append(
            {
                "time": f"2026-01-01T09:{i:02d}:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    # All candles span 99-101 with equal volume.
    # With old midpoint binning, POC was at 100.
    # With proportional distribution, volume spreads across the 3-4
    # overlapping bins, making POC slightly below 100.
    poc = compute_volume_profile_poc(candles)
    assert poc is not None
    assert 98.0 <= poc <= 102.0
    assert abs(poc - 100.0) < 2.0


def test_volume_profile_poc_too_few() -> None:
    assert compute_volume_profile_poc([]) is None
    assert (
        compute_volume_profile_poc([{"high": 100, "low": 90, "volume": 1000}]) is None
    )


# --- chart.py ---


def test_fmt_price_none() -> None:
    assert _fmt_price(None) == "--"


def test_fmt_price_zero() -> None:
    assert _fmt_price(0) == "0.00"


def test_fmt_price_small() -> None:
    assert _fmt_price(123.456) == "123.46"


def test_fmt_price_large() -> None:
    assert _fmt_price(123456.78) == "123,457"


def test_fmt_age_none() -> None:
    assert _fmt_age(None) == "--"


def test_fmt_age_seconds() -> None:
    assert _fmt_age(5) == "5s"


def test_fmt_age_minutes() -> None:
    assert _fmt_age(180) == "3m"


def test_fmt_age_hours() -> None:
    assert _fmt_age(5400) == "1.5h"


def test_nice_ticks_basic() -> None:
    ticks = _nice_ticks(90, 110, n=5)
    assert len(ticks) >= 2
    assert ticks[0] <= 90
    assert ticks[-1] >= 110


def test_nice_ticks_equal() -> None:
    ticks = _nice_ticks(100, 100)
    assert ticks == [100]


# --- sidebar.py panels ---


def test_prediction_panel_render_empty() -> None:
    p = PredictionPanel()
    p.update_data(None)
    t = p.render()
    assert isinstance(t.plain, str)
    assert len(t.plain) > 0


def test_regime_panel_render_empty() -> None:
    r = RegimePanel()
    r.update_data({})
    t = r.render()
    assert "computing" in t.plain


def test_regime_panel_render_with_data() -> None:
    r = RegimePanel()
    r.update_data(
        {
            "regime": "TRENDING_UP",
            "label": "↑ TRENDING",
            "color": "bold green",
            "direction_strength": 75.0,
            "bias": 80,
            "atr_pct": 0.5,
        }
    )
    t = r.render()
    assert "TRENDING" in t.plain


# --- store.py additional tests ---


def test_prediction_record_is_mature_naive_utc() -> None:
    rec = PredictionRecord(
        "TEST", "2026-01-01T10:00:00Z", ["2026-01-01T09:30:00"], [100.0]
    )
    assert rec.is_mature() is True


def test_prediction_record_is_mature_future() -> None:
    rec = PredictionRecord(
        "TEST", "2026-01-01T10:00:00Z", ["2099-01-01T00:00:00"], [100.0]
    )
    assert rec.is_mature() is False


def test_prediction_record_is_mature_empty() -> None:
    rec = PredictionRecord("TEST", "2026-01-01T10:00:00Z", [], [])
    assert rec.is_mature() is False


def test_prediction_record_no_timestamps() -> None:
    rec = PredictionRecord("TEST", "2026-01-01T10:00:00Z", [], [])
    assert rec.is_mature() is False


def test_prediction_record_compute_accuracy_empty() -> None:
    rec = PredictionRecord(
        "TEST", "2026-01-01T10:00:00Z", ["2026-01-01T09:30:00"], [100.0]
    )
    rec.compute_accuracy([])
    assert rec.accuracy_checked is True
    assert rec.mae is None


def test_latency_history_empty() -> None:
    lo = LatencyHistory(maxlen=10)
    assert lo.latest() is None
    assert lo.get_sparkline(5) == " " * 5


def test_latency_history_record() -> None:
    lo = LatencyHistory(maxlen=10)
    lo.add(100)
    lo.add(200)
    lo.add(300)
    assert lo.latest() == 300
    assert len(lo.get_sparkline(5)) > 0


def test_bull_bias_tracker() -> None:
    b = BullBiasTracker()
    assert b.pct() == 50.0
    assert b.count() == 0
    b.add(True)
    b.add(True)
    b.add(False)
    assert b.count() == 3
    assert b.pct() == pytest.approx(66.7, rel=0.1)
