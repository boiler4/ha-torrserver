"""Read-only interruption forecast and in-memory streaming session summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .stream_health import EMERGENCY_BUFFER_SECONDS, evaluate_stream_health

STREAM_FORECAST_OPTIONS: Final = [
    "idle",
    "sustainable",
    "depleting",
    "at_risk",
    "measuring",
    "unknown",
]
STREAM_FORECAST_ICONS: Final = {
    "idle": "mdi:minus-circle-outline",
    "sustainable": "mdi:play-circle-outline",
    "depleting": "mdi:timer-sand",
    "at_risk": "mdi:progress-alert",
    "measuring": "mdi:chart-timeline-variant-shimmer",
    "unknown": "mdi:help-circle-outline",
}
_STATE_PRIORITY: Final = {
    "sustainable": 0,
    "unknown": 1,
    "measuring": 1,
    "depleting": 2,
    "at_risk": 3,
}
_MIN_DRAIN_RATE_SECONDS_PER_MINUTE: Final = 3.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stream_key(torrent: dict[str, Any]) -> str:
    """Return an internal session key that is never exposed to Home Assistant."""
    for field in ("hash", "torrs_hash", "link", "title", "name"):
        if value := torrent.get(field):
            return f"{field}:{value}"
    return f"object:{id(torrent)}"


@dataclass(frozen=True, slots=True)
class StreamForecast:
    """One explainable interruption forecast."""

    state: str
    risk: bool
    eta_seconds: float | None
    attributes: dict[str, Any]


@dataclass(slots=True)
class _StreamSession:
    """Volatile statistics for one continuous TorrServer reader session."""

    started_at: float
    last_update: float
    last_health_state: str | None = None
    minimum_buffer_seconds: float | None = None
    speed_total: float = 0.0
    speed_samples: int = 0
    insufficient_seconds: float = 0.0
    risk_events: int = 0
    risk_since: float | None = None
    risk_active: bool = False


def stream_forecast_icon(state: str) -> str:
    """Return the icon associated with a forecast state."""
    return STREAM_FORECAST_ICONS.get(state, "mdi:progress-question")


def evaluate_stream_forecast(
    torrent: dict[str, Any] | None,
    *,
    risk_horizon_seconds: float = 60,
    stable_margin_percent: float = 0,
    preload_margin_percent: float = 10,
    low_buffer_seconds: float = 15,
    protected_buffer_seconds: float = 60,
) -> StreamForecast:
    """Predict interruption only when measured playable buffer is depleting."""
    if torrent is None:
        return StreamForecast(
            state="idle",
            risk=False,
            eta_seconds=None,
            attributes={"reason": "no_active_stream"},
        )

    health = evaluate_stream_health(
        torrent,
        stable_margin_percent=stable_margin_percent,
        preload_margin_percent=preload_margin_percent,
        low_buffer_seconds=low_buffer_seconds,
        protected_buffer_seconds=protected_buffer_seconds,
    )
    buffer_seconds = _optional_float(health.attributes.get("buffer_seconds"))
    trend_per_minute = _optional_float(
        health.attributes.get("buffer_trend_seconds_per_minute")
    )
    horizon = max(float(risk_horizon_seconds), 1.0)
    eta_seconds: float | None = None
    if (
        buffer_seconds is not None
        and trend_per_minute is not None
        and trend_per_minute < -_MIN_DRAIN_RATE_SECONDS_PER_MINUTE
    ):
        eta_seconds = buffer_seconds / (-trend_per_minute / 60)

    candidate_risk = bool(
        (eta_seconds is not None and eta_seconds <= horizon)
        or (
            health.state == "insufficient"
            and buffer_seconds is not None
            and buffer_seconds < low_buffer_seconds
        )
    )
    confirmed_risk = bool(torrent.get("stream_interruption_risk", False))

    if confirmed_risk:
        state = "at_risk"
        reason = "confirmed_interruption_risk"
    elif eta_seconds is not None:
        state = "depleting"
        reason = "playable_buffer_depleting"
    elif buffer_seconds is None:
        state = (
            "measuring"
            if health.attributes.get("speed_source") == "measuring"
            else "unknown"
        )
        reason = "playable_buffer_unavailable"
    elif trend_per_minute is None:
        state = "measuring"
        reason = "collecting_buffer_samples"
    else:
        state = "sustainable"
        reason = "buffer_not_depleting"

    stored_eta = _optional_float(torrent.get("stream_interruption_eta_seconds"))
    if stored_eta is not None:
        eta_seconds = stored_eta

    attributes = {
        "reason": reason,
        "estimated": True,
        "candidate_risk": candidate_risk,
        "risk_horizon_seconds": horizon,
        "playable_buffer_seconds": buffer_seconds,
        "buffer_trend_seconds_per_minute": trend_per_minute,
        "speed_margin_percent": health.attributes.get("speed_margin_percent"),
        "average_download_speed_mbps": health.attributes.get(
            "average_download_speed_mbps"
        ),
        "bit_rate_mbps": health.attributes.get("bit_rate_mbps"),
        "bit_rate_source": health.attributes.get("bit_rate_source"),
        "health_state": health.state,
        "confirmation_pending_seconds": torrent.get(
            "stream_risk_confirmation_pending_seconds"
        ),
        "session_duration_seconds": torrent.get("stream_session_duration_seconds"),
        "session_minimum_buffer_seconds": torrent.get(
            "stream_session_minimum_buffer_seconds"
        ),
        "session_average_speed_mbps": torrent.get(
            "stream_session_average_speed_mbps"
        ),
        "session_insufficient_seconds": torrent.get(
            "stream_session_insufficient_seconds"
        ),
        "session_risk_events": torrent.get("stream_session_risk_events"),
    }
    return StreamForecast(
        state=state,
        risk=confirmed_risk,
        eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
        attributes=attributes,
    )


class StreamForecastTracker:
    """Confirm risks and keep summaries for active reader sessions in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, _StreamSession] = {}

    def apply(
        self,
        torrents: tuple[dict[str, Any], ...],
        *,
        now: float,
        risk_horizon_seconds: float,
        confirmation_seconds: float,
        stable_margin_percent: float,
        preload_margin_percent: float,
        low_buffer_seconds: float,
        protected_buffer_seconds: float,
    ) -> None:
        """Annotate streams with a confirmed forecast and session statistics."""
        active_keys: set[str] = set()
        confirmation = max(float(confirmation_seconds), 0.0)

        for torrent in torrents:
            key = _stream_key(torrent)
            active_keys.add(key)
            session = self._sessions.get(key)
            if session is None:
                session = _StreamSession(started_at=now, last_update=now)
                self._sessions[key] = session

            elapsed = max(now - session.last_update, 0.0)
            if session.last_health_state == "insufficient":
                session.insufficient_seconds += elapsed

            forecast = evaluate_stream_forecast(
                torrent,
                risk_horizon_seconds=risk_horizon_seconds,
                stable_margin_percent=stable_margin_percent,
                preload_margin_percent=preload_margin_percent,
                low_buffer_seconds=low_buffer_seconds,
                protected_buffer_seconds=protected_buffer_seconds,
            )
            buffer_seconds = _optional_float(
                forecast.attributes.get("playable_buffer_seconds")
            )
            if buffer_seconds is not None:
                session.minimum_buffer_seconds = (
                    buffer_seconds
                    if session.minimum_buffer_seconds is None
                    else min(session.minimum_buffer_seconds, buffer_seconds)
                )

            speed = _optional_float(torrent.get("average_download_speed"))
            if speed is None:
                speed = _optional_float(torrent.get("download_speed"))
            if speed is not None:
                session.speed_total += max(speed, 0.0)
                session.speed_samples += 1

            emergency = bool(
                buffer_seconds is not None
                and buffer_seconds <= EMERGENCY_BUFFER_SECONDS
            ) or str(torrent.get("stream_health_candidate_reason")) == "no_sources"
            pending_seconds: float | None = None
            if forecast.attributes["candidate_risk"]:
                if emergency or confirmation == 0:
                    risk_active = True
                    session.risk_since = session.risk_since or now
                elif session.risk_since is None:
                    session.risk_since = now
                    risk_active = False
                    pending_seconds = confirmation
                else:
                    risk_elapsed = max(now - session.risk_since, 0.0)
                    risk_active = risk_elapsed >= confirmation
                    if not risk_active:
                        pending_seconds = confirmation - risk_elapsed
            else:
                risk_active = False
                session.risk_since = None

            if risk_active and not session.risk_active:
                session.risk_events += 1

            session.risk_active = risk_active
            session.last_health_state = str(
                torrent.get("stabilized_stream_health_state") or "unknown"
            )
            session.last_update = now

            torrent["stream_interruption_risk"] = risk_active
            torrent["stream_interruption_eta_seconds"] = forecast.eta_seconds
            torrent["stream_speed_margin_percent"] = forecast.attributes.get(
                "speed_margin_percent"
            )
            torrent["stream_risk_confirmation_pending_seconds"] = (
                round(pending_seconds, 1) if pending_seconds is not None else None
            )
            torrent["stream_session_duration_seconds"] = round(
                max(now - session.started_at, 0.0), 1
            )
            torrent["stream_session_minimum_buffer_seconds"] = (
                round(session.minimum_buffer_seconds, 1)
                if session.minimum_buffer_seconds is not None
                else None
            )
            torrent["stream_session_average_speed_mbps"] = (
                round(
                    (session.speed_total / session.speed_samples) * 8 / 1_000_000,
                    2,
                )
                if session.speed_samples
                else None
            )
            torrent["stream_session_insufficient_seconds"] = round(
                session.insufficient_seconds, 1
            )
            torrent["stream_session_risk_events"] = session.risk_events
            final = evaluate_stream_forecast(
                torrent,
                risk_horizon_seconds=risk_horizon_seconds,
                stable_margin_percent=stable_margin_percent,
                preload_margin_percent=preload_margin_percent,
                low_buffer_seconds=low_buffer_seconds,
                protected_buffer_seconds=protected_buffer_seconds,
            )
            torrent["stream_forecast_state"] = final.state
            torrent["stream_forecast_reason"] = final.attributes["reason"]

        for stale_key in set(self._sessions) - active_keys:
            self._sessions.pop(stale_key, None)


def evaluate_streams_forecast(
    torrents: tuple[dict[str, Any], ...],
    *,
    risk_horizon_seconds: float = 60,
    stable_margin_percent: float = 0,
    preload_margin_percent: float = 10,
    low_buffer_seconds: float = 15,
    protected_buffer_seconds: float = 60,
) -> StreamForecast:
    """Return the worst forecast across simultaneous active streams."""
    if not torrents:
        return evaluate_stream_forecast(None)

    forecasts = [
        evaluate_stream_forecast(
            torrent,
            risk_horizon_seconds=risk_horizon_seconds,
            stable_margin_percent=stable_margin_percent,
            preload_margin_percent=preload_margin_percent,
            low_buffer_seconds=low_buffer_seconds,
            protected_buffer_seconds=protected_buffer_seconds,
        )
        for torrent in torrents
    ]
    worst = max(forecasts, key=lambda item: _STATE_PRIORITY[item.state])
    eta_values = [
        item.eta_seconds for item in forecasts if item.eta_seconds is not None
    ]
    margin_values = [
        _optional_float(item.attributes.get("speed_margin_percent"))
        for item in forecasts
    ]
    margins = [item for item in margin_values if item is not None]
    attributes = {
        "stream_count": len(forecasts),
        "at_risk_streams": sum(item.risk for item in forecasts),
        "depleting_streams": sum(item.state == "depleting" for item in forecasts),
        "minimum_eta_seconds": min(eta_values) if eta_values else None,
        "minimum_speed_margin_percent": min(margins) if margins else None,
        "session_risk_events": sum(
            int(item.attributes.get("session_risk_events") or 0)
            for item in forecasts
        ),
    }
    if len(forecasts) == 1:
        attributes.update(worst.attributes)
        attributes["stream_count"] = 1
    return StreamForecast(
        state=worst.state,
        risk=any(item.risk for item in forecasts),
        eta_seconds=min(eta_values) if eta_values else None,
        attributes=attributes,
    )
