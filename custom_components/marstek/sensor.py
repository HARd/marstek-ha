"""Sensor platform for Marstek Energy System."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class MarstekSensorEntityDescription(SensorEntityDescription):
    """Describes Marstek sensor entity."""
    value_fn: Callable[[dict[str, Any]], Any]


def _get_val(data: dict[str, Any], *keys: tuple[str, str], default: Any = None) -> Any:
    """Get the first non-None value from nested dictionaries."""
    for dict_key, val_key in keys:
        sub = data.get(dict_key)
        if isinstance(sub, dict) and val_key in sub and sub[val_key] is not None:
            return sub[val_key]
    return default


def _get_pv_power(data: dict[str, Any]) -> Any:
    val = _get_val(data, ("es_status", "pv_power"), ("pv_status", "pv_power"))
    if val is not None:
        return val
    if "pv_status" in data and isinstance(data["pv_status"], dict):
        return sum(data["pv_status"].get(f"pv{i}_power", 0) for i in range(1, 5))
    return 0


def _get_pv_voltage(data: dict[str, Any]) -> Any:
    val = _get_val(data, ("pv_status", "pv_voltage"))
    if val is not None:
        return val
    if "pv_status" in data and isinstance(data["pv_status"], dict):
        voltages = [data["pv_status"].get(f"pv{i}_voltage", 0) for i in range(1, 5)]
        return max(voltages, default=0)
    return 0


def _get_pv_current(data: dict[str, Any]) -> Any:
    val = _get_val(data, ("pv_status", "pv_current"))
    if val is not None:
        return val
    if "pv_status" in data and isinstance(data["pv_status"], dict):
        return sum(data["pv_status"].get(f"pv{i}_current", 0) for i in range(1, 5))
    return 0


def _calc_remaining_runtime(data: dict[str, Any]) -> int | None:
    """Calculate remaining runtime in minutes during backup / off-grid operation."""
    if "bat_status" not in data and "es_status" not in data:
        return None
    cap = _get_val(data, ("bat_status", "bat_capacity"), ("es_status", "bat_cap"))
    offgrid = _get_val(data, ("es_status", "offgrid_power"), ("es_mode", "offgrid_power"), default=0)
    ongrid = _get_val(data, ("es_status", "ongrid_power"), default=0)
    bat_power = _get_val(data, ("es_status", "bat_power"), default=0)

    # If grid power is present or battery is not discharging (abs(bat_power) < 15), remaining runtime is 0
    if not cap or float(offgrid) <= 15 or float(ongrid) > 0 or abs(float(bat_power)) < 15:
        return 0
    try:
        hours = float(cap) / float(offgrid)
        return int(hours * 60)
    except (ValueError, ZeroDivisionError):
        return 0


SENSORS: tuple[MarstekSensorEntityDescription, ...] = (
    # Battery SOC
    MarstekSensorEntityDescription(
        key="battery_soc",
        translation_key="battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-high",
        value_fn=lambda data: _get_val(data, ("bat_status", "soc"), ("es_status", "bat_soc"), ("es_mode", "bat_soc")),
    ),
    # On-Grid Power
    MarstekSensorEntityDescription(
        key="ongrid_power",
        translation_key="ongrid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower",
        value_fn=lambda data: _get_val(data, ("es_status", "ongrid_power"), ("es_mode", "ongrid_power"), default=0),
    ),
    # Off-Grid Power
    MarstekSensorEntityDescription(
        key="offgrid_power",
        translation_key="offgrid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-lightning-bolt",
        value_fn=lambda data: _get_val(data, ("es_status", "offgrid_power"), ("es_mode", "offgrid_power"), default=0),
    ),
    # Battery Power
    MarstekSensorEntityDescription(
        key="battery_power",
        translation_key="battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging-wireless",
        value_fn=lambda data: _get_val(data, ("es_status", "bat_power"), default=0),
    ),
    # Solar / PV Power
    MarstekSensorEntityDescription(
        key="pv_power",
        translation_key="pv_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=_get_pv_power,
    ),
    # PV Voltage
    MarstekSensorEntityDescription(
        key="pv_voltage",
        translation_key="pv_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=_get_pv_voltage,
    ),
    # PV Current
    MarstekSensorEntityDescription(
        key="pv_current",
        translation_key="pv_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-dc",
        value_fn=_get_pv_current,
    ),
    # Battery Temperature
    MarstekSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda data: _get_val(data, ("bat_status", "bat_temp")),
    ),
    # Battery Capacity
    MarstekSensorEntityDescription(
        key="battery_capacity",
        translation_key="battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=getattr(SensorDeviceClass, "ENERGY_STORAGE", "energy_storage"),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-50",
        value_fn=lambda data: _get_val(data, ("bat_status", "bat_capacity"), ("es_status", "bat_cap")),
    ),
    # Rated Capacity
    MarstekSensorEntityDescription(
        key="rated_capacity",
        translation_key="rated_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=getattr(SensorDeviceClass, "ENERGY_STORAGE", "energy_storage"),
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery",
        value_fn=lambda data: _get_val(data, ("bat_status", "rated_capacity")),
    ),
    # Remaining Runtime
    MarstekSensorEntityDescription(
        key="remaining_runtime",
        translation_key="remaining_runtime",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        value_fn=_calc_remaining_runtime,
    ),
    # Total PV Energy
    MarstekSensorEntityDescription(
        key="total_pv_energy",
        translation_key="total_pv_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-panel",
        value_fn=lambda data: _get_val(data, ("es_status", "total_pv_energy"), default=0),
    ),
    # Total Grid Output Energy
    MarstekSensorEntityDescription(
        key="total_grid_output_energy",
        translation_key="total_grid_output_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower-export",
        value_fn=lambda data: _get_val(data, ("es_status", "total_grid_output_energy"), default=0),
    ),
    # Total Grid Input Energy
    MarstekSensorEntityDescription(
        key="total_grid_input_energy",
        translation_key="total_grid_input_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower-import",
        value_fn=lambda data: _get_val(data, ("es_status", "total_grid_input_energy"), default=0),
    ),
    # Total Load Energy
    MarstekSensorEntityDescription(
        key="total_load_energy",
        translation_key="total_load_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:home-lightning-bolt-outline",
        value_fn=lambda data: _get_val(data, ("es_status", "total_load_energy"), default=0),
    ),
    # WiFi RSSI
    MarstekSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
        value_fn=lambda data: _get_val(data, ("wifi_status", "rssi")),
    ),
    # WiFi SSID
    MarstekSensorEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi-settings",
        value_fn=lambda data: _get_val(data, ("wifi_status", "ssid"), ("device_info", "wifi_name")),
    ),
    # Device IP
    MarstekSensorEntityDescription(
        key="device_ip",
        translation_key="device_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:ip-network",
        value_fn=lambda data: _get_val(data, ("wifi_status", "sta_ip"), ("device_info", "ip")),
    ),
    # EM Total Power
    MarstekSensorEntityDescription(
        key="em_total_power",
        translation_key="em_total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda data: _get_val(data, ("em_status", "total_power"), ("es_mode", "total_power"), default=0),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek sensor entities based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        MarstekSensorEntity(coordinator, description, entry)
        for description in SENSORS
    )


class MarstekSensorEntity(CoordinatorEntity[MarstekDataUpdateCoordinator], SensorEntity):
    """Marstek sensor entity."""

    entity_description: MarstekSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
