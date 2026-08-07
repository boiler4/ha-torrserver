# TorrServer for Home Assistant

[![HACS validation](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml)
[![Tests](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml)

A local, read-only Home Assistant integration for monitoring
[YouROK/TorrServer](https://github.com/YouROK/TorrServer).

The integration uses TorrServer's official HTTP endpoints and presents useful
dashboard entities while keeping lower-level diagnostics disabled by default.
It does not add, remove, stop, or modify torrents.

## Highlights

- Local polling with no cloud dependency.
- UI configuration and reconfiguration.
- Optional HTTP Basic authentication and HTTPS certificate verification.
- Configurable polling interval and download activity threshold.
- Explainable red/yellow/green streaming-quality estimate.
- English and Italian translations.
- Privacy-conscious downloadable diagnostics.
- Multiple TorrServer instances are supported.

## Default entities

- Connectivity, downloading, and working binary sensors.
- Aggregate download and upload speed.
- Total, active, and working torrent counts.
- Streaming quality (`green`, `yellow`, `red`, `idle`, or `unknown`).
- Current torrent title and loaded percentage.

Additional entities for all status counters, peer counters, cache/I/O counters,
chunks, pieces, preload data, duration, and bitrate are created disabled by
default. Enable only the entities you need from the Home Assistant entity
registry to avoid unnecessary recorder history.

`Working` reflects TorrServer's official `Torrent working` state. It is not an
exact count of open HTTP playback connections because TorrServer does not
currently expose that count in its status model.

`Streaming quality` is an estimate, not a guarantee from TorrServer or the
player. It combines connected seeders, active peers, current download speed,
preloaded data, loaded percentage, and the media bitrate when TorrServer makes
it available. When bitrate is unavailable, the estimate uses a conservative
8 Mbps fallback. Its attributes expose the score, reason, inputs, and bitrate
source so automations and dashboards can explain the selected color.

## Installation with HACS

Until the repository is included in the default HACS catalog:

1. Open HACS in Home Assistant.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/boiler4/ha-torrserver` as category **Integration**.
4. Install **TorrServer** and restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → TorrServer**.

For the default local installation, use a URL such as
`http://192.168.1.20:8090`. Credentials may be left empty when TorrServer HTTP
authentication is disabled.

## Manual installation

Copy `custom_components/torrserver` into the `custom_components` directory in
your Home Assistant configuration, restart Home Assistant, and add the
integration from the UI.

## Example dashboard card

Entity IDs can be adjusted in Home Assistant if an existing entity already uses
one of these names.

```yaml
type: entities
title: TorrServer
show_header_toggle: false
entities:
  - entity: binary_sensor.torrserver_connected
  - entity: binary_sensor.torrserver_downloading
  - entity: binary_sensor.torrserver_working
  - entity: sensor.torrserver_stream_health
  - entity: sensor.torrserver_current_torrent
  - entity: sensor.torrserver_current_loaded_percent
  - entity: sensor.torrserver_download_speed
  - entity: sensor.torrserver_upload_speed
  - entity: sensor.torrserver_active_torrents
  - entity: sensor.torrserver_total_torrents
```

## Supported TorrServer fields

The integration understands the official fields returned by `POST /torrents`
with `{"action":"list"}`, including status, loaded and torrent sizes, preload,
download/upload speed, peer and seeder counters, byte and chunk counters,
piece counters, active duration, bitrate, and file statistics. File paths,
hashes, links, posters, and titles are redacted from downloadable diagnostics.

## Development

```bash
python -m pip install -r requirements_test.txt
python -m pytest
python -m ruff check .
```

## License and project relationship

This project is licensed under the MIT License. It is an independent community
integration and is not an official component of TorrServer or Home Assistant.
