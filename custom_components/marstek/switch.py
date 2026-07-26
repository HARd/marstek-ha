"""Switch platform for Marstek Energy System."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class MarstekSwitchEntityDescription(SwitchEntityDescription):
    """Describes Marstek switch entity."""
    is_on_fn: Callable[[dict[str, Any]], bool | None]
    turn_on_fn: Callable[[MarstekDataUpdateCoordinator], Any]
    turn_off_fn: Callable[[MarstekDataUpdateCoordinator], Any]


SWITCH_TYPES: tuple[MarstekSwitchEntityDescription, ...] = (
    MarstekSwitchEntityDescription(
        key="led_display",
        translation_key="led_display",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:led-on",
        is_on_fn=lambda data: data.get("led_state", True),
        turn_on_fn=lambda coord: coord.client.async_set_led_ctrl(1),
        turn_off_fn=lambda coord: coord.client.async_set_led_ctrl(0),
    ),
    MarstekSwitchEntityDescription(
        key="bluetooth_broadcast",
        translation_key="bluetooth_broadcast",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:bluetooth",
        # Note: In Marstek API, Ble.Adv enable=0 is ENABLE, enable=1 is DISABLE
        is_on_fn=lambda data: data.get("ble_status", {}).get("state") == "connect" or data.get("ble_adv_state", True),
        turn_on_fn=lambda coord: coord.client.async_set_ble_adv(0),
        turn_off_fn=lambda coord: coord.client.async_set_ble_adv(1),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek switch entities based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MarstekSwitchEntity(coordinator, description, entry)
        for description in SWITCH_TYPES
    )


class MarstekSwitchEntity(CoordinatorEntity[MarstekDataUpdateCoordinator], SwitchEntity):
    """Marstek switch entity."""

    entity_description: MarstekSwitchEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSwitchEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description

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
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.debug("Turning ON Marstek switch %s", self.entity_description.key)
        await self.entity_description.turn_on_fn(self.coordinator)
        if self.entity_description.key == "led_display":
            self.coordinator.data["led_state"] = True
        elif self.entity_description.key == "bluetooth_broadcast":
            self.coordinator.data["ble_adv_state"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.debug("Turning OFF Marstek switch %s", self.entity_description.key)
        await self.entity_description.turn_off_fn(self.coordinator)
        if self.entity_description.key == "led_display":
            self.coordinator.data["led_state"] = False
        elif self.entity_description.key == "bluetooth_broadcast":
            self.coordinator.data["ble_adv_state"] = False
        self.async_write_ha_state()
