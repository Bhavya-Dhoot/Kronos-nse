"""Prediction storage, accuracy comparison, and session tracking for TUI v2."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any


def _normalize_ts(ts: str) -> str:
    s = ts.replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    if len(s) > 19 and s[19] in ("+", "-"):
        s = s[:19]
    return s


class PredictionRecord:
    def __init__(
        self,
        symbol: str,
        generated_at: str,
        timestamps: list[str],
        pred_close: list[float],
        pred_open: list[float] | None = None,
        pred_high: list[float] | None = None,
        pred_low: list[float] | None = None,
        confidence: float | None = None,
    ):
        self.symbol = symbol
        self.generated_at = generated_at
        self.timestamps = list(timestamps)
        self.pred_close = list(pred_close)
        self.pred_open = list(pred_open) if pred_open else []
        self.pred_high = list(pred_high) if pred_high else []
        self.pred_low = list(pred_low) if pred_low else []
        self.confidence = confidence

        self.actual_open: list[float] | None = None
        self.actual_high: list[float] | None = None
        self.actual_low: list[float] | None = None
        self.actual_close: list[float] | None = None
        self.mae: float | None = None
        self.dir_accuracy: float | None = None
        self.accuracy_checked: bool = False
        self.dir_correct: bool | None = None
        self.ltp_at_prediction: float | None = None
        self.ltp_error: float | None = None
        self.ltp_dir_correct: bool | None = None

    def is_mature(self) -> bool:
        if not self.timestamps:
            return False
        last_ts = self.timestamps[-1]
        try:
            if "T" in last_ts:
                dt = datetime.fromisoformat(last_ts)
                if dt.tzinfo is not None:
                    dt_utc = dt.astimezone(UTC)
                else:
                    dt_utc = dt.replace(tzinfo=UTC)
            else:
                dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                dt_utc = dt.replace(tzinfo=UTC)
            return dt_utc < datetime.now(UTC)
        except (ValueError, TypeError):
            return False

    def set_ltp_at_prediction(self, ltp: float) -> None:
        self.ltp_at_prediction = ltp

    def compute_ltp_accuracy(self, ltp: float) -> None:
        if not self.pred_close:
            return
        self.ltp_error = abs(self.pred_close[0] - ltp)
        pred_dir = self.pred_close[-1] - self.pred_close[0]
        actual_dir = ltp - self.pred_close[0]
        self.ltp_dir_correct = pred_dir * actual_dir >= 0

    def compute_accuracy(self, actual_candles: list[dict[str, Any]]) -> None:
        ts_map = {}
        for ac in actual_candles:
            raw = ac.get("time", "")
            key = _normalize_ts(raw)
            ts_map[key] = ac

        matched_pred = []
        matched_open = []
        matched_high = []
        matched_low = []
        matched_close = []
        for i, ts in enumerate(self.timestamps):
            key = _normalize_ts(ts)
            act = ts_map.get(key)
            if act is not None and i < len(self.pred_close):
                matched_pred.append(self.pred_close[i])
                matched_open.append(float(act.get("open", 0)))
                matched_high.append(float(act.get("high", 0)))
                matched_low.append(float(act.get("low", 0)))
                matched_close.append(float(act.get("close", 0)))

        if not matched_pred:
            self.accuracy_checked = True
            return

        errors = [abs(p - a) for p, a in zip(matched_pred, matched_close)]
        self.mae = sum(errors) / len(errors)

        pred_dir = matched_pred[-1] - matched_pred[0]
        actual_dir = matched_close[-1] - matched_close[0]
        self.dir_correct = pred_dir * actual_dir >= 0

        dir_correct_count = sum(
            1
            for p, a in zip(matched_pred, matched_close)
            if (p - matched_pred[0]) * (a - matched_close[0]) >= 0
        )
        self.dir_accuracy = dir_correct_count / len(matched_pred)

        self.actual_open = matched_open
        self.actual_high = matched_high
        self.actual_low = matched_low
        self.actual_close = matched_close
        self.accuracy_checked = True


class RollingAccuracy:
    def __init__(self, maxlen: int = 50):
        self._deque: deque[bool] = deque(maxlen=maxlen)

    def add(self, correct: bool) -> None:
        self._deque.append(correct)

    def pct(self) -> float:
        if not self._deque:
            return 0.0
        return round(sum(self._deque) / len(self._deque) * 100, 1)

    def count(self) -> int:
        return len(self._deque)

    def clear(self) -> None:
        self._deque.clear()


class LatencyHistory:
    def __init__(self, maxlen: int = 10):
        self._values: deque[float] = deque(maxlen=maxlen)

    def add(self, latency_ms: float) -> None:
        self._values.append(latency_ms)

    def latest(self) -> float | None:
        return self._values[-1] if self._values else None

    def get_sparkline(self, width: int = 10) -> str:
        if not self._values:
            return " " * width
        vals = list(self._values)
        mn = min(vals)
        mx = max(vals)
        r = mx - mn if mx > mn else 1
        chars = []
        for v in vals:
            pct = (v - mn) / r
            bar_h = max(1, min(4, round(pct * 4)))
            ch = ["▂", "▄", "▆", "▇"][bar_h - 1]
            chars.append(ch)
        return "".join(chars)


class BullBiasTracker:
    def __init__(self, maxlen: int = 50):
        self._deque: deque[bool] = deque(maxlen=maxlen)

    def add(self, is_up: bool) -> None:
        self._deque.append(is_up)

    def pct(self) -> float:
        if not self._deque:
            return 50.0
        return round(sum(self._deque) / len(self._deque) * 100, 1)

    def count(self) -> int:
        return len(self._deque)


class VolumeAccuracyTracker:
    """Tracks volume prediction accuracy — percentage error and direction."""

    def __init__(self, maxlen: int = 20):
        self._pct_errors: deque[float] = deque(maxlen=maxlen)
        self._directions: deque[bool] = deque(maxlen=maxlen)

    def record(
        self,
        pred_first_vol: float,
        actual_vol: float,
        pred_last_vol: float | None = None,
    ) -> None:
        pct_error = abs(pred_first_vol - actual_vol) / max(actual_vol, 1e-6) * 100
        self._pct_errors.append(pct_error)
        if pred_last_vol is not None:
            pred_dir = pred_last_vol - pred_first_vol
            actual_dir = actual_vol - pred_first_vol
            direction_correct = pred_dir * actual_dir >= 0
        else:
            direction_correct = actual_vol >= pred_first_vol
        self._directions.append(direction_correct)

    def last_error_pct(self) -> float | None:
        return self._pct_errors[-1] if self._pct_errors else None

    def avg_error_pct(self) -> float:
        if not self._pct_errors:
            return 0.0
        return round(sum(self._pct_errors) / len(self._pct_errors), 2)

    def direction_rate(self) -> float:
        if not self._directions:
            return 0.0
        return round(sum(self._directions) / len(self._directions) * 100, 1)

    def count(self) -> int:
        return len(self._pct_errors)


class LtpAccuracyTracker:
    """Tracks real-time LTP vs prediction accuracy — error and direction."""

    def __init__(self, maxlen: int = 20):
        self._errors: deque[float] = deque(maxlen=maxlen)
        self._directions: deque[bool] = deque(maxlen=maxlen)

    def record(
        self, pred_first_close: float, ltp: float, pred_last_close: float | None = None
    ) -> None:
        error = abs(pred_first_close - ltp)
        self._errors.append(error)
        if pred_last_close is not None:
            pred_dir = pred_last_close - pred_first_close
            actual_dir = ltp - pred_first_close
            direction_correct = pred_dir * actual_dir >= 0
        else:
            direction_correct = ltp >= pred_first_close
        self._directions.append(direction_correct)

    def last_error(self) -> float | None:
        return self._errors[-1] if self._errors else None

    def avg_error(self) -> float:
        if not self._errors:
            return 0.0
        return round(sum(self._errors) / len(self._errors), 2)

    def direction_rate(self) -> float:
        if not self._directions:
            return 0.0
        return round(sum(self._directions) / len(self._directions) * 100, 1)

    def count(self) -> int:
        return len(self._errors)


class SessionAccuracyTracker:
    def __init__(self):
        self._acc20 = RollingAccuracy(20)
        self._acc50 = RollingAccuracy(50)
        self._bull_bias = BullBiasTracker(50)
        self._latency_hist = LatencyHistory(10)
        self._last_pred_direction: str | None = None
        self._last_pred_confidence: float = 0.0
        self._pred_flip_alert: bool = False
        self._pred_flip_text: str = ""
        self._ltp_acc = LtpAccuracyTracker()
        self._vol_acc = VolumeAccuracyTracker()

    def record_prediction(self, pred: dict[str, Any] | None) -> None:
        if not pred or not pred.get("pred_close"):
            return
        pred_close = pred["pred_close"]
        first = pred_close[0] if pred_close else 0
        last = pred_close[-1] if pred_close else 0
        direction = "UP" if last > first else "DOWN" if last < first else "SIDEWAYS"

        if (
            self._last_pred_direction is not None
            and direction != self._last_pred_direction
        ):
            self._pred_flip_text = (
                f"↺ PRED FLIP: {self._last_pred_direction}→{direction}"
            )
            self._pred_flip_alert = True
        self._last_pred_direction = direction

        raw_conf = pred.get("confidence", pred.get("softmax_score"))
        try:
            self._last_pred_confidence = (
                float(raw_conf) if raw_conf is not None else 0.0
            )
        except (ValueError, TypeError):
            self._last_pred_confidence = 0.0
        self._bull_bias.add(direction == "UP")

    def record_accuracy(self, record: PredictionRecord) -> None:
        if record.dir_correct is not None:
            self._acc20.add(record.dir_correct)
            self._acc50.add(record.dir_correct)

    def record_latency(self, latency_ms: float) -> None:
        self._latency_hist.add(latency_ms)

    def get_bull_bias(self) -> float:
        return self._bull_bias.pct()

    def get_latency(self) -> float | None:
        return self._latency_hist.latest()

    def get_sparkline(self, width: int = 10) -> str:
        return self._latency_hist.get_sparkline(width)

    def record_ltp_accuracy(
        self, pred_first_close: float, ltp: float, pred_last_close: float | None = None
    ) -> None:
        self._ltp_acc.record(pred_first_close, ltp, pred_last_close)

    def record_vol_accuracy(
        self,
        pred_first_vol: float,
        actual_vol: float,
        pred_last_vol: float | None = None,
    ) -> None:
        self._vol_acc.record(pred_first_vol, actual_vol, pred_last_vol)

    def get_vol_accuracy(self) -> dict:
        return {
            "last_error_pct": self._vol_acc.last_error_pct(),
            "avg_error_pct": self._vol_acc.avg_error_pct(),
            "direction_rate": self._vol_acc.direction_rate(),
            "count": self._vol_acc.count(),
        }

    def get_ltp_accuracy(self) -> dict:
        return {
            "last_error": self._ltp_acc.last_error(),
            "avg_error": self._ltp_acc.avg_error(),
            "direction_rate": self._ltp_acc.direction_rate(),
            "count": self._ltp_acc.count(),
        }

    def consume_flip_alert(self) -> str:
        if self._pred_flip_alert:
            self._pred_flip_alert = False
            return self._pred_flip_text
        return ""


class AccuracyStore:
    def __init__(self, max_per_symbol: int = 50):
        self._records: dict[str, list[PredictionRecord]] = {}
        self._max = max_per_symbol
        self.session = SessionAccuracyTracker()

    def add(
        self, symbol: str, pred_data: dict[str, Any], ltp: float | None = None
    ) -> None:
        timestamps = pred_data.get("timestamps", [])
        pred_close = pred_data.get("pred_close", [])
        if not timestamps or not pred_close:
            return
        rec = PredictionRecord(
            symbol=symbol.upper(),
            generated_at=pred_data.get("generated_at", ""),
            timestamps=timestamps,
            pred_close=list(pred_close),
            pred_open=list(pred_data.get("pred_open", [])),
            pred_high=list(pred_data.get("pred_high", [])),
            pred_low=list(pred_data.get("pred_low", [])),
            confidence=pred_data.get("confidence"),
        )
        if symbol not in self._records:
            self._records[symbol] = []
        self._records[symbol].append(rec)
        if len(self._records[symbol]) > self._max:
            self._records[symbol] = self._records[symbol][-self._max :]

        if ltp is not None:
            rec.set_ltp_at_prediction(ltp)

        self.session.record_prediction(pred_data)

    def get_comparisons(
        self, symbol: str, actual_candles: list[dict[str, Any]]
    ) -> list[PredictionRecord]:
        records = self._records.get(symbol.upper(), [])
        matured = [r for r in records if r.is_mature() and not r.accuracy_checked]
        for rec in matured:
            rec.compute_accuracy(actual_candles)
            self.session.record_accuracy(rec)
        checked = [r for r in records if r.accuracy_checked]
        return checked

    def get_latest_prediction(self, symbol: str) -> PredictionRecord | None:
        records = self._records.get(symbol.upper(), [])
        return records[-1] if records else None
