# TorrServer for Home Assistant

[English](README.md) · [Italiano](README.it.md) · [Русский](README.ru.md)

[![HACS validation](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/hassfest.yml)
[![Tests](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml/badge.svg)](https://github.com/boiler4/ha-torrserver/actions/workflows/tests.yml)

A local, read-only Home Assistant integration for monitoring
[YouROK/TorrServer](https://github.com/YouROK/TorrServer). It does not add,
remove, stop, or modify torrents or TorrServer settings.

The current stable release is `0.3.0`. `0.4.0-beta.4` is an optional
pre-release for testing streaming autonomy and interruption forecasting.

## Highlights

- One-click local discovery or manual URL configuration.
- HTTP Basic authentication, HTTPS, and self-signed certificate support.
- Download/upload speed, playable buffer in seconds, average streaming speed,
  torrent counts, active playback, peers, seeders, cache and I/O statistics.
- Native streaming-health states: `protected` (Good), `stable`, `insufficient`,
  `measuring`, `idle`, and `unknown`.
- Configurable polling, averaging window, buffer thresholds, speed margins,
  and downgrade delay.
- Optional experimental real bitrate analysis through TorrServer `/ffp`.
- English, Italian, and Russian user interface.
- Privacy-conscious diagnostics, System Health, Repairs, and GitHub Issue Forms.
- Multiple TorrServer instances and multiple simultaneous streams.
- Measured streaming autonomy, speed margin, interruption ETA, confirmed risk,
  and an in-memory playback-session summary.

## Installation with HACS

TorrServer is included in the default HACS community catalog.

1. Open HACS and search for **TorrServer**.
2. Download the integration, restart Home Assistant, then add it from
   **Settings → Devices & services**.
3. HACS selects the stable release by default. To test this beta, enable
   prereleases in the version selector and explicitly choose `v0.4.0-beta.4`.

If the catalog has not refreshed yet, add `https://github.com/boiler4/ha-torrserver`
as a custom **Integration** repository. HACS inclusion is not inclusion in
Home Assistant Core.

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

Beta.4 uses **reader-v2** as the authoritative model by default. It combines
TorrServer's active reader position, consecutive completed cache pieces, measured
reader demand, rolling download speed and buffer trend. A torrent merely seeding
without an active cache reader does not degrade streaming health.

- A completely cached remaining file stays **Good** (`protected`) even if
  downloads stop. Cache occupancy alone is not proof of playable data.
- Startup and resume collect fresh samples before risk is allowed. A detected
  seek or confirmed pause clears stale risk and ETA; resume starts measuring
  again rather than reusing old throughput samples.
- Sustained throughput deficits and projected buffer exhaustion can still raise
  interruption risk after the initial measuring phase.
- Existing health entity IDs and raw states remain compatible. Attributes expose
  `model`, `phase`, `condition`, buffer evidence, confidence and decision reason.
- The reader-v2 option is authoritative, not a diagnostic-only shadow. Disabling
  it selects the legacy model; existing stored `stream_shadow_*` option keys are
  preserved for upgrade compatibility.

Reader phases are inferred from server activity: the integration does not read
the player's actual pause button or buffering screen. The forecast remains an
explainable estimate, not a playback guarantee. Startup alerts are still under
field evaluation in this prerelease.

## Streaming autonomy and interruption forecast (beta)

**Streaming autonomy** is the existing consecutive playable buffer expressed in
seconds. The continuity forecast uses its rolling trend as the primary signal:

- **Sustainable**: the measured playable buffer is stable or growing;
- **Buffer depleting**: the buffer is shrinking and a time-to-empty estimate can
  be calculated;
- **Interruption risk**: the estimated time-to-empty is inside the configured
  risk horizon and remains there for the confirmation time;
- **Measuring/Unknown**: there is not enough real reader-buffer information.

No ETA is exposed while the buffer is stable or growing. The default risk
horizon is 60 seconds and confirmation time is 15 seconds; both are configurable.
After startup/resume settling, five playable seconds or less can bypass
the normal confirmation delay. With simultaneous
streams the worst forecast and minimum ETA are exposed.

The `Streaming interruption risk` binary sensor can trigger a native Home
Assistant notification or automation. Session attributes include minimum
buffer, average speed, seconds spent Insufficient, duration, and risk events.
They live only in Home Assistant memory and reset when playback ends or Home
Assistant restarts. The forecast estimates TorrServer-side risk; it cannot prove
that a separate player actually displayed a buffering screen.

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
      color: blue
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
read-only `/ffp/<hash>/<file>` endpoint after the initial buffer is available,
applies a timeout, and keeps successful results only in bounded Home Assistant
memory. Transient failures retry after 15, 30, 60, 120, and at most 300 seconds;
a Repair warning appears only after three consecutive failures. Failure types
and the next retry are available in diagnostics without torrent identifiers.

Measured values expose `bit_rate_source` and `estimated: false`. While probing
is pending or unavailable, monitoring continues with an explicitly marked
size/duration or conservative resolution estimate. For multi-file torrents the
fallback uses the active media file rather than the complete torrent size. The
integration does not install software, write TorrServer settings, or change
playback.

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

### Optional stream-health observation log

For a short diagnostic observation window, enable debug logging only for this
integration:

```yaml
logger:
  logs:
    custom_components.torrserver: debug
```

While a real reader is active, one machine-readable `stream_health_sample` JSON
object is emitted per coordinator poll, followed by a `stream_health_idle`
marker when playback ends. Samples include health and forecast decisions,
playable buffer and trend, speed margin, bitrate provenance, cache/peer/session
metrics, and ffprobe retry state. They never include torrent titles, hashes,
links, file paths, server URLs, addresses, or credentials. Disable the override
after collecting enough sessions to avoid unnecessary long-term log volume.

## Entities and units

Default entities include connectivity, download activity, TorrServer working
state, instantaneous download/upload speed, average streaming speed, streaming
autonomy, continuity forecast, interruption ETA and risk, speed margin, torrent
counts, streaming health, current torrent, loaded percentage, and current
bitrate. All exposed speeds and bitrates use Mbps.

Lower-level status, peer, cache, byte, chunk, piece, preload, duration, and
session-summary entities are created disabled by default. Enable only the data
you need to avoid unnecessary recorder history.

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
