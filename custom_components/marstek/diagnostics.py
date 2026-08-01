"""Diagnostics support for Marstek Energy System."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from homeassistant.config_entries import ConfigEntry

TO_REDACT = {
    "wifi_mac",
    "ble_mac",
    "ssid",
    "wifi_name",
    "sta_ip",
    "ip",
    "host",
    "sta_gate",
    "sta_dns",
    # Cloud mode stores account credentials in the entry options
    "email",
    "mailbox",
    "password",
    "pwd",
    "token",
    "sn",
    "devid",
    "cloud_devid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(coordinator.data, TO_REDACT),
        "device_info": async_redact_data(coordinator.device_info_data, TO_REDACT),
    }
