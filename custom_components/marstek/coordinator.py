"""Data update coordinator for Marstek Energy System."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MarstekApiClient, MarstekApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SLOW_UPDATE_CYCLES

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
        self._slow_countdown: int = 0

    def request_full_update(self) -> None:
        """Force the slow endpoint group to be polled on the next update."""
        self._slow_countdown = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Marstek device via UDP."""
        # Start with a shallow copy of previous valid data so temporary UDP packet loss does not cause sensors to flip to Unknown/Unavailable
        data: dict[str, Any] = dict(self.data) if self.data else {}

        # Only ES/Bat telemetry needs per-cycle resolution. Everything else changes
        # slowly, and the device reboots if we flood it with UDP requests.
        run_slow = self._slow_countdown <= 0
        self._slow_countdown = SLOW_UPDATE_CYCLES - 1 if run_slow else self._slow_countdown - 1

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

        # 3. Slow group - mode, PV, meter, wifi and BLE barely move between cycles,
        # so they are polled once every SLOW_UPDATE_CYCLES instead of every update.
        if run_slow:
            for method, fetch, key in (
                ("ES.GetMode", self.client.async_get_es_mode, "es_mode"),
                ("PV.GetStatus", self.client.async_get_pv_status, "pv_status"),
                ("EM.GetStatus", self.client.async_get_em_status, "em_status"),
                ("Wifi.GetStatus", self.client.async_get_wifi_status, "wifi_status"),
                ("BLE.GetStatus", self.client.async_get_ble_status, "ble_status"),
            ):
                await asyncio.sleep(0.25)
                try:
                    res = await fetch()
                    if res and "result" in res:
                        data[key] = res["result"]
                except Exception as err:
                    _LOGGER.debug("Could not fetch %s: %s", method, err)

        # Attach cached device info
        data["device_info"] = self.device_info_data

        return data
