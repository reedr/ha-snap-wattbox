"""Diagnostics for SnapAV WattBox."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import WattboxConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WattboxConfigEntry
) -> dict[str, Any]:
    """Return the entry, the unit's identity and its last state."""
    coord = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "info": asdict(coord.info),
        "state": asdict(coord.data) if coord.data else None,
        "connected": coord.device.connected,
    }
