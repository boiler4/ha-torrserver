"""Second-generation reader-aware stream evaluation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Final

from .stream_health import EMERGENCY_BUFFER_SECONDS, evaluate_stream_health

_MIN_SAMPLES: Final = 3
_MIN_RISK_GRACE_SECONDS: Final = 15.0
_SHORT_WINDOW_SECONDS: Final = 30.0
_TREND_TOLERANCE_SECONDS_PER_MINUTE: Final = 3.0
_CONDITION_SEVERITY: Final = {
    "protected": 0,
    "sustainable": 1,
    "preloading_sustainable": 1,
    "paused": 1,
    "marginal": 2,
    "temporarily_protected": 2,
    "preloading_unsustainable": 2,
    "measuring": 2,
    "unknown": 2,
    "depleting": 3,
    "at_risk": 4,
    "stalled": 5,
}


def _number(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stream_key(torrent: dict[str, Any]) -> str:
    """Return a volatile key; identifiers never leave coordinator memory."""
    for field_name in ("hash", "torrs_hash", "link", "title", "name"):
        if value := torrent.get(field_name):
            return f"{field_name}:{value}"
    return f"object:{id(torrent)}"


def _positions(torrent: dict[str, Any]) -> tuple[int, ...]:
    raw = torrent.get("shadow_reader_positions")
    if not isinstance(raw, (list, tuple)):
        return ()
    values: list[int] = []
    for value in raw:
        if isinstance(value, bool):
            return ()
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return ()
        if parsed < 0:
            return ()
        values.append(parsed)
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class _Sample:
    timestamp: float
    speed: float
    buffer_bytes: float | None
    demand_active: bool


@dataclass(slots=True)
class _Session:
    started_at: float
    last_update: float
    last_positions: tuple[int, ...] = ()
    last_progress_at: float | None = None
    playback_seen: bool = False
    last_phase: str = "unknown"
    samples: deque[_Sample] = field(default_factory=deque)
    confirmed_condition: str = "measuring"
    pending_condition: str | None = None
    pending_since: float | None = None
    risk_since: float | None = None
    risk_recovery_since: float | None = None
    risk_active: bool = False


@dataclass(frozen=True, slots=True)
class ReaderV2Evaluation:
    """One rich assessment plus mappings to the existing indicators."""

    condition: str
    phase: str
    health_state: str
    buffer_mode: str
    forecast_state: str
    risk: bool
    eta_seconds: float | None
    eta_source: str | None
    reason: str
    confidence: str
    attributes: dict[str, Any]


def _window_samples(
    samples: deque[_Sample], now: float, seconds: float
) -> list[_Sample]:
    cutoff = now - seconds
    return [sample for sample in samples if sample.timestamp >= cutoff]


def _demand_speed(samples: list[_Sample]) -> tuple[float | None, int]:
    demanded = [sample.speed for sample in samples if sample.demand_active]
    if not demanded:
        return None, 0
    return sum(demanded) / len(demanded), len(demanded)


def _buffer_trend(samples: list[_Sample]) -> tuple[float | None, int]:
    """Return a least-squares byte/s slope for available buffer samples."""
    values = [sample for sample in samples if sample.buffer_bytes is not None]
    if len(values) < _MIN_SAMPLES:
        return None, len(values)
    origin = values[0].timestamp
    xs = [sample.timestamp - origin for sample in values]
    ys = [float(sample.buffer_bytes) for sample in values]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= 0:
        return None, len(values)
    slope = (
        sum(
            (x_value - mean_x) * (y_value - mean_y)
            for x_value, y_value in zip(xs, ys, strict=True)
        )
        / denominator
    )
    return slope, len(values)


def _phase(
    torrent: dict[str, Any],
    session: _Session,
    *,
    now: float,
    required_speed: float,
    low_buffer_seconds: float,
    buffer_seconds: float | None,
    speed_ratio: float | None,
    pause_grace_seconds: float,
) -> tuple[str, bool]:
    previous_phase = session.last_phase
    positions = _positions(torrent)
    previous = session.last_positions
    seek = False
    progressed = False

    if positions and previous and len(positions) == len(previous):
        deltas = [
            current - old for current, old in zip(positions, previous, strict=True)
        ]
        piece_length = _number(torrent.get("shadow_piece_length"))
        elapsed = max(now - session.last_update, 0.0)
        expected = required_speed * elapsed / piece_length if piece_length > 0 else 0.0
        seek = any(delta < 0 for delta in deltas) or any(
            delta > max(expected * 4, 8) for delta in deltas
        )
        progressed = not seek and any(delta > 0 for delta in deltas)
    elif positions and previous:
        seek = True

    if seek:
        session.playback_seen = False
        session.last_progress_at = None
        session.samples.clear()
        phase = "seek"
    elif progressed:
        session.playback_seen = True
        session.last_progress_at = now
        phase = "playing"
    elif int(_number(torrent.get("stat"))) == 2 and not session.playback_seen:
        phase = "preloading"
    elif not positions:
        phase = "unknown"
    elif not session.playback_seen:
        phase = "preloading"
    else:
        stationary_for = max(now - (session.last_progress_at or now), 0.0)
        stalled = bool(
            stationary_for >= pause_grace_seconds
            and buffer_seconds is not None
            and buffer_seconds <= max(low_buffer_seconds, EMERGENCY_BUFFER_SECONDS)
            and speed_ratio is not None
            and speed_ratio < 1
            and torrent.get("shadow_current_piece_complete") is not True
        )
        if stalled:
            phase = "stalled"
        elif stationary_for >= pause_grace_seconds:
            phase = "paused"
        else:
            phase = "playing"

    reset_history = bool(
        seek
        or phase == "paused"
        or (previous_phase == "paused" and phase == "playing")
    )
    if reset_history:
        session.samples.clear()
        session.pending_condition = None
        session.pending_since = None
        session.confirmed_condition = "paused" if phase == "paused" else "measuring"
    session.last_phase = phase
    session.last_positions = positions
    return phase, reset_history


def _indicator_mapping(condition: str, phase: str) -> tuple[str, str, str]:
    """Map rich shadow semantics onto the existing three enum indicators."""
    if condition == "protected":
        return "protected", "full", "sustainable"
    if condition in {"at_risk", "stalled"}:
        return "insufficient", "draining", "at_risk"
    if condition == "depleting":
        return "insufficient", "draining", "depleting"
    if condition == "preloading_unsustainable":
        return "insufficient", "preloading", "depleting"
    if condition == "temporarily_protected":
        return "stable", "draining", "depleting"
    if condition == "preloading_sustainable":
        return "stable", "preloading", "sustainable"
    if condition == "paused":
        return "stable", "stable", "sustainable"
    if condition in {"sustainable", "marginal"}:
        mode = "recovering" if phase == "playing" else "stable"
        return "stable", mode, "sustainable"
    if condition == "measuring":
        return "measuring", "measuring", "measuring"
    return "unknown", "unknown", "unknown"


def _stabilize_condition(
    session: _Session,
    candidate: str,
    *,
    now: float,
    confirmation_seconds: float,
    emergency: bool,
) -> tuple[str, float | None]:
    current = session.confirmed_condition
    if candidate == current:
        session.pending_condition = None
        session.pending_since = None
        return current, None

    if emergency or candidate == "protected" or confirmation_seconds <= 0:
        session.confirmed_condition = candidate
        session.pending_condition = None
        session.pending_since = None
        return candidate, None

    worsening = _CONDITION_SEVERITY.get(candidate, 2) > _CONDITION_SEVERITY.get(
        current, 2
    )
    delay = confirmation_seconds if worsening else max(confirmation_seconds * 2, 30)
    if session.pending_condition != candidate or session.pending_since is None:
        session.pending_condition = candidate
        session.pending_since = now
        return current, delay
    elapsed = max(now - session.pending_since, 0.0)
    if elapsed >= delay:
        session.confirmed_condition = candidate
        session.pending_condition = None
        session.pending_since = None
        return candidate, None
    return current, delay - elapsed


class ReaderV2StreamTracker:
    """Evaluate the authoritative reader-aware streaming model."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}

    def apply(
        self,
        torrents: tuple[dict[str, Any], ...],
        *,
        now: float,
        window_seconds: float,
        sustainable_margin_percent: float,
        low_buffer_seconds: float,
        risk_horizon_seconds: float,
        confirmation_seconds: float,
        scan_interval_seconds: float,
    ) -> None:
        active_keys: set[str] = set()
        window = max(float(window_seconds), _SHORT_WINDOW_SECONDS)
        margin_ratio = 1 + max(float(sustainable_margin_percent), 0) / 100
        horizon = max(float(risk_horizon_seconds), 1)
        confirmation = max(float(confirmation_seconds), 0)
        pause_grace = max(float(scan_interval_seconds) * 3, 30)

        for torrent in torrents:
            key = _stream_key(torrent)
            active_keys.add(key)
            session = self._sessions.get(key)
            if session is None:
                session = _Session(started_at=now, last_update=now)
                self._sessions[key] = session

            health = evaluate_stream_health(torrent, use_stabilized_state=False)
            buffer_seconds = _optional_number(health.attributes.get("buffer_seconds"))
            required_speed = (
                _number(health.attributes.get("bit_rate_mbps")) * 1_000_000 / 8
            )
            buffer_bytes = _optional_number(torrent.get("buffer_ahead_bytes"))
            cache_full = bool(torrent.get("cache_full"))
            previous_buffer = (
                session.samples[-1].buffer_bytes if session.samples else None
            )
            buffer_not_falling = bool(
                previous_buffer is not None
                and buffer_bytes is not None
                and buffer_bytes >= previous_buffer
            )
            demand_active = bool(
                torrent.get("shadow_remaining_file_cached") is not True
                and not (cache_full and buffer_not_falling)
            )
            session.samples.append(
                _Sample(
                    timestamp=now,
                    speed=_number(torrent.get("download_speed")),
                    buffer_bytes=buffer_bytes,
                    demand_active=demand_active,
                )
            )
            cutoff = now - window
            while session.samples and session.samples[0].timestamp < cutoff:
                session.samples.popleft()

            long_samples = _window_samples(session.samples, now, window)
            short_samples = _window_samples(
                session.samples, now, min(_SHORT_WINDOW_SECONDS, window)
            )
            long_speed, long_count = _demand_speed(long_samples)
            short_speed, short_count = _demand_speed(short_samples)
            trend_bytes, trend_count = _buffer_trend(long_samples)
            long_ratio = (
                long_speed / required_speed
                if long_speed is not None and required_speed > 0
                else None
            )
            short_ratio = (
                short_speed / required_speed
                if short_speed is not None and required_speed > 0
                else None
            )
            trend_per_minute = (
                trend_bytes / required_speed * 60
                if trend_bytes is not None and required_speed > 0
                else None
            )

            phase, reset_history = _phase(
                torrent,
                session,
                now=now,
                required_speed=required_speed,
                low_buffer_seconds=low_buffer_seconds,
                buffer_seconds=buffer_seconds,
                speed_ratio=long_ratio,
                pause_grace_seconds=pause_grace,
            )
            if reset_history:
                long_count = short_count = trend_count = 0
                long_ratio = short_ratio = trend_per_minute = None

            span = (
                long_samples[-1].timestamp - long_samples[0].timestamp
                if len(long_samples) >= 2
                else 0
            )
            short_span = (
                short_samples[-1].timestamp - short_samples[0].timestamp
                if len(short_samples) >= 2
                else 0
            )
            enough_speed = long_count >= _MIN_SAMPLES and span >= min(window / 2, 30)
            enough_short = short_count >= _MIN_SAMPLES and short_span >= 20
            enough_trend = trend_count >= _MIN_SAMPLES and span >= min(window / 2, 30)
            risk_grace_seconds = max(
                _MIN_RISK_GRACE_SECONDS, float(scan_interval_seconds) * 2
            )
            risk_ready = bool(
                len(session.samples) >= _MIN_SAMPLES and span >= risk_grace_seconds
            )
            remaining_cached = torrent.get("shadow_remaining_file_cached") is True
            fully_loaded = bool(
                _number(torrent.get("torrent_size")) > 0
                and _number(torrent.get("loaded_size"))
                >= _number(torrent.get("torrent_size"))
            )

            eta: float | None = None
            eta_source: str | None = None
            if (
                not (remaining_cached or fully_loaded)
                and buffer_seconds is not None
                and phase not in {"paused", "seek", "unknown"}
            ):
                if (
                    phase == "playing"
                    and enough_trend
                    and trend_per_minute is not None
                    and trend_per_minute < -_TREND_TOLERANCE_SECONDS_PER_MINUTE
                ):
                    eta = buffer_seconds / (-trend_per_minute / 60)
                    eta_source = "measured_buffer_trend"
                elif enough_speed and long_ratio is not None and long_ratio < 1:
                    eta = buffer_seconds / max(1 - long_ratio, 0.001)
                    eta_source = (
                        "projected_if_playback_started"
                        if phase in {"preloading", "paused"}
                        else "throughput_deficit"
                    )
                if (
                    phase == "playing"
                    and eta_source != "measured_buffer_trend"
                    and enough_short
                    and short_ratio is not None
                    and short_ratio < 0.75
                    and (long_ratio is None or short_ratio <= long_ratio - 0.2)
                ):
                    short_eta = buffer_seconds / max(1 - short_ratio, 0.001)
                    if eta is None or short_eta < eta:
                        eta = short_eta
                        eta_source = "short_throughput_collapse"

            emergency = bool(
                not (remaining_cached or fully_loaded)
                and (
                    phase == "stalled"
                    or (
                        phase == "playing"
                        and risk_ready
                        and buffer_seconds is not None
                        and buffer_seconds <= EMERGENCY_BUFFER_SECONDS
                    )
                )
            )
            candidate_risk = bool(
                phase in {"playing", "stalled"}
                and (risk_ready or phase == "stalled")
                and (emergency or (eta is not None and eta <= horizon))
            )
            risk_pending: float | None = None
            risk_suppressed = bool(
                phase in {"preloading", "paused", "seek", "unknown"}
                or (phase == "playing" and not risk_ready)
            )
            if risk_suppressed:
                session.risk_since = None
                session.risk_recovery_since = None
                session.risk_active = False
                risk = False
            elif candidate_risk:
                session.risk_recovery_since = None
                if emergency or confirmation == 0:
                    risk = True
                    session.risk_since = session.risk_since or now
                elif session.risk_active:
                    risk = True
                elif session.risk_since is None:
                    session.risk_since = now
                    risk = False
                    risk_pending = confirmation
                else:
                    elapsed = max(now - session.risk_since, 0.0)
                    risk = elapsed >= confirmation
                    if not risk:
                        risk_pending = confirmation - elapsed
            else:
                session.risk_since = None
                if session.risk_active:
                    recovery_delay = max(confirmation * 2, 30)
                    if session.risk_recovery_since is None:
                        session.risk_recovery_since = now
                        risk = True
                        risk_pending = recovery_delay
                    else:
                        elapsed = max(now - session.risk_recovery_since, 0.0)
                        risk = elapsed < recovery_delay
                        if risk:
                            risk_pending = recovery_delay - elapsed
                        else:
                            session.risk_recovery_since = None
                else:
                    session.risk_recovery_since = None
                    risk = False
            session.risk_active = risk

            if remaining_cached or fully_loaded:
                candidate = "protected"
                reason = (
                    "remaining_file_cached"
                    if remaining_cached
                    else "torrent_fully_loaded"
                )
                confidence = "high"
            elif phase == "seek":
                candidate, reason, confidence = "measuring", "seek_detected", "low"
            elif phase == "unknown" or required_speed <= 0:
                candidate, reason, confidence = (
                    "unknown",
                    "insufficient_reader_or_bitrate_data",
                    "low",
                )
            elif phase == "paused":
                candidate, reason, confidence = (
                    "paused",
                    "reader_not_consuming",
                    "medium",
                )
            elif phase == "stalled":
                candidate, reason, confidence = (
                    "stalled",
                    "reader_stalled_with_low_buffer",
                    "high",
                )
            elif risk or candidate_risk:
                candidate, reason, confidence = (
                    "at_risk",
                    "projected_interruption_within_horizon",
                    "high" if eta_source == "measured_buffer_trend" else "medium",
                )
            elif not enough_speed:
                candidate, reason, confidence = (
                    "measuring",
                    "collecting_shadow_samples",
                    "low",
                )
            elif long_ratio is not None and long_ratio >= margin_ratio:
                candidate = (
                    "preloading_sustainable" if phase == "preloading" else "sustainable"
                )
                reason = "throughput_has_configured_margin"
                confidence = (
                    "medium" if health.attributes.get("bit_rate_estimated") else "high"
                )
            elif long_ratio is not None and long_ratio >= 1:
                candidate, reason, confidence = (
                    "marginal",
                    "throughput_without_safety_margin",
                    "medium",
                )
            elif phase == "preloading":
                candidate, reason, confidence = (
                    "preloading_unsustainable",
                    "preload_throughput_below_bitrate",
                    "medium",
                )
            elif eta_source == "measured_buffer_trend":
                candidate, reason, confidence = (
                    "depleting",
                    "measured_buffer_depletion",
                    "high",
                )
            else:
                candidate, reason, confidence = (
                    "temporarily_protected",
                    "buffer_masks_throughput_deficit",
                    "medium",
                )

            confirmed, pending = _stabilize_condition(
                session,
                candidate,
                now=now,
                confirmation_seconds=confirmation,
                emergency=emergency,
            )
            health_state, buffer_mode, forecast_state = _indicator_mapping(
                confirmed, phase
            )
            confirmed_reason = (
                reason if confirmed == candidate else "transition_pending"
            )
            torrent.update(
                {
                    "shadow_condition": confirmed,
                    "shadow_candidate_condition": candidate,
                    "shadow_phase": phase,
                    "shadow_health_state": health_state,
                    "shadow_buffer_mode": buffer_mode,
                    "shadow_forecast_state": forecast_state,
                    "shadow_interruption_risk": risk,
                    "shadow_candidate_risk": candidate_risk,
                    "shadow_risk_transition_pending_seconds": round(risk_pending, 1)
                    if risk_pending is not None
                    else None,
                    "shadow_eta_seconds": round(eta, 1) if eta is not None else None,
                    "shadow_eta_source": eta_source,
                    "shadow_reason": confirmed_reason,
                    "shadow_candidate_reason": reason,
                    "shadow_confidence": confidence,
                    "shadow_transition_pending_seconds": round(pending, 1)
                    if pending is not None
                    else None,
                    "shadow_long_speed_ratio": round(long_ratio, 3)
                    if long_ratio is not None
                    else None,
                    "shadow_short_speed_ratio": round(short_ratio, 3)
                    if short_ratio is not None
                    else None,
                    "shadow_buffer_trend_seconds_per_minute": round(trend_per_minute, 2)
                    if trend_per_minute is not None
                    else None,
                    "shadow_long_sample_count": long_count,
                    "shadow_short_sample_count": short_count,
                    "shadow_buffer_sample_count": trend_count,
                    "shadow_window_seconds": window,
                    "shadow_sustainable_margin_percent": max(
                        float(sustainable_margin_percent), 0
                    ),
                    "shadow_risk_horizon_seconds": horizon,
                    "shadow_session_seconds": round(
                        max(now - session.started_at, 0), 1
                    ),
                }
            )
            session.last_update = now

        for stale_key in set(self._sessions) - active_keys:
            self._sessions.pop(stale_key, None)
