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
async def test_client_translates_authentication_error():
    session = MagicMock()
    session.request.return_value = FakeResponse(status=401)
    client = TorrServerApiClient(session, "http://torrserver:8090")

    with pytest.raises(TorrServerAuthenticationError):
        await client.async_get_torrents()
