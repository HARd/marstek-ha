"""Data update coordinator for Marstek Energy System."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MarstekApiClient, MarstekApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MarstekDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from Marstek UDP API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MarstekApiClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.device_info_data: dict[str, Any] = {}
        self.last_passive_power: int = 100
        self.last_passive_cd_time: int = 3600
        self._consecutive_errors: int = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Marstek device via UDP."""
        # Start with a shallow copy of previous valid data so temporary UDP packet loss does not cause sensors to flip to Unknown/Unavailable
        data: dict[str, Any] = dict(self.data) if self.data else {}

        # Fetch basic device info once if not yet fetched
        if not self.device_info_data:
            try:
                res = await self.client.async_get_device()
                if res and "result" in res:
                    self.device_info_data = res["result"]
                    self.device_info_data["src"] = res.get("src", "Marstek Device")
            except Exception as err:
                _LOGGER.debug("Could not fetch GetDevice during update: %s", err)

        # 1. Fetch ES Status (Primary telemetry: ongrid, offgrid, soc, power)
        try:
            es_res = await self.client.async_get_es_status()
            if es_res and "result" in es_res:
                data["es_status"] = es_res["result"]
                if "src" in es_res and not self.device_info_data.get("src"):
                    self.device_info_data["src"] = es_res["src"]
                self._consecutive_errors = 0
        except MarstekApiError as err:
            self._consecutive_errors += 1
            if not self.data or self._consecutive_errors >= 3:
                _LOGGER.error("Failed to fetch ES.GetStatus from Marstek (attempt %s): %s", self._consecutive_errors, err)
                raise UpdateFailed(f"Error communicating with Marstek device: {err}") from err
            _LOGGER.debug("Temporary UDP packet drop for ES.GetStatus (attempt %s), retaining previous valid telemetry", self._consecutive_errors)

        # Small delay between UDP packets to prevent buffer congestion on ESP-style Wi-Fi modules
        await asyncio.sleep(0.25)

        # 2. Fetch Battery Status (soc, charg_flag, dischrg_flag, temp, capacity)
        try:
            bat_res = await self.client.async_get_bat_status()
            if bat_res and "result" in bat_res:
                data["bat_status"] = bat_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch Bat.GetStatus: %s", err)

        await asyncio.sleep(0.25)

        # 3. Fetch ES Mode (current mode: Auto, AI, Manual, Passive, UPS, ct_state)
        try:
            mode_res = await self.client.async_get_es_mode()
            if mode_res and "result" in mode_res:
                data["es_mode"] = mode_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch ES.GetMode: %s", err)

        await asyncio.sleep(0.25)

        # 4. Fetch PV Status (solar power, voltage, current)
        try:
            pv_res = await self.client.async_get_pv_status()
            if pv_res and "result" in pv_res:
                data["pv_status"] = pv_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch PV.GetStatus: %s", err)

        await asyncio.sleep(0.25)

        # 5. Fetch EM Status (Energy Meter CT Phase powers)
        try:
            em_res = await self.client.async_get_em_status()
            if em_res and "result" in em_res:
                data["em_status"] = em_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch EM.GetStatus: %s", err)

        await asyncio.sleep(0.25)

        # 6. Fetch Wifi Status (RSSI, SSID, IP)
        try:
            wifi_res = await self.client.async_get_wifi_status()
            if wifi_res and "result" in wifi_res:
                data["wifi_status"] = wifi_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch Wifi.GetStatus: %s", err)

        await asyncio.sleep(0.25)

        # 7. Fetch BLE Status
        try:
            ble_res = await self.client.async_get_ble_status()
            if ble_res and "result" in ble_res:
                data["ble_status"] = ble_res["result"]
        except Exception as err:
            _LOGGER.debug("Could not fetch BLE.GetStatus: %s", err)

        # Attach cached device info
        data["device_info"] = self.device_info_data

        return data
