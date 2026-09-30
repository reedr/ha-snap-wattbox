"""Registry migrations from the legacy "Wattbox" package."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_LEGACY_ENTRY, DOMAIN, LEGACY_DOMAIN
from .coordinator import WattboxConfigEntry
from .device import WattboxInfo

_LOGGER = logging.getLogger(__name__)

_RESET_SUFFIX = " Reset"


async def async_migrate_legacy_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> None:
    """Move the legacy entry's device and entities onto this entry, then remove it.

    Device and entity registry IDs are kept, so entity IDs, history, areas, labels,
    customizations and device-based automations carry over unchanged.
    """
    legacy_id = entry.data.get(CONF_LEGACY_ENTRY)
    if legacy_id is None:
        return

    legacy = hass.config_entries.async_get_entry(legacy_id)
    if legacy is not None and legacy.domain == LEGACY_DOMAIN:
        # Loaded entities can't change platform. The legacy package is normally
        # gone by now (this one replaces its folder), but unload it if not.
        if legacy.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(legacy_id)

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(ent_reg, legacy_id):
            ent_reg.async_update_entity_platform(
                entity.entity_id, DOMAIN, new_config_entry_id=entry.entry_id
            )
            _LOGGER.info("Took over %s from the legacy Wattbox integration", entity.entity_id)
        for device in dr.async_entries_for_config_entry(dev_reg, legacy_id):
            dev_reg.async_update_device(
                device.id,
                new_config_entry_id=entry.entry_id,
                new_identifiers={
                    (DOMAIN, ident) if domain == LEGACY_DOMAIN else (domain, ident)
                    for domain, ident in device.identifiers
                },
            )
        await hass.config_entries.async_remove(legacy_id)

    data = {k: v for k, v in entry.data.items() if k != CONF_LEGACY_ENTRY}
    hass.config_entries.async_update_entry(entry, data=data)


@callback
def async_migrate_unique_ids(
    hass: HomeAssistant, entry: WattboxConfigEntry, info: WattboxInfo
) -> None:
    """Rekey legacy ``<hostname>_<outlet name>[ Reset]`` IDs to the service tag and outlet number.

    Outlets are matched by their current name on the unit. An entity whose outlet
    has since been renamed can't be matched and is left for the user to remove.
    """
    tag = info.service_tag
    numbers: dict[str, int] = {}
    for i, name in enumerate(info.outlet_names):
        numbers.setdefault(name, i + 1)

    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.unique_id.startswith(f"{tag}_") or "_" not in entity.unique_id:
            continue
        # Hostnames can't contain "_", so the first one ends the prefix.
        name = entity.unique_id.split("_", 1)[1]
        if entity.domain == "button" and name.endswith(_RESET_SUFFIX):
            key, name = "reset", name.removesuffix(_RESET_SUFFIX)
        elif entity.domain == "switch":
            key = "outlet"
        else:
            continue
        if (number := numbers.get(name)) is None:
            _LOGGER.warning(
                "%s: no outlet named %r on %s; leaving it unmigrated",
                entity.entity_id,
                name,
                info.hostname,
            )
            continue
        new_id = f"{tag}_{key}_{number}"
        if ent_reg.async_get_entity_id(entity.domain, DOMAIN, new_id):
            _LOGGER.warning("%s: %s is already taken", entity.entity_id, new_id)
            continue
        ent_reg.async_update_entity(entity.entity_id, new_unique_id=new_id)

    dev_reg = dr.async_get(hass)
    if dev_reg.async_get_device_by_identifier((DOMAIN, tag), entry.entry_id) is None:
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if any(domain == DOMAIN for domain, _ in device.identifiers):
                dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, tag)})
                break

    if entry.unique_id is None and not any(
        other.unique_id == tag for other in hass.config_entries.async_entries(DOMAIN)
    ):
        hass.config_entries.async_update_entry(entry, unique_id=tag)
