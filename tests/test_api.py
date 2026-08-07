"""Tests for the standalone TorrServer API client and data model."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.torrserver.api import (
    TorrServerApiClient,
    TorrServerAuthenticationError,
    TorrServerData,
    normalize_url,
)


class FakeResponse:
    """Minimal aiohttp response context manager."""

    def __init__(self, *, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, content_type=None):
        return self._json_data

    async def text(self):
        return self._text_data


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("192.168.1.10:8090", "http://192.168.1.10:8090"),
        ("http://server:8090/", "http://server:8090"),
        ("https://server.example/base/", "https://server.example/base"),
    ],
)
def test_normalize_url(source, expected):
    assert normalize_url(source) == expected


@pytest.mark.parametrize("source", ["", "ftp://server", "http:///missing-host"])
def test_normalize_url_rejects_invalid_input(source):
    with pytest.raises(ValueError):
        normalize_url(source)


def test_data_model_selects_fastest_active_torrent():
    data = TorrServerData(
        torrents=(
            {"title": "Saved", "stat": 5, "download_speed": 100000},
            {"title": "Slow", "stat": 3, "download_speed": 100},
            {"title": "Fast", "stat": 3, "download_speed": 250},
        ),
        version="MatriX.137",
    )

    assert len(data.active_torrents) == 2
    assert data.current_torrent["title"] == "Fast"
    assert data.active_sum("download_speed") == 350
    assert data.count_state(5) == 1


def test_data_model_prefers_connected_torrent_when_speeds_are_equal():
    data = TorrServerData(
        torrents=(
            {"title": "Idle", "stat": 3, "timestamp": 2},
            {
                "title": "Streaming",
                "stat": 3,
                "connected_seeders": 3,
                "active_peers": 5,
                "timestamp": 1,
            },
        )
    )

    assert data.current_torrent["title"] == "Streaming"


def test_data_model_excludes_seed_only_torrent_from_streaming():
    data = TorrServerData(
        torrents=(
            {
                "title": "Playing",
                "stat": 3,
                "cache_stats_available": True,
                "reader_count": 1,
                "streaming_reader_count": 1,
            },
            {
                "title": "Seeding",
                "stat": 3,
                "cache_stats_available": True,
                "reader_count": 30,
                "streaming_reader_count": 0,
                "upload_speed": 500_000,
            },
        )
    )

    assert [torrent["title"] for torrent in data.streaming_torrents] == ["Playing"]


def test_data_model_keeps_stream_while_its_reader_starts_downloading():
    data = TorrServerData(
        torrents=(
            {
                "title": "Starting",
                "stat": 3,
                "cache_stats_available": True,
                "reader_count": 1,
                "streaming_reader_count": 0,
                "download_speed": 4096,
            },
        )
    )

    assert len(data.streaming_torrents) == 1


def test_data_model_falls_back_when_cache_api_is_unavailable():
    data = TorrServerData(torrents=({"title": "Legacy", "stat": 3},))

    assert data.streaming_torrents == data.active_torrents


@pytest.mark.asyncio
async def test_client_reads_torrents_and_version():
    session = MagicMock()
    session.request.side_effect = [
        FakeResponse(json_data=[{"title": "Example", "stat": 3}]),
        FakeResponse(text_data="<h6>TorrServer MatriX.137</h6>"),
    ]
    client = TorrServerApiClient(session, "http://torrserver:8090")

    data = await client.async_get_data()

    assert len(data.torrents) == 1
    assert data.version == "MatriX.137"
    assert session.request.call_count == 2


@pytest.mark.asyncio
async def test_client_enriches_torrent_with_reader_activity():
    session = MagicMock()
    session.request.side_effect = [
        FakeResponse(json_data=[{"title": "Example", "stat": 3, "hash": "abc"}]),
        FakeResponse(
            json_data={
                "Readers": [
                    {"Start": 0, "End": 32, "Reader": 0},
                    {"Start": 100, "End": 200, "Reader": 120},
                ]
            }
        ),
        FakeResponse(text_data="<h6>TorrServer MatriX.137</h6>"),
    ]
    client = TorrServerApiClient(session, "http://torrserver:8090")

    data = await client.async_get_data()

    assert data.torrents[0]["cache_stats_available"] is True
    assert data.torrents[0]["reader_count"] == 2
    assert data.torrents[0]["streaming_reader_count"] == 1
    assert session.request.call_count == 3


@pytest.mark.asyncio
async def test_client_translates_authentication_error():
    session = MagicMock()
    session.request.return_value = FakeResponse(status=401)
    client = TorrServerApiClient(session, "http://torrserver:8090")

    with pytest.raises(TorrServerAuthenticationError):
        await client.async_get_torrents()
