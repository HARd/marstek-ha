"""Select platform for Marstek Energy System."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN, OPERATING_MODES
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek select entity based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([MarstekOperatingModeSelect(coordinator, entry)])


class MarstekOperatingModeSelect(CoordinatorEntity[MarstekDataUpdateCoordinator], SelectEntity):
    """Marstek operating mode select entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "operating_mode"
    _attr_icon = "mdi:state-machine"
    _attr_options = OPERATING_MODES

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        dev_info = coordinator.device_info_data or {}
        mac = dev_info.get("wifi_mac") or dev_info.get("ble_mac") or entry.data["host"]
        dev_name = dev_info.get("device", "Marstek Energy System")

        self._attr_unique_id = f"{mac}_operating_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=f"{dev_name} ({entry.data['host']})",
            manufacturer="Marstek",
            model=dev_info.get("device", "Energy Storage System"),
            sw_version=str(dev_info.get("ver", "")),
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        mode = self.coordinator.data.get("es_mode", {}).get("mode")
        if mode in self._attr_options:
            return mode
        # Fallback check string case-insensitive
        if mode:
            for opt in self._attr_options:
                if str(mode).lower() == opt.lower():
                    return opt
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug("Setting Marstek operating mode to %s", option)
        power = self.coordinator.last_passive_power
        cd_time = self.coordinator.last_passive_cd_time
        await self.coordinator.client.async_set_es_mode(option, power=power, cd_time=cd_time)
        await asyncio.sleep(1.0)
        self.coordinator.request_full_update()
        await self.coordinator.async_request_refresh()
