"""Binary sensor platform for Marstek Energy System."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class MarstekBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Marstek binary sensor entity."""
    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[MarstekBinarySensorEntityDescription, ...] = (
    MarstekBinarySensorEntityDescription(
        key="grid_power_present",
        translation_key="grid_power_present",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:transmission-tower",
        value_fn=lambda data: (
            data.get("es_status", {}).get("ongrid_power", 0) != 0
            or data.get("es_mode", {}).get("ongrid_power", 0) != 0
            or (
                (
                    data.get("es_status", {}).get("offgrid_power", 0) > 0
                    or data.get("es_mode", {}).get("offgrid_power", 0) > 0
                )
                and abs(data.get("es_status", {}).get("bat_power", 0)) < 15
            )
        ) if "es_status" in data or "es_mode" in data else None,
    ),
    MarstekBinarySensorEntityDescription(
        key="backup_power_active",
        translation_key="backup_power_active",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda data: (
            (
                data.get("es_status", {}).get("offgrid_power", 0) > 0
                or data.get("es_mode", {}).get("offgrid_power", 0) > 0
            )
            and data.get("es_status", {}).get("ongrid_power", 0) == 0
            and abs(data.get("es_status", {}).get("bat_power", 0)) >= 15
        ) if "es_status" in data or "es_mode" in data else None,
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_charging",
        translation_key="battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        icon="mdi:battery-charging",
        value_fn=lambda data: (
            data.get("bat_status", {}).get("charg_flag", False) is True
            and (
                data.get("es_status", {}).get("bat_power", 0) > 5
                or data.get("es_status", {}).get("ongrid_power", 0) > 10
                or data.get("pv_status", {}).get("pv_power", 0) > 10
            )
        ) if "bat_status" in data or "es_status" in data else None,
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_charging_permission",
        translation_key="battery_charging_permission",
        icon="mdi:shield-check",
        value_fn=lambda data: data.get("bat_status", {}).get("charg_flag") if "bat_status" in data else None,
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_discharging_permission",
        translation_key="battery_discharging_permission",
        icon="mdi:battery-minus",
        value_fn=lambda data: data.get("bat_status", {}).get("dischrg_flag") if "bat_status" in data else None,
    ),
    MarstekBinarySensorEntityDescription(
        key="ct_connected",
        translation_key="ct_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:current-ac",
        value_fn=lambda data: (
            data.get("es_mode", {}).get("ct_state") == 1
            or data.get("em_status", {}).get("ct_state") == 1
        ) if "es_mode" in data or "em_status" in data else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek binary sensor entities based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        MarstekBinarySensorEntity(coordinator, description, entry)
        for description in BINARY_SENSORS
    )


class MarstekBinarySensorEntity(CoordinatorEntity[MarstekDataUpdateCoordinator], BinarySensorEntity):
    """Marstek binary sensor entity."""

    entity_description: MarstekBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekBinarySensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
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
        """Return true if the binary sensor is on."""
        return self.entity_description.value_fn(self.coordinator.data)
