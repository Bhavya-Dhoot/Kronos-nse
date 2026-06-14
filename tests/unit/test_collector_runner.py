from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from data.collector.runner import CollectionRunner


@pytest.mark.asyncio
async def test_run_incremental_delegates_to_fetcher():
    ctx = MagicMock()
    ctx.config = {"collector": {"universe": "NIFTY50", "timeframes": ["5min"]}}
    ctx.fetcher.incremental_update = AsyncMock(return_value={"SBIN": {"5min": 10}})
    runner = CollectionRunner(ctx)
    out = await runner.run_incremental()
    assert out["SBIN"]["5min"] == 10
    ctx.fetcher.incremental_update.assert_awaited_once()
