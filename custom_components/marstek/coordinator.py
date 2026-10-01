"""Data update coordinator for Marstek Energy System."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MarstekApiClient, MarstekApiError
from .cloud import (
    MarstekCloudClient,
    MarstekCloudError,
    cloud_device_info,
    cloud_to_data,
)
from .const import DEFAULT_DOD, DEFAULT_SCAN_INTERVAL, DOMAIN, SLOW_UPDATE_CYCLES

_LOGGER = logging.getLogger(__name__)


def device_id(entry: ConfigEntry) -> str:
    """Return the id every entity and device of this entry is keyed on.

    It has to be the same in cloud and local mode and survive a GetDevice that
    went unanswered, so it comes from the config entry and never from telemetry.
    The entry's own unique id is the station's MAC when discovery could read one.
    """
    return entry.unique_id or entry.entry_id


class MarstekDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from Marstek UDP API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MarstekApiClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        cloud: MarstekCloudClient | None = None,
        cloud_devid: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.cloud = cloud
        self.cloud_devid = cloud_devid
        self.platforms: list[str] = []
        self.device_info_data: dict[str, Any] = {}
        self.last_dod: int = DEFAULT_DOD
        self.last_passive_power: int = 100
        self.last_passive_cd_time: int = 3600
        self._consecutive_errors: int = 0
        self._slow_countdown: int = 0

    def request_full_update(self) -> None:
        """Force the slow endpoint group to be polled on the next update."""
        self._slow_countdown = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch telemetry from whichever source this entry is configured for."""
        if self.cloud is not None:
            return await self._async_update_cloud()
        return await self._async_update_local()

    async def _async_update_cloud(self) -> dict[str, Any]:
        """Fetch telemetry from the Marstek cloud. Sends nothing to the station."""
        try:
            devices = await self.cloud.async_get_devices()
        except MarstekCloudError as err:
            raise UpdateFailed(f"Error communicating with Marstek cloud: {err}") from err

        device = next(
            (d for d in devices if str(d.get("devid")) == str(self.cloud_devid)),
            None,
        )
        if device is None:
            raise UpdateFailed(
                f"Device {self.cloud_devid} is not present in the Marstek cloud account"
            )

        if not self.device_info_data:
            self.device_info_data = cloud_device_info(device)

        data = cloud_to_data(device)
        data["device_info"] = self.device_info_data
        return data

    async def _async_update_local(self) -> dict[str, Any]:
        """Fetch data from Marstek device via UDP."""
        # Start with a shallow copy of previous valid data so temporary UDP packet loss does not cause sensors to flip to Unknown/Unavailable
        data: dict[str, Any] = dict(self.data) if self.data else {}

        # Only ES telemetry needs per-cycle resolution. Everything else changes
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

        # Bat.GetStatus is not polled at all: it is the measured trigger for the
        # firmware switching its own Open API off, and dropping it took the
        # station from a reset every ~2h to one every ~11 days. SOC and capacity
        # come from ES.GetStatus instead; battery temperature, rated capacity and
        # the charge/discharge permission flags have no other source and stay
        # empty. ponytail: re-add the call once a firmware stops resetting.
        # https://github.com/MarstekEnergy/aiomarstek/issues/2

        # 2. Slow group - mode, PV, meter, wifi and BLE barely move between cycles,
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
