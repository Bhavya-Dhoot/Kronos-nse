from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from headless.runtime import ApplicationRuntime


@pytest.fixture
def config():
    return {"collector": {"universe": "NIFTY50", "live_candle_timeframe": "5min"}}


@pytest.mark.asyncio
async def test_init_visual_mode(config):
    with patch("headless.runtime.load_config", return_value=config):
        rt = ApplicationRuntime("VISUAL")
        assert rt.mode == "VISUAL"
        assert rt.collector is None
        assert rt.headless is None


@pytest.mark.asyncio
async def test_shutdown_no_services(config):
    with patch("headless.runtime.load_config", return_value=config):
        rt = ApplicationRuntime("VISUAL")
        await rt.shutdown()


@pytest.mark.asyncio
async def test_training_mode_short_circuit(config):
    with (
        patch("headless.runtime.load_config", return_value=config),
        patch("headless.runtime.build_inference_context", AsyncMock()) as mock_build,
    ):
        mock_build.return_value.registry = AsyncMock()
        rt = ApplicationRuntime("TRAIN")
        with patch.object(rt, "_run_training", AsyncMock()) as mock_train:
            await rt.start()
            mock_train.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_sets_mode(config):
    with patch("headless.runtime.load_config", return_value=config):
        rt = ApplicationRuntime("COLLECT")
        assert rt.mode == "COLLECT"
