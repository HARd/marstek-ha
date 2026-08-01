"""The Marstek Energy System integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
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
    SOURCE_CLOUD,
    SOURCE_LOCAL,
)
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _platforms(entry: ConfigEntry) -> list[str]:
    """Return the platforms this entry runs, which depends on its data source."""
    if entry.options.get(CONF_DATA_SOURCE, SOURCE_LOCAL) == SOURCE_CLOUD:
        return CLOUD_PLATFORMS
    return PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek Energy System from a config entry."""
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
