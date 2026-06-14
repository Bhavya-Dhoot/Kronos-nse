from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data.collector.angel_client import AngelOneClient
from data.collector.historical_fetcher import HistoricalFetcher


@pytest.fixture
def smart_mock(monkeypatch):
    smart_cls = MagicMock()
    monkeypatch.setenv("ANGEL_API_KEY", "k")
    monkeypatch.setenv("ANGEL_CLIENT_ID", "id")
    monkeypatch.setenv("ANGEL_PASSWORD", "pw")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "BASE32SECRET")
    monkeypatch.setattr("data.collector.angel_client.SmartConnect", smart_cls)
    return smart_cls


def test_authenticate_success(smart_mock):
    instance = smart_mock.return_value
    instance.generateSession.return_value = {
        "status": True,
        "data": {"jwtToken": "abc"},
    }
    client = AngelOneClient(
        {
            "api_key": "k",
            "client_id": "id",
            "password": "pw",
            "totp_secret": "BASE32SECRET",
        }
    )
    assert client.authenticate() is True
    assert client.jwt_token == "abc"


def test_max_chunk_days_one_minute_is_30():
    assert AngelOneClient.max_chunk_days_for_interval("1min") == 30
    assert AngelOneClient.max_chunk_days_for_interval("5min") == 100
    assert AngelOneClient.resolve_interval("15min") == "FIFTEEN_MINUTE"


def test_authenticate_failure_returns_false_not_raises(smart_mock):
    instance = smart_mock.return_value
    instance.generateSession.return_value = {"status": False, "message": "bad creds"}
    client = AngelOneClient(
        {
            "api_key": "k",
            "client_id": "id",
            "password": "pw",
            "totp_secret": "BASE32SECRET",
        }
    )
    assert client.authenticate() is False


def test_get_historical_chunked_splits_correctly(monkeypatch, smart_mock):
    # make get_historical return a single row tagged by its from_date
    from data.collector.angel_client import AngelOneClient as C

    client = C(
        {
            "api_key": "k",
            "client_id": "id",
            "password": "pw",
            "totp_secret": "BASE32SECRET",
        }
    )
    client._smart = MagicMock()
    client.authenticate = lambda: True  # type: ignore

    calls = []

    def fake_get(symbol_token, exchange, interval, from_date, to_date):
        calls.append((from_date, to_date))
        # Return 1min candles spanning the full range so _suspect_truncation passes
        nrows = max(int((to_date - from_date).total_seconds() / 60), 1)
        rows_list = []
        t = from_date
        for _ in range(nrows):
            rows_list.append([t.isoformat(), 1, 2, 0.5, 1.5, 100])
            t += timedelta(minutes=1)
        return rows_list

    client.get_historical = fake_get  # type: ignore

    start = datetime(2020, 1, 1)
    end = start + timedelta(days=400)
    rows = client.get_historical_chunked("3045", "NSE", "1min", start, end)

    # ONE_MINUTE max 30 days/request -> 400/30 ≈ 14 chunks
    assert 13 <= len(calls) <= 15
    # deduplication keeps only unique timestamps
    assert len(rows) == len({r[0] for r in rows})


def test_get_historical_chunked_deduplicates_overlap(monkeypatch, smart_mock):
    from data.collector.angel_client import AngelOneClient as C

    client = C(
        {
            "api_key": "k",
            "client_id": "id",
            "password": "pw",
            "totp_secret": "BASE32SECRET",
        }
    )
    client._smart = MagicMock()
    client.authenticate = lambda: True  # type: ignore

    # Two chunks, both return same timestamp
    def fake_get(symbol_token, exchange, interval, from_date, to_date):
        return [["2020-01-01T09:15:00+05:30", 1, 2, 0.5, 1.5, 100]]

    client.get_historical = fake_get  # type: ignore

    start = datetime(2020, 1, 1)
    end = start + timedelta(days=120)
    rows = client.get_historical_chunked("3045", "NSE", "1min", start, end)
    # Even though multiple chunks, only one unique row should be returned
    assert len(rows) == 1


def test_get_historical_retries_on_network_error(monkeypatch, smart_mock):
    from data.collector.angel_client import AngelOneClient as C

    instance = smart_mock.return_value
    # first two raise, last returns success
    sequence = [Exception("net1"), Exception("net2"), {"status": True, "data": []}]

    def side_effect(*args, **kwargs):
        v = sequence.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    instance.getCandleData.side_effect = side_effect

    client = C(
        {
            "api_key": "k",
            "client_id": "id",
            "password": "pw",
            "totp_secret": "BASE32SECRET",
        }
    )
    client.authenticate = lambda: True  # type: ignore

    start = datetime(2020, 1, 1)
    end = start + timedelta(days=1)
    rows = client.get_historical("3045", "NSE", "1min", start, end)
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_fetch_symbol_stores_correct_candle_count(monkeypatch):
    client = MagicMock()
    # two rows from Angel
    client.get_historical_chunked.return_value = [
        ["2025-04-01T09:15:00+05:30", 100, 101, 99, 100.5, 1000],
        ["2025-04-01T09:16:00+05:30", 100.5, 102, 100, 101.5, 2000],
    ]

    db = AsyncMock()
    db.bulk_insert_candles = AsyncMock(return_value=2)

    fetcher = HistoricalFetcher(client=client, db=db, config={})
    count = await fetcher.fetch_symbol(
        symbol="SBIN",
        token=3045,
        exchange="NSE",
        timeframe="1min",
        from_date=datetime(2025, 4, 1),
        to_date=datetime(2025, 4, 2),
    )
    assert count == 2
    assert db.bulk_insert_candles.await_count == 1


@pytest.mark.asyncio
async def test_incremental_update_fetches_from_last_timestamp(monkeypatch):
    # universe with one symbol
    monkeypatch.setattr(
        "data.collector.historical_fetcher.get_universe",
        lambda name: {"SBIN": 3045},
    )
    client = MagicMock()
    client.get_historical_chunked.return_value = []

    db = AsyncMock()
    last_ts = pd.Timestamp("2025-04-01 15:30:00", tz="UTC")
    db.get_latest_timestamp = AsyncMock(return_value=last_ts)
    db.bulk_insert_candles = AsyncMock(return_value=0)

    fetcher = HistoricalFetcher(client=client, db=db, config={})
    out = await fetcher.incremental_update("NIFTY50", ["1min"])
    assert "SBIN" in out
    assert "1min" in out["SBIN"]
