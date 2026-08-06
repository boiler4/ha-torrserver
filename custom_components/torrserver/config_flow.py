"""Config flow for TorrServer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    TorrServerApiClient,
    TorrServerAuthenticationError,
    TorrServerCannotConnect,
    normalize_url,
)
from .const import (
    CONF_DOWNLOAD_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_DOWNLOAD_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the connection schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            vol.Optional(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Optional(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): BooleanSelector(),
        }
    )


async def _validate_input(hass: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize connection data."""
    normalized = dict(data)
    normalized[CONF_URL] = normalize_url(str(data[CONF_URL]))
    normalized[CONF_USERNAME] = str(data.get(CONF_USERNAME, "")).strip()
    normalized[CONF_PASSWORD] = str(data.get(CONF_PASSWORD, ""))

    client = TorrServerApiClient(
        async_get_clientsession(hass),
        normalized[CONF_URL],
        username=normalized[CONF_USERNAME] or None,
        password=normalized[CONF_PASSWORD] or None,
        verify_ssl=bool(normalized.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
    )
    snapshot = await client.async_get_data()
    host_label = normalize_url(normalized[CONF_URL]).split("://", 1)[1]
    return {
        "data": normalized,
        "title": f"TorrServer ({host_label})",
        "version": snapshot.version,
    }


class TorrServerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a TorrServer config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up TorrServer through the UI."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await _validate_input(self.hass, user_input)
            except TorrServerAuthenticationError:
                errors["base"] = "invalid_auth"
            except (TorrServerCannotConnect, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(result["data"][CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=result["title"], data=result["data"]
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow connection settings to be changed."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_PASSWORD) and entry.data.get(CONF_PASSWORD):
                user_input = {
                    **user_input,
                    CONF_PASSWORD: entry.data[CONF_PASSWORD],
                }
            try:
                result = await _validate_input(self.hass, user_input)
            except TorrServerAuthenticationError:
                errors["base"] = "invalid_auth"
            except (TorrServerCannotConnect, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(result["data"][CONF_URL])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    title=result["title"],
                    data=result["data"],
                )

        defaults = dict(entry.data)
        defaults.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(user_input or defaults),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm updated credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updated = {
                **entry.data,
                CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD, ""),
            }
            try:
                result = await _validate_input(self.hass, updated)
            except TorrServerAuthenticationError:
                errors["base"] = "invalid_auth"
            except (TorrServerCannotConnect, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=result["data"])

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                    ): TextSelector(),
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the TorrServer options flow."""
        return TorrServerOptionsFlow()


class TorrServerOptionsFlow(config_entries.OptionsFlow):
    """Handle TorrServer options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_DOWNLOAD_THRESHOLD,
                        default=options.get(
                            CONF_DOWNLOAD_THRESHOLD, DEFAULT_DOWNLOAD_THRESHOLD
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=1_000_000,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="B/s",
                        )
                    ),
                }
            ),
        )
