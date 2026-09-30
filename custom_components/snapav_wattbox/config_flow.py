"""Config flow for the SnapAV WattBox integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_LEGACY_ENTRY,
    CONF_OUTLET_METERING,
    DEFAULT_OUTLET_METERING,
    DOMAIN,
    LEGACY_DOMAIN,
)
from .device import WattboxAuthError, WattboxDevice, WattboxError, WattboxInfo

_LOGGER = logging.getLogger(__name__)

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def clean_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Trim the host and username; the password is kept as typed."""
    cleaned = dict(user_input)
    for key in (CONF_HOST, CONF_USERNAME):
        if key in cleaned:
            cleaned[key] = cleaned[key].strip()
    return cleaned


async def validate_connection(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[WattboxInfo | None, dict[str, str]]:
    """Log in and read the unit's identity; return it or form errors."""
    dev = WattboxDevice(hass, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])
    try:
        return await dev.async_test_connection(), {}
    except WattboxAuthError as err:
        _LOGGER.warning("Setup could not log in: %s", err)
        return None, {"base": "invalid_auth"}
    except WattboxError as err:
        _LOGGER.warning("Setup could not connect: %s", err)
        return None, {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return None, {"base": "unknown"}


class WattboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SnapAV WattBox."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._skip_legacy = False

    def _legacy_entries(self) -> list[ConfigEntry]:
        """Entries of the legacy "Wattbox" package not yet imported."""
        imported = {
            entry.data.get(CONF_LEGACY_ENTRY)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        hosts = {
            entry.data.get(CONF_HOST) for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        return [
            entry
            for entry in self.hass.config_entries.async_entries(LEGACY_DOMAIN)
            if entry.entry_id not in imported and entry.data.get(CONF_HOST) not in hosts
        ]

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return WattboxOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None and not self._skip_legacy and self._legacy_entries():
            return self.async_show_menu(step_id="user", menu_options=["import_legacy", "manual"])

        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = clean_input(user_input)
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            info, errors = await validate_connection(self.hass, user_input)
            if info is not None:
                await self.async_set_unique_id(info.service_tag)
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(title=info.hostname, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(CONNECTION_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a new unit instead of importing the legacy ones."""
        self._skip_legacy = True
        return await self.async_step_user()

    async def async_step_import_legacy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import every legacy entry: same settings, devices and entity IDs."""
        legacies = self._legacy_entries()
        if not legacies:
            return self.async_abort(reason="no_legacy_entry")
        if user_input is None:
            return self.async_show_form(
                step_id="import_legacy",
                description_placeholders={
                    "count": str(len(legacies)),
                    "titles": ", ".join(sorted(entry.title for entry in legacies)),
                },
            )
        first, *rest = legacies
        for legacy in rest:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_IMPORT},
                    data={CONF_LEGACY_ENTRY: legacy.entry_id},
                )
            )
        return self._async_create_legacy_entry(first)

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import one legacy entry (started by import_legacy)."""
        legacy = self.hass.config_entries.async_get_entry(import_data[CONF_LEGACY_ENTRY])
        if legacy is None or legacy.domain != LEGACY_DOMAIN:
            return self.async_abort(reason="no_legacy_entry")
        return self._async_create_legacy_entry(legacy)

    def _async_create_legacy_entry(self, legacy: ConfigEntry) -> ConfigFlowResult:
        self._async_abort_entries_match({CONF_HOST: legacy.data[CONF_HOST]})
        return self.async_create_entry(
            title=legacy.title,
            data={
                CONF_HOST: legacy.data[CONF_HOST],
                CONF_USERNAME: legacy.data[CONF_USERNAME],
                CONF_PASSWORD: legacy.data[CONF_PASSWORD],
                CONF_LEGACY_ENTRY: legacy.entry_id,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The unit rejected the stored login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new username and password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = clean_input(user_input)
            _, errors = await validate_connection(self.hass, {**entry.data, **user_input})
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA, user_input or {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            description_placeholders={"title": entry.title, "host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host or login."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = clean_input(user_input)
            info, errors = await validate_connection(self.hass, user_input)
            if info is not None:
                if entry.unique_id is not None:
                    await self.async_set_unique_id(info.service_tag)
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )


class WattboxOptionsFlow(OptionsFlow):
    """Handle options for SnapAV WattBox."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Turn per-outlet metering on or off."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OUTLET_METERING,
                        default=self.config_entry.options.get(
                            CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING
                        ),
                    ): bool,
                }
            ),
        )
