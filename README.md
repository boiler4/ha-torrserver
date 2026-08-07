# TorrServer for Home Assistant

[English](README.md) · [Italiano](README.it.md) · [Русский](README.ru.md)

[![HACS validation](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml)
[![Tests](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml)

A local, read-only Home Assistant integration for monitoring
[YouROK/TorrServer](https://github.com/YouROK/TorrServer). It does not add,
remove, stop, or modify torrents or TorrServer settings.

> `0.3.0-beta.3` is a test release. Keep it on the beta branch until the new
> discovery and streaming-health logic has been validated.

## Highlights

- One-click local discovery or manual URL configuration.
- HTTP Basic authentication, HTTPS, and self-signed certificate support.
- Download/upload speed, playable buffer in seconds, average streaming speed,
  torrent counts, active playback, peers, seeders, cache and I/O statistics.
- Native streaming-health states: `protected`, `stable`, `insufficient`,
  `measuring`, `idle`, and `unknown`.
- Configurable polling, averaging window, buffer thresholds, speed margins,
  and downgrade delay.
- Optional experimental real bitrate analysis through TorrServer `/ffp`.
- English, Italian, and Russian user interface.
- Privacy-conscious diagnostics, System Health, Repairs, and GitHub Issue Forms.
- Multiple TorrServer instances and multiple simultaneous streams.

## Installation with HACS

Until the repository is included in the default HACS catalog:

1. Open HACS in Home Assistant.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/boiler4/ha-torrserver` as **Integration**.
4. Install **TorrServer**, restart Home Assistant, and add the integration from
   **Settings → Devices & services**.

For beta testing, select the beta release explicitly. No stable release is
created until testing is complete.

## Configuration and discovery

**Search automatically** is recommended. It performs one on-demand scan of
enabled Home Assistant IPv4 networks. It checks only HTTP port 8090 and HTTPS
port 8091, or one custom port selected by the user. Broad networks are limited
to the local `/24` and the total scan is capped at 512 hosts. There is no
periodic background scan.

Discovery never sends usernames or passwords. A server returning 401/403 is
shown as protected; credentials are requested only after that candidate is
selected. Manual URL setup is always available. Do not use Basic authentication
over plain HTTP on an untrusted network. For a trusted HTTPS server with a
self-signed certificate, disable certificate verification explicitly.

## Streaming health logic

Only torrents with a real TorrServer cache reader are treated as streaming.
Other loaded or seeding torrents do not affect the health indicator. With
multiple simultaneous streams, the entity reports the worst active state and
its attributes include a count for every state.

The primary signal is playable data ahead of TorrServer's active reader. It is
calculated from consecutive `/cache` `Pieces` marked `Completed`, stopping at
the first missing piece, and converted to seconds using the detected media
bitrate. The current reader piece is excluded because TorrServer does not expose
the byte offset inside that piece:

- **Protected**: at least 60 playable seconds or a completely loaded file.
- **Stable**: at least 15 playable seconds, or a low buffer whose download can
  sustain and recover playback.
- **Insufficient**: fewer than 15 playable seconds while speed and buffer trend
  cannot recover playback.
- **Measuring**: reader-buffer data is unavailable and speed samples are still
  being collected.

The buffer mode is exposed separately as `full`, `preloading`, `stable`,
`draining`, `recovering`, or `unknown`. `full` means that the consecutive
playable buffer reached the Protected threshold; TorrServer cache occupancy is
diagnostic only and never makes a stream Protected by itself.

Defaults are 15 seconds for low buffer, 60 seconds for Protected, 0% sustainable
speed margin, 10% preloading margin, a 15-second average, and a 15-second
non-emergency downgrade delay. All are configurable. Emergency conditions at
five seconds or no usable sources are applied immediately.

This is an explainable estimate, not a player guarantee. Attributes expose
playable seconds, buffer mode and trend, instantaneous/average Mbps, bitrate,
thresholds, cache occupancy, consecutive completed pieces, samples, peers,
seeders, reason, pending transition, and bitrate source.

## Native traffic-light dashboard

No custom Lovelace card is required. Replace the entity ID if Home Assistant
assigned a different one.

```yaml
type: vertical-stack
cards:
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.torrserver_stream_health
        state: protected
    card:
      type: tile
      entity: sensor.torrserver_stream_health
      name: Streaming health
      icon: mdi:traffic-light
      color: green
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.torrserver_stream_health
        state: stable
    card:
      type: tile
      entity: sensor.torrserver_stream_health
      name: Streaming health
      icon: mdi:traffic-light
      color: amber
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.torrserver_stream_health
        state: insufficient
    card:
      type: tile
      entity: sensor.torrserver_stream_health
      name: Streaming health
      icon: mdi:traffic-light
      color: red
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.torrserver_stream_health
        state_not: protected
      - condition: state
        entity: sensor.torrserver_stream_health
        state_not: stable
      - condition: state
        entity: sensor.torrserver_stream_health
        state_not: insufficient
    card:
      type: tile
      entity: sensor.torrserver_stream_health
      name: Streaming health
      icon: mdi:traffic-light
      color: grey
```

## Experimental real bitrate (`ffprobe`)

This option is off by default. The integration calls TorrServer's existing
read-only `/ffp/<hash>/<file>` endpoint at most once per streamed file, applies
a timeout, and keeps the result only in Home Assistant memory. It does not
install software, write TorrServer settings, or change playback. If analysis
fails, streaming monitoring continues with the size/duration or conservative
resolution fallback and Home Assistant creates a Repair warning.

TorrServer must be able to execute `ffprobe`. In the Linux/Debian layout tested
for this integration, `ffprobe` is provided by the `ffmpeg` package and was made
available beside the TorrServer executable:

```bash
sudo apt update
sudo apt install ffmpeg
command -v ffprobe
sudo ln -s /usr/bin/ffprobe /opt/torrserver/ffprobe
```

Paths vary. Confirm the TorrServer executable directory before creating a link;
do not overwrite an existing file. For Docker, add `ffprobe` to a custom image
and make it visible inside the TorrServer container. On Windows use
`ffprobe.exe`; on macOS an ffmpeg package normally provides `ffprobe`. These are
server-administration steps and are never performed by this integration.

## Entities and units

Default entities include connectivity, download activity, TorrServer working
state, instantaneous download/upload speed, average streaming speed, playable
buffer seconds, torrent counts, streaming health, current torrent, loaded
percentage, and current bitrate. All exposed speeds and bitrates use Mbps.

Lower-level status, peer, cache, byte, chunk, piece, preload, and duration
entities are created disabled by default. Enable only the data you need to avoid
unnecessary recorder history.

## Diagnostics and bug reports

Open the integration menu in **Settings → Devices & services**, download
**Diagnostics**, then use the repository's **New issue** form. Attach the JSON
manually after checking it. Credentials, torrent hashes, names, titles, paths,
posters, and file data are redacted automatically; nothing is uploaded by the
integration. Blank GitHub issues are disabled so reports include version,
language, reproduction steps, expected result, and logs.

System Health shows connection, server version, and ffprobe state. Home
Assistant Repairs is used only for an actionable detected problem such as an
enabled experimental probe that TorrServer cannot execute.

## Development

```bash
python -m pip install -r requirements_test.txt
python -m pytest
python -m ruff check .
```

## License and project relationship

MIT licensed. This is an independent community integration and is not an
official component of TorrServer or Home Assistant.
