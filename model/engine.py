"""Kronos inference engine with hot-swap, caching, DQG gate, and batch predict."""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from data.quality.gate import DataQualityGate, DQGFailureError, DQGStatus
from model.context_builder import ContextBuilder
from model.predictor import KronosPredictorWrapper, PredictionError
from model.registry import ModelRegistry
from variance import PredictionModifier

logger = logging.getLogger(__name__)


class _MockPredictor:
    """Mock predictor for dev mode when the real kronos package is absent.

    Returns a synthetic prediction DataFrame shaped like a real one, with
    direction bias, confidence scores, and multi-sample ensembles so the
    TUI can display realistic conviction even in dev mode.
    """

    def __init__(self, paths: dict[str, str], device: str = "cpu") -> None:
        self._paths = paths
        self.device = device
        logger.info("MockPredictor initialized (dev mode, device=%s)", device)

    def predict(
        self,
        df: pd.DataFrame,
        x_ts: pd.DatetimeIndex,
        y_ts: pd.DatetimeIndex,
        pred_len: int = 12,
        sample_count: int | None = None,
        temperature: float = 0.7,
        vix_level: float | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        sample_count = sample_count or 3
        last_close = float(df["close"].iloc[-1]) if not df.empty else 1000.0

        # Direction bias: if the last 5 closes are rising → bias UP
        recent = df["close"].iloc[-5:].values if len(df) >= 5 else [last_close] * 5
        slope = (recent[-1] - recent[0]) / max(len(recent), 1)
        bias_up = slope > 0

        # Confidence inversely proportional to temperature + noise
        base_conf = max(
            0.55, min(0.90, 0.8 - temperature * 0.2 + np.random.uniform(-0.05, 0.05))
        )
        direction_conf = base_conf if abs(slope / max(last_close, 1)) > 0.001 else 0.55

        # VIX-scaled noise multiplier: higher VIX → wider prediction spread
        # Minimum multiplier is 1.0 (no-VIX baseline), scales up with VIX
        noise_multiplier = (
            max(1.0, 0.5 + (vix_level / 40)) if vix_level is not None and vix_level > 0 else 1.0
        )

        # Build ensemble samples
        all_samples = []
        for _ in range(sample_count):
            noise_scale = (0.005 + temperature * 0.01) * noise_multiplier
            raw = np.random.randn(pred_len, 6).astype(np.float32)
            drift = np.linspace(0, 0.02 if bias_up else -0.02, pred_len).reshape(-1, 1)
            raw[:, :4] = raw[:, :4] * noise_scale + 1.0 + drift
            raw[:, 0] -= 0.002  # open slightly below close
            raw[:, 1] += 0.003  # high slightly above
            raw[:, 2] -= 0.003  # low slightly below
            raw[:, 4:] = np.abs(raw[:, 4:]) * 1000 * (1 + np.random.uniform(-0.2, 0.2))
            s = pd.DataFrame(
                raw,
                columns=["open", "high", "low", "close", "volume", "amount"],
                index=y_ts[:pred_len],
            )
            s *= last_close / s["close"].iloc[0]
            all_samples.append(s)

        # Mean ensemble = primary output
        result = sum(all_samples) / len(all_samples)

        return result, {
            "sample_count": sample_count,
            "confidence": float(round(direction_conf, 4)),
            "direction": "UP" if bias_up else "DOWN",
            "latency_ms": float(round(np.random.uniform(80, 350), 1)),
        }


class KronosEngine:
    """Inference engine with Redis cache, DQG gate, and version hot-swap."""

    def __init__(
        self,
        config: dict[str, Any],
        registry: ModelRegistry,
        redis_cache: Any,
        *,
        dqg: DataQualityGate | None = None,
        context_builder: ContextBuilder | None = None,
        db: Any | None = None,
        model_loader: Any | None = None,
        modifier: PredictionModifier | None = None,
        mve: Any | None = None,
        watcher_interval_s: int = 60,
    ) -> None:
        self.config = config
        self.registry = registry
        self.redis = redis_cache
        self._dqg = dqg
        self._context_builder = context_builder
        self._db = db
        self._model_loader = model_loader or self._default_model_loader
        self._modifier = modifier
        self._mve = mve
        self._watcher_interval_s = watcher_interval_s

        self._model_lock = asyncio.Lock()
        self._predictor: KronosPredictorWrapper | None = None
        self._loaded_version: str | None = None
        self._watcher_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()

        model_cfg = config.get("model") or {}
        self.device = str(model_cfg.get("device", "cuda"))
        self.dtype = str(model_cfg.get("dtype", "bf16"))
        self.lookback = int(model_cfg.get("lookback", 225))
        self.sample_count = int(model_cfg.get("default_sample_count", 3))
        self.temperature = float(model_cfg.get("default_temperature", 0.7))
        self.pred_len_default = int(model_cfg.get("default_pred_len", 12))

        self._load_model_sync()
        self._watcher_task = asyncio.create_task(self._version_watcher())
        self._background_tasks.add(self._watcher_task)

    def _default_model_loader(self, paths: dict[str, str]) -> Any:
        """Load model from disk. Override in tests.

        Validates checkpoint files before importing the (very slow)
        transformers library, so we fail fast rather than wait for
        a 90-second import just to discover a missing tokenizer.json.

        Falls back to a mock predictor in dev mode when the real
        kronos package is not installed.
        """
        import os as _os

        tok_path = paths["tokenizer"]
        if not _os.path.isfile(_os.path.join(tok_path, "tokenizer.json")):
            raise RuntimeError(
                f"Tokenizer checkpoint at {tok_path} is missing tokenizer.json. "
                "Cannot load with AutoTokenizer fallback — install the kronos package."
            )

        try:
            import importlib

            if importlib.util.find_spec("kronos") is None:
                raise ImportError("kronos package not installed")

            from model.kronos_imports import (  # type: ignore
                Kronos,
                KronosPredictor,
                KronosTokenizer,
            )

            if Kronos is None or KronosTokenizer is None:
                raise ImportError("Kronos classes resolved to None")

            tokenizer = KronosTokenizer.from_pretrained(tok_path)
            model = Kronos.from_pretrained(paths["predictor"])
            if self.dtype in {"float16", "fp16"}:
                model = model.half()
            elif self.dtype in {"bfloat16", "bf16"}:
                model = model.to(dtype=getattr(__import__("torch"), "bfloat16"))
            model = model.to(self.device)
            model.eval()

            try:
                import torch

                if hasattr(torch, "compile"):
                    model = torch.compile(model, mode="reduce-overhead")
            except Exception:
                logger.debug("torch.compile not applied", exc_info=True)

            return KronosPredictor(model, tokenizer, device=self.device)
        except Exception:
            logger.warning(
                "Kronos model classes not available — using mock predictor (dev mode). "
                "Install the kronos package for real inference."
            )
            return _MockPredictor(paths, device=self.device)

    def _warmup(self) -> None:
        """Run dummy predictions to warm CUDA kernels and torch.compile."""
        try:
            import numpy as np

            cols = ["open", "high", "low", "close", "volume", "amount"]
            dummy = pd.DataFrame(
                np.random.randn(self.lookback, 6).astype(np.float32), columns=cols
            )
            dummy["amount"] = dummy["volume"] * dummy[
                ["open", "high", "low", "close"]
            ].mean(axis=1)
            dummy_ts = pd.date_range(
                end=pd.Timestamp.now(tz="Asia/Kolkata"),
                periods=self.lookback,
                freq="5min",
            )
            y_ts = pd.date_range(
                end=dummy_ts[-1] + pd.Timedelta(minutes=5),
                periods=self.pred_len_default,
                freq="5min",
            )
            for temp in (0.5, 0.7, 1.0):
                if self._predictor is not None:
                    self._predictor.predict(
                        dummy,
                        dummy_ts,
                        y_ts,
                        pred_len=self.pred_len_default,
                        temperature=temp,
                    )
            logger.info("Model warm-up complete (3 iterations)")
        except Exception:
            logger.debug("Warm-up skipped", exc_info=True)

    def _load_model_sync(self) -> None:
        """Load model synchronously (called from __init__ — no lock needed)."""
        paths = self.registry.get_production_paths()
        self._predictor = self._model_loader(paths)
        self._loaded_version = paths["version"]
        logger.info("Loaded model version %s", self._loaded_version)
        self._warmup()

    async def _load_model_async(self) -> None:
        """Load model under lock (called from hot-swap watcher)."""
        async with self._model_lock:
            paths = self.registry.get_production_paths()
            self._predictor = self._model_loader(paths)
            self._loaded_version = paths["version"]
            logger.info("Hot-swapped to model version %s", self._loaded_version)
            import torch

            torch.cuda.empty_cache()
            self._warmup()

    async def _version_watcher(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._watcher_interval_s)
                if self.registry.has_production():
                    prod_version = self.registry.get_production_paths()["version"]
                    if prod_version != self._loaded_version:
                        logger.info(
                            "Detected new production version %s — hot-swapping",
                            prod_version,
                        )
                        await self._load_model_async()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Version watcher error")

    def _cache_key(self, symbol: str, x_ts: pd.DatetimeIndex) -> str:
        last = x_ts[-1].isoformat() if len(x_ts) else "none"
        version = self._loaded_version or "none"
        return f"pred:{symbol}:{last}:{version}"

    async def _assert_dqg_pass(self, symbol: str, timeframe: str, mode: str) -> None:
        """Run DQG and raise if status is not PASS."""
        if self._dqg is None:
            return
        report = await self._dqg.run(symbol, timeframe, mode)
        if report.status != DQGStatus.PASS:
            raise DQGFailureError(report)

    def _df_to_result(
        self,
        symbol: str,
        pred_df: pd.DataFrame,
        y_ts: pd.DatetimeIndex,
        meta: dict[str, Any],
        *,
        timeframe: str = "5min",
        mode: str = "VISUAL",
        cached: bool = False,
    ) -> dict[str, Any]:
        result = {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "pred_open": pred_df["open"].astype(float).tolist(),
            "pred_high": pred_df["high"].astype(float).tolist(),
            "pred_low": pred_df["low"].astype(float).tolist(),
            "pred_close": pred_df["close"].astype(float).tolist(),
            "pred_volume": pred_df["volume"].astype(float).tolist(),
            "pred_timestamps": [ts.isoformat() for ts in y_ts[: len(pred_df)]],
            "model_version": self._loaded_version,
            "sample_count": meta.get("sample_count", self.sample_count),
            "temperature": meta.get("temperature", self.temperature),
            "latency_ms": meta.get("latency_ms"),
            "clipped": meta.get("clipped", False),
            "cached": cached,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        _raw_conf = meta.get("confidence")
        if _raw_conf is not None:
            if _raw_conf >= 0.7:
                result["mve_confidence"] = "HIGH"
            elif _raw_conf >= 0.55:
                result["mve_confidence"] = "MEDIUM"
            else:
                result["mve_confidence"] = "LOW"
        return result

    async def _persist_prediction(self, result: dict[str, Any]) -> None:
        """Store prediction in ledger and publish to Redis (non-blocking ledger write)."""
        try:
            await self.redis.publish_prediction(result["symbol"], result)
        except Exception:
            logger.exception(
                "Failed to publish prediction for %s", result.get("symbol")
            )

        if self._db is None:
            return

        async def _store() -> None:
            try:
                await self._db.store_prediction(result)
            except Exception:
                logger.exception(
                    "Failed to store prediction ledger row for %s", result.get("symbol")
                )

        task = asyncio.create_task(_store())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def get_vix_level(self) -> float | None:
        """Return the latest VIX value from the Market Variance Engine."""
        if self._mve is not None:
            try:
                return (
                    float(self._mve._raw_vix)
                    if self._mve._raw_vix is not None
                    else None
                )
            except Exception:
                return None
        return None

    async def predict(
        self,
        symbol: str,
        df: pd.DataFrame,
        x_ts: pd.DatetimeIndex,
        y_ts: pd.DatetimeIndex,
        pred_len: int | None = None,
        sample_count: int | None = None,
        force: bool = False,
        temperature: float | None = None,
        timeframe: str = "5min",
        mode: str = "VISUAL",
        skip_dqg: bool = False,
        vix_level: float | None = None,
    ) -> dict[str, Any]:
        """Run inference with DQG gate, Redis cache, and OHLCV validation."""
        pred_len = pred_len or len(y_ts) or self.pred_len_default

        if not force:
            try:
                cached = await self.redis.get_prediction(symbol, x_ts[-1].isoformat())
                if cached is not None:
                    cached["cached"] = True
                    return cached
            except Exception:
                logger.warning(
                    "Redis cache lookup failed for %s — proceeding without cache",
                    symbol,
                )

        if not skip_dqg:
            await self._assert_dqg_pass(symbol, timeframe, mode)

        # ── Pre-inference modifier: adjust temperature via PredictionModifier ──
        effective_temperature = (
            temperature if temperature is not None else self.temperature
        )
        if self._modifier is not None:
            effective_temperature = self._modifier.modify_pre_inference(
                effective_temperature
            )

        async with self._model_lock:
            if self._predictor is None:
                raise PredictionError("Model not loaded")
            loop = asyncio.get_running_loop()
            try:
                pred_df, meta = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        functools.partial(
                            self._predictor.predict,
                            df,
                            x_ts,
                            y_ts,
                            pred_len=pred_len,
                            sample_count=sample_count,
                            temperature=effective_temperature,
                            vix_level=vix_level,
                        ),
                    ),
                    timeout=120,
                )
            except TimeoutError:
                raise PredictionError(
                    f"Model inference timed out (>120s) for {symbol}"
                ) from None

        if pred_df.isna().any().any():
            raise PredictionError("NaN values in model output")

        result = self._df_to_result(
            symbol,
            pred_df,
            y_ts,
            meta,
            timeframe=timeframe,
            mode=mode,
            cached=False,
        )

        # ── Post-inference modifier: apply MVS-driven modifications ──
        if self._modifier is not None:
            result.setdefault("temperature", self.temperature)
            result = self._modifier.modify_post_inference(result)

        try:
            await self.redis.set_prediction(
                symbol, x_ts[-1].isoformat(), result, ttl=300
            )
        except Exception:
            logger.warning("Failed to cache prediction result in Redis for %s", symbol)
        try:
            await self._persist_prediction(result)
        except Exception:
            logger.exception("Failed to persist prediction result for %s", symbol)
        return result

    async def predict_symbol(
        self,
        symbol: str,
        timeframe: str = "5min",
        mode: str = "VISUAL",
        pred_len: int | None = None,
        sample_count: int | None = None,
        force: bool = False,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Build context from DB, run DQG, and predict."""
        if self._context_builder is None:
            raise RuntimeError("ContextBuilder not configured on KronosEngine")
        ctx = await self._context_builder.build(symbol, timeframe, mode)
        effective_temp = temperature
        if effective_temp is None and "temperature_override" in ctx:
            effective_temp = ctx["temperature_override"]
        result = await self.predict(
            symbol=symbol,
            df=ctx["df"],
            x_ts=ctx["x_ts"],
            y_ts=ctx["y_ts"],
            pred_len=pred_len,
            sample_count=sample_count,
            force=force,
            temperature=effective_temp,
            timeframe=timeframe,
            mode=mode,
        )
        if "regime" in ctx:
            result["regime"] = ctx["regime"]
        return result

    async def close(self) -> None:
        """Cancel watcher task and release resources."""
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None

        # Cancel any orphaned background tasks
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            _, pending = await asyncio.wait(
                list(self._background_tasks),
                timeout=5,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for t in pending:
                logger.warning("Background task %s did not stop in time", t)
            self._background_tasks.clear()

        # Release GPU memory
        self._predictor = None
        import torch

        torch.cuda.empty_cache()

    async def predict_batch(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Batch predict — parallel with configurable concurrency, per-item error handling."""
        max_parallel = self.config.get("model", {}).get("max_parallel_inference", 2)
        sem = asyncio.Semaphore(max_parallel)

        async def _predict_one(req: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                try:
                    return await self.predict(
                        symbol=req["symbol"],
                        df=req["df"],
                        x_ts=req["x_ts"],
                        y_ts=req["y_ts"],
                        pred_len=req.get("pred_len"),
                        sample_count=req.get("sample_count"),
                        force=req.get("force", False),
                        temperature=req.get("temperature"),
                        timeframe=req.get("timeframe", "5min"),
                        mode=req.get("mode", "VISUAL"),
                        skip_dqg=req.get("skip_dqg", False),
                    )
                except Exception:
                    logger.exception(
                        "Prediction failed for %s", req.get("symbol", "unknown")
                    )
                    return {
                        "symbol": req.get("symbol", "unknown"),
                        "error": "prediction_failed",
                        "pred_close": [],
                        "pred_open": [],
                        "pred_high": [],
                        "pred_low": [],
                        "model_version": self._loaded_version or "",
                        "generated_at": datetime.now(UTC).isoformat(),
                    }

        results = await asyncio.gather(*[_predict_one(req) for req in requests])
        return list(results)
