"""API client for Marstek Energy Systems over UDP (Open API Rev 2.0)."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any

from .const import (
    DEFAULT_PORT,
    METHOD_BAT_GET_STATUS,
    METHOD_BLE_ADV,
    METHOD_BLE_GET_STATUS,
    METHOD_DOD_SET,
    METHOD_EM_GET_STATUS,
    METHOD_ES_GET_MODE,
    METHOD_ES_GET_STATUS,
    METHOD_ES_SET_MODE,
    METHOD_GET_DEVICE,
    METHOD_LED_CTRL,
    METHOD_PV_GET_STATUS,
    METHOD_WIFI_GET_STATUS,
    MODE_AI,
    MODE_AUTO,
    MODE_MANUAL,
    MODE_PASSIVE,
    MODE_UPS,
)

_LOGGER = logging.getLogger(__name__)


class MarstekApiError(Exception):
    """Base exception for Marstek API errors."""


class MarstekTimeoutError(MarstekApiError):
    """Timeout waiting for UDP response from Marstek device."""


class MarstekProtocolError(MarstekApiError):
    """Invalid or error response received from Marstek device."""


class MarstekApiClient:
    """Async UDP client for Marstek devices (Open API Rev 2.0)."""

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        """Initialize the API client."""
        self.host = host
        self.port = port
        self._msg_id = 0
        self._lock = asyncio.Lock()
        self._sock: socket.socket | None = None

    def _next_id(self) -> int:
        """Get the next sequential message ID."""
        self._msg_id = (self._msg_id + 1) % 100000
        if self._msg_id == 0:
            self._msg_id = 1
        return self._msg_id

    async def async_send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 3.0,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Send a UDP JSON-RPC command to the Marstek device and wait for response."""
        if params is None:
            params = {"id": 0}

        req_id = self._next_id()
        payload = {
            "id": req_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(payload).encode("utf-8")

        for attempt in range(1, retries + 2):
            try:
                return await self._async_send_datagram(data, req_id, timeout)
            except MarstekTimeoutError:
                if attempt > retries:
                    _LOGGER.debug(
                        "Timeout waiting for Marstek response (%s:%s, method=%s) after %d attempts",
                        self.host,
                        self.port,
                        method,
                        attempt,
                    )
                    raise
                _LOGGER.debug(
                    "Timeout for method %s (attempt %d/%d), retrying...",
                    method,
                    attempt,
                    retries + 1,
                )
                await asyncio.sleep(0.2 * attempt)
            except Exception as err:
                if isinstance(err, (MarstekProtocolError, MarstekApiError)):
                    raise
                _LOGGER.error("Error communicating with Marstek (%s): %s", method, err)
                raise MarstekApiError(f"Communication error: {err}") from err

        raise MarstekTimeoutError(f"No response from {self.host}:{self.port} for {method}")

    def _get_socket(self) -> socket.socket:
        """Return the long-lived UDP socket, recreating it if it was closed.

        The socket is deliberately kept open for the lifetime of the client so all
        requests originate from a single source port. Opening a fresh socket per
        request makes the device see tens of thousands of distinct UDP endpoints per
        day, and late replies land on an already-closed port, which bounces an ICMP
        port-unreachable back at it.
        """
        if self._sock is None or self._sock.fileno() == -1:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._sock = sock
        return self._sock

    def close(self) -> None:
        """Close the UDP socket."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    async def _async_send_datagram(
        self, data: bytes, req_id: int, timeout: float
    ) -> dict[str, Any]:
        """Send datagram and wait for matching response ID using asyncio socket."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            sock = self._get_socket()

            try:
                await loop.sock_sendto(sock, data, (self.host, self.port))
                start_time = time.monotonic()

                while time.monotonic() - start_time < timeout:
                    remaining_time = timeout - (time.monotonic() - start_time)
                    if remaining_time <= 0:
                        break

                    try:
                        resp_data, addr = await asyncio.wait_for(
                            loop.sock_recvfrom(sock, 4096), timeout=remaining_time
                        )
                    except asyncio.TimeoutError:
                        break

                    # Verify it's from our target host (or accept if broadcast)
                    if addr[0] != self.host and self.host != "255.255.255.255":
                        continue

                    try:
                        resp_json = json.loads(resp_data.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

                    # Skip late replies to earlier requests still sitting in the buffer
                    if req_id != 0 and resp_json.get("id") != req_id:
                        continue

                    # Check for error object in response
                    if "error" in resp_json and resp_json["error"]:
                        err_info = resp_json["error"]
                        raise MarstekProtocolError(
                            f"Device returned error {err_info.get('code')}: {err_info.get('message')}"
                        )

                    return resp_json

                raise MarstekTimeoutError(
                    f"Timeout waiting for response ID {req_id} from {self.host}:{self.port}"
                )
            except OSError:
                # Socket is unusable (interface change, fd error) - drop it so the
                # next call builds a fresh one.
                self.close()
                raise

    @classmethod
    async def async_discover_devices(
        cls, timeout: float = 3.0, port: int = DEFAULT_PORT
    ) -> list[dict[str, Any]]:
        """Discover Marstek devices on the local area network via UDP broadcast."""
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)

        payload = {
            "id": 0,
            "method": METHOD_GET_DEVICE,
            "params": {"ble_mac": "0"},
        }
        data = json.dumps(payload).encode("utf-8")
        discovered: dict[str, dict[str, Any]] = {}

        try:
            # Send to generic broadcast and limited broadcast
            for bcast_ip in ("255.255.255.255", "<broadcast>"):
                try:
                    await loop.sock_sendto(sock, data, (bcast_ip, port))
                except Exception as err:
                    _LOGGER.debug("Could not send broadcast to %s: %s", bcast_ip, err)

            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                remaining_time = timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    break

                try:
                    resp_data, addr = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 4096), timeout=remaining_time
                    )
                except asyncio.TimeoutError:
                    break

                try:
                    resp_json = json.loads(resp_data.decode("utf-8"))
                    if "result" in resp_json and isinstance(resp_json["result"], dict):
                        res = resp_json["result"]
                        ip_addr = res.get("ip", addr[0])
                        mac = res.get("wifi_mac", res.get("ble_mac", ip_addr))
                        res["ip"] = ip_addr
                        res["src"] = resp_json.get("src", res.get("device", "Marstek"))
                        discovered[mac] = res
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        finally:
            sock.close()

        return list(discovered.values())

    async def async_test_connection(self) -> bool:
        """Test connection to the Marstek device."""
        try:
            res = await self.async_get_device()
            return res is not None and "result" in res
        except Exception:
            try:
                res = await self.async_get_es_status()
                return res is not None and "result" in res
            except Exception as err:
                _LOGGER.debug("Connection test failed for %s:%s: %s", self.host, self.port, err)
                return False

    async def async_get_device(self) -> dict[str, Any]:
        """Get basic device info (Marstek.GetDevice)."""
        return await self.async_send_command(METHOD_GET_DEVICE, {"ble_mac": "0"})

    async def async_get_es_status(self) -> dict[str, Any]:
        """Get energy system status (ES.GetStatus)."""
        return await self.async_send_command(METHOD_ES_GET_STATUS, {"id": 0})

    async def async_get_bat_status(self) -> dict[str, Any]:
        """Get battery status (Bat.GetStatus)."""
        return await self.async_send_command(METHOD_BAT_GET_STATUS, {"id": 0})

    async def async_get_pv_status(self) -> dict[str, Any]:
        """Get PV / solar status (PV.GetStatus)."""
        return await self.async_send_command(METHOD_PV_GET_STATUS, {"id": 0})

    async def async_get_em_status(self) -> dict[str, Any]:
        """Get energy meter status (EM.GetStatus)."""
        return await self.async_send_command(METHOD_EM_GET_STATUS, {"id": 0})

    async def async_get_wifi_status(self) -> dict[str, Any]:
        """Get WiFi network status (Wifi.GetStatus)."""
        return await self.async_send_command(METHOD_WIFI_GET_STATUS, {"id": 0})

    async def async_get_ble_status(self) -> dict[str, Any]:
        """Get Bluetooth status (BLE.GetStatus)."""
        return await self.async_send_command(METHOD_BLE_GET_STATUS, {"id": 0})

    async def async_get_es_mode(self) -> dict[str, Any]:
        """Get operating mode info (ES.GetMode)."""
        return await self.async_send_command(METHOD_ES_GET_MODE, {"id": 0})

    async def async_set_es_mode(
        self, mode: str, power: int = 100, cd_time: int = 3600
    ) -> dict[str, Any]:
        """Set operating mode (ES.SetMode)."""
        config: dict[str, Any] = {"mode": mode}
        if mode == MODE_AUTO:
            config["auto_cfg"] = {"enable": 1}
        elif mode == MODE_AI:
            config["ai_cfg"] = {"enable": 1}
        elif mode == MODE_UPS:
            config["ups_cfg"] = {"enable": 1}
        elif mode == MODE_PASSIVE:
            config["passive_cfg"] = {"power": power, "cd_time": cd_time}
        elif mode == MODE_MANUAL:
            config["manual_cfg"] = {
                "time_num": 1,
                "start_time": "00:00",
                "end_time": "23:59",
                "week_set": 127,
                "power": power if power > 0 else 1000,
                "enable": 1,
            }
        return await self.async_send_command(METHOD_ES_SET_MODE, {"id": 0, "config": config})

    async def async_set_dod(self, value: int) -> dict[str, Any]:
        """Set Depth of Discharge value (DOD.SET). Range 30-88."""
        return await self.async_send_command(METHOD_DOD_SET, {"value": value})

    async def async_set_ble_adv(self, enable: int) -> dict[str, Any]:
        """Set Bluetooth broadcast state (Ble.Adv). 0: enable, 1: disable."""
        return await self.async_send_command(METHOD_BLE_ADV, {"enable": enable})

    async def async_set_led_ctrl(self, state: int) -> dict[str, Any]:
        """Set LED display state (Led.Ctrl). 1: on, 0: off."""
        return await self.async_send_command(METHOD_LED_CTRL, {"state": state})
