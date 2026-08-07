"""Safe, credential-free local discovery for TorrServer."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address, ip_network
from typing import Any

from aiohttp import ClientError, ClientSession

_VERSION_PATTERN = re.compile(
    r"TorrServer\s+MatriX[.\s-]*([0-9][A-Za-z0-9._-]*)", re.IGNORECASE
)
DEFAULT_DISCOVERY_PORTS = (("http", 8090), ("https", 8091))
MAX_DISCOVERY_HOSTS = 512


@dataclass(frozen=True, slots=True)
class DiscoveredTorrServer:
    """One candidate returned without ever sending user credentials."""

    url: str
    version: str | None
    auth_required: bool


def candidate_urls_from_adapters(
    adapters: Iterable[Mapping[str, Any]],
    *,
    custom_port: int | None = None,
    max_hosts: int = MAX_DISCOVERY_HOSTS,
) -> tuple[str, ...]:
    """Build bounded candidates from enabled Home Assistant IPv4 adapters."""
    hosts: set[IPv4Address] = set()
    for adapter in adapters:
        if not adapter.get("enabled", True):
            continue
        ipv4_entries = adapter.get("ipv4")
        if not isinstance(ipv4_entries, list):
            continue
        for entry in ipv4_entries:
            if not isinstance(entry, Mapping):
                continue
            try:
                address = ip_address(str(entry["address"]))
                prefix = int(entry.get("network_prefix", 24))
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not isinstance(address, IPv4Address)
                or address.is_loopback
                or address.is_link_local
                or address.is_unspecified
            ):
                continue
            network = ip_network(f"{address}/{prefix}", strict=False)
            # A broad LAN is intentionally limited to the local /24. Discovery is
            # on-demand and must never turn Home Assistant into a large scanner.
            if network.prefixlen < 24:
                network = ip_network(f"{address}/24", strict=False)
            for host in network.hosts():
                hosts.add(host)
                if len(hosts) >= max_hosts:
                    break
            if len(hosts) >= max_hosts:
                break
        if len(hosts) >= max_hosts:
            break

    ports = (
        (("http", custom_port), ("https", custom_port))
        if custom_port is not None
        else DEFAULT_DISCOVERY_PORTS
    )
    return tuple(
        f"{scheme}://{host}:{port}" for host in sorted(hosts) for scheme, port in ports
    )


async def async_discover_torrservers(
    session: ClientSession,
    urls: Iterable[str],
    *,
    timeout: float = 0.6,
    concurrency: int = 64,
) -> tuple[DiscoveredTorrServer, ...]:
    """Probe candidates concurrently without authentication or state changes."""
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _probe(url: str) -> DiscoveredTorrServer | None:
        try:
            async with (
                semaphore,
                asyncio.timeout(timeout),
                session.get(url, ssl=False, allow_redirects=True) as response,
            ):
                if response.status in {401, 403}:
                    return DiscoveredTorrServer(url, None, True)
                if response.status >= 400:
                    return None
                body = await response.text(errors="ignore")
        except (TimeoutError, ClientError, UnicodeError):
            return None
        match = _VERSION_PATTERN.search(body)
        if not match:
            return None
        return DiscoveredTorrServer(url, f"MatriX.{match.group(1)}", False)

    results = await asyncio.gather(*(_probe(url) for url in urls))
    return tuple(sorted((item for item in results if item), key=lambda item: item.url))
