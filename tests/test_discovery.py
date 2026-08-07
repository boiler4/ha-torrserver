"""Tests for bounded, credential-free TorrServer discovery."""

from custom_components.torrserver.discovery import (
    async_discover_torrservers,
    candidate_urls_from_adapters,
)


def test_candidates_use_only_enabled_ipv4_networks_and_default_ports():
    urls = candidate_urls_from_adapters(
        [
            {
                "enabled": True,
                "ipv4": [{"address": "192.168.10.17", "network_prefix": 30}],
            },
            {
                "enabled": False,
                "ipv4": [{"address": "10.0.0.2", "network_prefix": 24}],
            },
        ]
    )

    assert urls == (
        "http://192.168.10.17:8090",
        "https://192.168.10.17:8091",
        "http://192.168.10.18:8090",
        "https://192.168.10.18:8091",
    )
    assert all("10.0.0" not in url for url in urls)


def test_custom_port_does_not_expand_to_other_ports():
    urls = candidate_urls_from_adapters(
        [
            {
                "enabled": True,
                "ipv4": [{"address": "192.168.1.2", "network_prefix": 32}],
            }
        ],
        custom_port=1234,
    )

    assert urls == (
        "http://192.168.1.2:1234",
        "https://192.168.1.2:1234",
    )


class _Response:
    def __init__(self, status, body=""):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self, **_kwargs):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


async def test_discovery_accepts_torrserver_and_locked_candidate_without_auth():
    session = _Session(
        {
            "http://open:8090/echo": _Response(200, "MatriX.136"),
            "http://locked:8090/echo": _Response(401),
            "http://other:8090/echo": _Response(200, "not TorrServer"),
        }
    )

    results = await async_discover_torrservers(
        session,
        ("http://open:8090", "http://locked:8090", "http://other:8090"),
    )

    assert [(item.url, item.version, item.auth_required) for item in results] == [
        ("http://locked:8090", None, True),
        ("http://open:8090", "MatriX.136", False),
    ]
    assert all("auth" not in kwargs for _, kwargs in session.calls)
