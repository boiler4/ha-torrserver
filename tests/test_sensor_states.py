"""Regression tests for Home Assistant sensor state constraints."""

from homeassistant.const import MAX_LENGTH_STATE_STATE

from custom_components.torrserver.sensor import _safe_text_state


def test_text_state_preserves_values_up_to_home_assistant_limit() -> None:
    value = "à" * MAX_LENGTH_STATE_STATE

    assert _safe_text_state(value) == value


def test_text_state_truncates_long_unicode_without_becoming_unknown() -> None:
    value = "🎬" * (MAX_LENGTH_STATE_STATE + 50)
    state = _safe_text_state(value)

    assert state is not None
    assert len(state) == MAX_LENGTH_STATE_STATE
    assert state.endswith("…")


def test_text_state_handles_empty_and_non_string_values() -> None:
    assert _safe_text_state(None) is None
    assert _safe_text_state("") is None
    assert _safe_text_state(1234) == "1234"
