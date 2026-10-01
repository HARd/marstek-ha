"""The Marstek Energy System integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MarstekApiClient
from .cloud import MarstekCloudClient
from .const import (
    CLOUD_PLATFORMS,
    CONF_CLOUD_DEVID,
    CONF_DATA_SOURCE,
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    RETIRED_ENTITY_KEYS,
    SOURCE_CLOUD,
    SOURCE_LOCAL,
)
from .coordinator import MarstekDataUpdateCoordinator, device_id

_LOGGER = logging.getLogger(__name__)


def _platforms(entry: ConfigEntry) -> list[str]:
    """Return the platforms this entry runs, which depends on its data source."""
    if entry.options.get(CONF_DATA_SOURCE, SOURCE_LOCAL) == SOURCE_CLOUD:
        return CLOUD_PLATFORMS
    return PLATFORMS


def _remove_retired_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete registry entries for entities this version no longer provides.

    Only the explicitly retired keys are touched. Entities that are simply not
    loaded right now - every local one while the entry runs in cloud mode - must
    survive, because they come back when the source is switched again.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if any(entity.unique_id.endswith(f"_{key}") for key in RETIRED_ENTITY_KEYS):
            _LOGGER.debug("Removing retired Marstek entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


def _merge_duplicate_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: MarstekDataUpdateCoordinator
) -> None:
    """Fold entities registered under an older id scheme onto the pinned one.

    Ids used to start with the MAC when GetDevice had answered and with the
    config entry's id when it had not, so a missed reply or a switch to cloud
    mode registered a second copy of every entity, suffixed _2. Copies whose
    pinned id is already taken are the leftovers and get removed.
    """
    target = device_id(entry)
    info = coordinator.device_info_data or {}
    stale = {info.get("wifi_mac"), info.get("ble_mac"), entry.data.get(CONF_HOST)}
    stale -= {None, "", target}

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        prefix = next((p for p in stale if entity.unique_id.startswith(f"{p}_")), None)
        if prefix is None:
            continue
        pinned = f"{target}{entity.unique_id[len(prefix):]}"
        if registry.async_get_entity_id(entity.domain, DOMAIN, pinned):
            _LOGGER.debug("Removing duplicate Marstek entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)
        else:
            registry.async_update_entity(entity.entity_id, new_unique_id=pinned)

    # Hand back the plain entity ids the removed copies were holding.
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        base, _, tail = entity.entity_id.rpartition("_")
        if tail.isdigit() and registry.async_get(base) is None:
            registry.async_update_entity(entity.entity_id, new_entity_id=base)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Energy System from a config entry."""
    _remove_retired_entities(hass, entry)

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    use_cloud = entry.options.get(CONF_DATA_SOURCE, SOURCE_LOCAL) == SOURCE_CLOUD

    _LOGGER.debug(
        "Setting up Marstek integration for host %s:%s with interval %ss",
        host,
        port,
        scan_interval,
    )

    client = MarstekApiClient(host=host, port=port)
    cloud: MarstekCloudClient | None = None

    if use_cloud:
        # Cloud mode never touches the station, so there is nothing local to verify.
        cloud = MarstekCloudClient(
            async_get_clientsession(hass),
            entry.options.get(CONF_EMAIL, ""),
            entry.options.get(CONF_PASSWORD, ""),
        )
    elif not await client.async_test_connection():
        _LOGGER.error("Failed to connect to Marstek device at %s:%s", host, port)
        raise ConfigEntryNotReady(f"Unable to connect to Marstek device at {host}:{port}")

    coordinator = MarstekDataUpdateCoordinator(
        hass=hass,
        client=client,
        scan_interval=scan_interval,
        cloud=cloud,
        cloud_devid=entry.options.get(CONF_CLOUD_DEVID),
    )

    await coordinator.async_config_entry_first_refresh()

    # Remember what was actually loaded: switching the data source reloads the entry,
    # and unload must tear down the old platform set, not the one the new options imply.
    _merge_duplicate_entities(hass, entry, coordinator)

    coordinator.platforms = _platforms(entry)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, coordinator.platforms)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, entry.runtime_data.platforms
    ):
        entry.runtime_data.client.close()
        _LOGGER.debug("Successfully unloaded Marstek integration for %s", entry.title)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
