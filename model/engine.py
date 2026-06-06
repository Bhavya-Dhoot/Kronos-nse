"""Kronos inference engine with hot-swap, caching, DQG gate, and batch predict."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import pandas as pd

from data.quality.gate import DQGFailureError, DQGStatus, DataQualityGate
from model.context_builder import ContextBuilder
from model.predictor import PredictionError
from model.registry import ModelRegistry
from variance import PredictionModifier

logger = logging.getLogger(__name__)


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

        model_cfg = config.get("model") or {}
        self.device = str(model_cfg.get("device", "cuda"))
        self.dtype = str(model_cfg.get("dtype", "bf16"))
        self.lookback = int(model_cfg.get("lookback", 225))
        self.sample_count = int(model_cfg.get("default_sample_count", 3))
        self.temperature = float(model_cfg.get("default_temperature", 0.7))
        self.pred_len_default = int(model_cfg.get("default_pred_len", 12))

        self._load_model_sync()
        self._watcher_task = asyncio.create_task(self._version_watcher())

    def _default_model_loader(self, paths: dict[str, str]) -> Any:
        """Load model from disk. Override in tests."""
        try:
            from model.kronos_imports import Kronos, KronosTokenizer, KronosPredictor  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "Kronos model classes not available. Install model package or use mocks in tests."
            ) from exc

        if Kronos is None or KronosTokenizer is None:
            raise RuntimeError(
                "Kronos model classes not available. Install model package or use mocks in tests."
            )

        tokenizer = KronosTokenizer.from_pretrained(paths["tokenizer"])
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

    def _warmup(self) -> None:
        """Run dummy predictions to warm CUDA kernels and torch.compile."""
        try:
            import numpy as np
            cols = ["open", "high", "low", "close", "volume", "amount"]
            dummy = pd.DataFrame(np.random.randn(self.lookback, 6).astype(np.float32), columns=cols)
            dummy["amount"] = dummy["volume"] * dummy[["open", "high", "low", "close"]].mean(axis=1)
            dummy_ts = pd.date_range(end=pd.Timestamp.now(tz="Asia/Kolkata"), periods=self.lookback, freq="5min")
            y_ts = pd.date_range(end=dummy_ts[-1] + pd.Timedelta(minutes=5), periods=self.pred_len_default, freq="5min")
            for temp in (0.5, 0.7, 1.0):
                if self._predictor is not None:
                    self._predictor.predict(dummy, dummy_ts, y_ts, pred_len=self.pred_len_default, temperature=temp)
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
        return f"pred:{symbol}:{last}"

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
        return {
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
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def _persist_prediction(self, result: dict[str, Any]) -> None:
        """Store prediction in ledger and publish to Redis (non-blocking ledger write)."""
        try:
            await self.redis.publish_prediction(result["symbol"], result)
        except Exception:
            logger.exception("Failed to publish prediction for %s", result.get("symbol"))

        if self._db is None:
            return

        async def _store() -> None:
            try:
                await self._db.store_prediction(result)
            except Exception:
                logger.exception("Failed to store prediction ledger row for %s", result.get("symbol"))

        asyncio.create_task(_store())

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
    ) -> dict[str, Any]:
        """Run inference with DQG gate, Redis cache, and OHLCV validation."""
        pred_len = pred_len or len(y_ts) or self.pred_len_default

        if not force:
            cached = await self.redis.get_prediction(symbol, x_ts[-1].isoformat())
            if cached is not None:
                cached["cached"] = True
                return cached

        if not skip_dqg:
            await self._assert_dqg_pass(symbol, timeframe, mode)

        # ── Pre-inference modifier: adjust temperature via PredictionModifier ──
        effective_temperature = temperature if temperature is not None else self.temperature
        if self._modifier is not None:
            effective_temperature = self._modifier.modify_pre_inference(effective_temperature)

        async with self._model_lock:
            if self._predictor is None:
                raise PredictionError("Model not loaded")
            pred_df, meta = self._predictor.predict(
                df,
                x_ts,
                y_ts,
                pred_len=pred_len,
                sample_count=sample_count,
                temperature=effective_temperature,
            )

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

        await self.redis.set_prediction(symbol, x_ts[-1].isoformat(), result, ttl=300)
        await self._persist_prediction(result)
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

    async def predict_batch(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch predict — sequential under lock (interface ready for true GPU batching)."""
        results: list[dict[str, Any]] = []
        for req in requests:
            out = await self.predict(
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
            results.append(out)
        return results
