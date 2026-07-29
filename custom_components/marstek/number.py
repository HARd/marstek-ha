"""Number platform for Marstek Energy System."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from .const import (
    DEFAULT_DOD,
    DOMAIN,
    MAX_DOD,
    MAX_PASSIVE_POWER,
    MIN_DOD,
    MIN_PASSIVE_POWER,
    MODE_PASSIVE,
)
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class MarstekNumberEntityDescription(NumberEntityDescription):
    """Describes Marstek number entity."""
    min_value: float
    max_value: float
    step_value: float


NUMBER_TYPES: tuple[MarstekNumberEntityDescription, ...] = (
    MarstekNumberEntityDescription(
        key="depth_of_discharge",
        translation_key="depth_of_discharge",
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-alert",
        min_value=MIN_DOD,
        max_value=MAX_DOD,
        step_value=1,
    ),
    MarstekNumberEntityDescription(
        key="passive_mode_power",
        translation_key="passive_mode_power",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:lightning-bolt-circle",
        min_value=MIN_PASSIVE_POWER,
        max_value=MAX_PASSIVE_POWER,
        step_value=10,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek number entities based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MarstekNumberEntity(coordinator, description, entry)
        for description in NUMBER_TYPES
    )


class MarstekNumberEntity(CoordinatorEntity[MarstekDataUpdateCoordinator], NumberEntity):
    """Marstek number entity."""

    entity_description: MarstekNumberEntityDescription
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekNumberEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step_value

        dev_info = coordinator.device_info_data or {}
        mac = dev_info.get("wifi_mac") or dev_info.get("ble_mac") or entry.data["host"]
        dev_name = dev_info.get("device", "Marstek Energy System")

        self._attr_unique_id = f"{mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=f"{dev_name} ({entry.data['host']})",
            manufacturer="Marstek",
            model=dev_info.get("device", "Energy Storage System"),
            sw_version=str(dev_info.get("ver", "")),
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self.entity_description.key == "depth_of_discharge":
            # Some models report dod in bat_status or DOD query, default fallback
            return self.coordinator.data.get("bat_status", {}).get("dod", DEFAULT_DOD)
        if self.entity_description.key == "passive_mode_power":
            return self.coordinator.last_passive_power
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        int_val = int(value)
        if self.entity_description.key == "depth_of_discharge":
            _LOGGER.debug("Setting Marstek DOD to %d%%", int_val)
            await self.coordinator.client.async_set_dod(int_val)
        elif self.entity_description.key == "passive_mode_power":
            _LOGGER.debug("Setting Marstek passive mode power to %d W", int_val)
            self.coordinator.last_passive_power = int_val
            # If currently in Passive mode, send SetMode right away
            current_mode = self.coordinator.data.get("es_mode", {}).get("mode")
            if current_mode == MODE_PASSIVE:
                await self.coordinator.client.async_set_es_mode(
                    MODE_PASSIVE, power=int_val, cd_time=self.coordinator.last_passive_cd_time
                )
        await asyncio.sleep(1.0)
        self.coordinator.request_full_update()
        await self.coordinator.async_request_refresh()
