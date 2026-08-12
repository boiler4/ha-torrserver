"""Config flow for TorrServer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    CONF_DOWNLOAD_THRESHOLD_MBPS,
    CONF_EXPERIMENTAL_FFPROBE,
    CONF_SCAN_INTERVAL,
    CONF_STREAM_AVERAGE_WINDOW,
    CONF_STREAM_DOWNGRADE_DELAY,
    CONF_STREAM_LOW_BUFFER_SECONDS,
    CONF_STREAM_PRELOAD_MARGIN,
    CONF_STREAM_PROTECTED_BUFFER_SECONDS,
    CONF_STREAM_RISK_CONFIRMATION,
    CONF_STREAM_RISK_HORIZON,
    CONF_STREAM_STABLE_MARGIN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_DOWNLOAD_THRESHOLD_MBPS,
    DEFAULT_EXPERIMENTAL_FFPROBE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STREAM_AVERAGE_WINDOW,
    DEFAULT_STREAM_DOWNGRADE_DELAY,
    DEFAULT_STREAM_LOW_BUFFER_SECONDS,
    DEFAULT_STREAM_PRELOAD_MARGIN,
    DEFAULT_STREAM_PROTECTED_BUFFER_SECONDS,
    DEFAULT_STREAM_RISK_CONFIRMATION,
    DEFAULT_STREAM_RISK_HORIZON,
    DEFAULT_STREAM_STABLE_MARGIN,
    DEFAULT_URL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_STREAM_AVERAGE_WINDOW,
    MAX_STREAM_BUFFER_SECONDS,
    MAX_STREAM_DOWNGRADE_DELAY,
    MAX_STREAM_MARGIN,
    MAX_STREAM_RISK_CONFIRMATION,
    MAX_STREAM_RISK_HORIZON,
    MIN_SCAN_INTERVAL,
    MIN_STREAM_AVERAGE_WINDOW,
    MIN_STREAM_BUFFER_SECONDS,
    MIN_STREAM_DOWNGRADE_DELAY,
    MIN_STREAM_MARGIN,
    MIN_STREAM_RISK_CONFIRMATION,
    MIN_STREAM_RISK_HORIZON,
)
from .discovery import (
    DiscoveredTorrServer,
    async_discover_torrservers,
    candidate_urls_from_adapters,
)

CONF_DISCOVERY_PORT = "discovery_port"
CONF_DISCOVERY_RESULT = "discovery_result"


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
    _discovered: dict[str, DiscoveredTorrServer]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer safe automatic discovery or manual configuration."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["discover", "manual"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up TorrServer using a manually entered URL."""
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
            step_id="manual",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover TorrServer instances on enabled local IPv4 networks."""
        errors: dict[str, str] = {}
        if user_input is not None:
            custom_port_value = user_input.get(CONF_DISCOVERY_PORT)
            custom_port = int(custom_port_value) if custom_port_value else None
            adapters = await network.async_get_adapters(self.hass)
            urls = candidate_urls_from_adapters(adapters, custom_port=custom_port)
            results = await async_discover_torrservers(
                async_get_clientsession(self.hass), urls
            )
            if results:
                self._discovered = {result.url: result for result in results}
                if len(results) == 1:
                    return await self._async_discovery_confirmation(results[0])
                return await self.async_step_discovery_select()
            errors["base"] = "no_servers_found"

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_DISCOVERY_PORT): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=65535,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_discovery_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user select one of multiple discovered instances."""
        if user_input is not None:
            candidate = self._discovered[str(user_input[CONF_DISCOVERY_RESULT])]
            return await self._async_discovery_confirmation(candidate)

        options = [
            SelectOptionDict(
                value=item.url,
                label=(
                    f"🔒 {item.url}"
                    if item.auth_required
                    else f"{item.url} — {item.version or 'TorrServer'}"
                ),
            )
            for item in self._discovered.values()
        ]
        return self.async_show_form(
            step_id="discovery_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DISCOVERY_RESULT): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _async_discovery_confirmation(
        self, candidate: DiscoveredTorrServer
    ) -> ConfigFlowResult:
        """Open the selected candidate; credentials are used only from here."""
        self.context["torrserver_discovery_url"] = candidate.url
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered URL and optionally authenticate it."""
        url = str(self.context["torrserver_discovery_url"])
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

        defaults = user_input or {
            CONF_URL: url,
            CONF_VERIFY_SSL: True,
            CONF_USERNAME: "",
        }
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=_user_schema(defaults),
            errors=errors,
            description_placeholders={"url": url},
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
        errors: dict[str, str] = {}
        if user_input is not None:
            stable_margin = float(user_input[CONF_STREAM_STABLE_MARGIN])
            preload_margin = float(user_input[CONF_STREAM_PRELOAD_MARGIN])
            low_buffer = float(user_input[CONF_STREAM_LOW_BUFFER_SECONDS])
            protected_buffer = float(
                user_input[CONF_STREAM_PROTECTED_BUFFER_SECONDS]
            )
            average_window = float(user_input[CONF_STREAM_AVERAGE_WINDOW])
            scan_interval = float(user_input[CONF_SCAN_INTERVAL])
            if preload_margin <= stable_margin:
                errors[CONF_STREAM_PRELOAD_MARGIN] = "preload_margin_too_low"
            elif protected_buffer <= low_buffer:
                errors[CONF_STREAM_PROTECTED_BUFFER_SECONDS] = (
                    "protected_buffer_too_low"
                )
            elif average_window < scan_interval:
                errors[CONF_STREAM_AVERAGE_WINDOW] = "average_window_too_short"
            else:
                return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        defaults = user_input or options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
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
                        CONF_STREAM_AVERAGE_WINDOW,
                        default=defaults.get(
                            CONF_STREAM_AVERAGE_WINDOW,
                            max(
                                DEFAULT_STREAM_AVERAGE_WINDOW,
                                defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                            ),
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_AVERAGE_WINDOW,
                            max=MAX_STREAM_AVERAGE_WINDOW,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_DOWNLOAD_THRESHOLD_MBPS,
                        default=defaults.get(
                            CONF_DOWNLOAD_THRESHOLD_MBPS,
                            DEFAULT_DOWNLOAD_THRESHOLD_MBPS,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=8_000,
                            step=0.01,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="Mbps",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_LOW_BUFFER_SECONDS,
                        default=defaults.get(
                            CONF_STREAM_LOW_BUFFER_SECONDS,
                            DEFAULT_STREAM_LOW_BUFFER_SECONDS,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_BUFFER_SECONDS,
                            max=MAX_STREAM_BUFFER_SECONDS,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_PROTECTED_BUFFER_SECONDS,
                        default=defaults.get(
                            CONF_STREAM_PROTECTED_BUFFER_SECONDS,
                            DEFAULT_STREAM_PROTECTED_BUFFER_SECONDS,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_BUFFER_SECONDS,
                            max=MAX_STREAM_BUFFER_SECONDS,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_STABLE_MARGIN,
                        default=defaults.get(
                            CONF_STREAM_STABLE_MARGIN,
                            DEFAULT_STREAM_STABLE_MARGIN,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_MARGIN,
                            max=MAX_STREAM_MARGIN,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_PRELOAD_MARGIN,
                        default=defaults.get(
                            CONF_STREAM_PRELOAD_MARGIN,
                            DEFAULT_STREAM_PRELOAD_MARGIN,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_MARGIN,
                            max=MAX_STREAM_MARGIN,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_DOWNGRADE_DELAY,
                        default=defaults.get(
                            CONF_STREAM_DOWNGRADE_DELAY,
                            DEFAULT_STREAM_DOWNGRADE_DELAY,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_DOWNGRADE_DELAY,
                            max=MAX_STREAM_DOWNGRADE_DELAY,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_RISK_HORIZON,
                        default=defaults.get(
                            CONF_STREAM_RISK_HORIZON,
                            DEFAULT_STREAM_RISK_HORIZON,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_RISK_HORIZON,
                            max=MAX_STREAM_RISK_HORIZON,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_STREAM_RISK_CONFIRMATION,
                        default=defaults.get(
                            CONF_STREAM_RISK_CONFIRMATION,
                            DEFAULT_STREAM_RISK_CONFIRMATION,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STREAM_RISK_CONFIRMATION,
                            max=MAX_STREAM_RISK_CONFIRMATION,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Required(
                        CONF_EXPERIMENTAL_FFPROBE,
                        default=defaults.get(
                            CONF_EXPERIMENTAL_FFPROBE,
                            DEFAULT_EXPERIMENTAL_FFPROBE,
                        ),
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )
