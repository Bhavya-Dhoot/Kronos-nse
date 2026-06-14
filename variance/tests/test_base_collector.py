"""Unit tests for BaseVarianceCollector ABC.

All external dependencies (fetch) are mocked.
No live API or Redis required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from variance.base_collector import BaseVarianceCollector
from variance.schemas import ParseResult


class MockCollector(BaseVarianceCollector):
    """Minimal concrete subclass for testing the ABC interface."""

    async def fetch(self) -> Any:
        return {"data": 42}

    def parse(self, raw: Any) -> ParseResult:
        return ParseResult(
            raw_value=42.0,
            normalized=0.5,
            direction=1,
            magnitude=0.5,
            detail={},
            source="mock",
            as_of=datetime.now(UTC).isoformat(),
        )

    def score(self, parsed: ParseResult) -> float:
        return 0.5


@pytest.fixture
def mock_collector() -> MockCollector:
    return MockCollector(name="test", poll_interval=1)


class TestABCInterface:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            BaseVarianceCollector("test")  # type: ignore

    def test_concrete_subclass_can_be_instantiated(self, mock_collector):
        assert isinstance(mock_collector, BaseVarianceCollector)


class TestPollFlow:
    @pytest.mark.asyncio
    async def test_poll_calls_fetch_parse_score_in_order(self, mock_collector):
        fetch_mock = AsyncMock(return_value={"data": 42})
        parse_mock = MagicMock(
            return_value=ParseResult(
                raw_value=42.0,
                normalized=0.5,
                direction=1,
                magnitude=0.5,
                detail={},
                source="mock",
                as_of=datetime.now(UTC).isoformat(),
            )
        )
        score_mock = MagicMock(return_value=0.5)

        mock_collector.fetch = fetch_mock
        mock_collector.parse = parse_mock
        mock_collector.score = score_mock

        result = await mock_collector.poll()

        fetch_mock.assert_awaited_once()
        parse_mock.assert_called_once_with({"data": 42})
        score_mock.assert_called_once()
        assert result["normalized"] == 0.5
        assert "as_of" in result

    @pytest.mark.asyncio
    async def test_poll_returns_parse_result(self, mock_collector):
        result = await mock_collector.poll()

        expected_keys = {
            "raw_value",
            "normalized",
            "direction",
            "magnitude",
            "detail",
            "source",
            "as_of",
        }
        assert expected_keys.issubset(result.keys())
        assert result["raw_value"] == 42.0
        assert result["normalized"] == 0.5
        assert result["source"] == "mock"


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_trips_after_5_errors(self, mock_collector):
        mock_collector.fetch = AsyncMock(side_effect=Exception("API down"))

        for _ in range(5):
            with pytest.raises(Exception):
                await mock_collector.poll()

        assert mock_collector.is_available is False
        assert mock_collector._consecutive_errors == 5

    @pytest.mark.asyncio
    async def test_resets_on_success(self, mock_collector):
        fetch_mock = AsyncMock()
        fetch_mock.side_effect = [Exception("fail")] * 3 + [{"data": 42}]

        mock_collector.fetch = fetch_mock

        for _ in range(3):
            with pytest.raises(Exception):
                await mock_collector.poll()

        assert mock_collector.is_available is True
        assert mock_collector._consecutive_errors == 3

        result = await mock_collector.poll()
        assert result["raw_value"] == 42.0
        assert mock_collector._consecutive_errors == 0
        assert mock_collector.is_available is True


class TestStaleValues:
    @pytest.mark.asyncio
    async def test_stale_result_on_error_with_cache(self, mock_collector):
        await mock_collector.poll()
        assert mock_collector._last_successful_result is not None

        mock_collector.fetch = AsyncMock(side_effect=Exception("API down"))

        stale = await mock_collector.poll()
        assert stale["raw_value"] == 42.0
        assert stale["source"] == "mock"
        assert mock_collector._consecutive_errors == 1


class TestProperties:
    def test_is_available_default(self, mock_collector):
        assert mock_collector.is_available is True

    def test_name_and_poll_interval(self, mock_collector):
        assert mock_collector.name == "test"
        assert mock_collector.poll_interval == 1
