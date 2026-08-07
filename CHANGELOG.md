# Changelog

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
