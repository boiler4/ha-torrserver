# Changelog

## 0.4.0-beta.2

- Retry transient `/ffp` failures with bounded 15/30/60/120/300-second backoff
  instead of permanently suppressing the file after one failed probe.
- Create the ffprobe Repair warning only after three consecutive failures and
  expose privacy-safe failure categories and retry state in diagnostics.
- Use the active media-file size, rather than the complete torrent size, for
  multi-file bitrate fallbacks.
- Mark bitrate values explicitly as measured or estimated and make the current
  bitrate sensor use the same source-selection logic as streaming health.
- Bound the in-memory probe cache to 256 entries with a 24-hour lifetime.
- Add opt-in structured debug samples for streaming-health inputs, decisions,
  continuity forecasts, and ffprobe state without media identifiers.

## 0.4.0-beta.1

- Add a read-only streaming-continuity forecast based on measured consecutive
  playable buffer and its rolling trend.
- Expose an estimated time to interruption only while the playable buffer is
  measurably depleting; no ETA is invented for stable or growing buffers.
- Add a configurable interruption-risk horizon and confirmation time, with an
  immediate emergency response at five playable seconds or less.
- Add a native interruption-risk binary sensor and streaming speed-margin
  sensor for dashboards, notifications, and automations.
- Rename the existing playable-buffer entity to Streaming autonomy without
  changing its entity identity or underlying value.
- Keep per-reader session summaries in memory: minimum buffer, average speed,
  time spent Insufficient, duration, and confirmed risk-event count.
- Aggregate simultaneous streams conservatively by exposing the worst forecast,
  minimum ETA, minimum speed margin, and number of streams at risk.

## 0.3.0

- Promote the tested streaming-health implementation to the first public stable
  release of the new monitoring model.
- Add bounded local discovery with manual configuration, authentication, HTTPS,
  and self-signed certificate support.
- Calculate streaming health from consecutive playable cache data, real media
  bitrate when available, rolling speed, and buffer trend.
- Add configurable buffer thresholds, speed margins, averaging window, polling
  interval, and downgrade hysteresis.
- Expose streaming speed, bitrate, playable buffer, health, torrent activity,
  cache, peer, seeder, I/O, diagnostics, and System Health data.
- Add Italian, English, and Russian configuration text, Repairs, issue forms,
  local branding, and native dashboard examples.

## 0.3.0-beta.4

- Display the top `protected` health state as Good, Buono, or Хорошо while
  preserving the raw state for history and automation compatibility.
- Rename the related buffer labels and option descriptions consistently.
- Use blue for the Good state in the native traffic-light dashboard example.

## 0.3.0-beta.3

- Calculate playable buffer only from consecutive `/cache` pieces marked
  `Completed`, stopping at the first missing piece.
- Exclude the current reader piece for a conservative estimate because
  TorrServer does not expose its internal byte offset.
- Treat cache fill as diagnostic occupancy instead of proof that playback data
  is available contiguously.
- Keep zero-speed samples visible even when cache occupancy is high.
- Detect active readers positioned at the beginning of a file.

## 0.3.0-beta.2

- Base streaming health on playable seconds ahead of TorrServer's active reader.
- Replace `healthy`/`warning`/`critical` with `protected`/`stable`/`insufficient`.
- Expose playable buffer seconds and buffer mode/trend diagnostics.
- Read cache capacity, fill, and reader positions from TorrServer's official `/cache` endpoint.
- Add configurable buffer thresholds, speed margins, and downgrade delay.
- Add downgrade hysteresis while preserving immediate emergency detection.

## 0.3.0-beta.1

- Add bounded on-demand local discovery with protected-server detection.
- Add cache-aware per-stream rolling average and configurable averaging window.
- Rename color states to semantic streaming-health states.
- Add a native average streaming speed entity in Mbps.
- Add Italian, English, and Russian configuration text.
- Add System Health, actionable ffprobe Repairs, guided issue forms, and expanded diagnostics/documentation.

## 0.2.0-beta.8

- Add configurable warning and healthy speed margins.
- Expose media bitrate and speed values in Mbps.
