"""Marstek V500 power station over Bluetooth LE.

The V500 has no Open API. It speaks the Hame BLE protocol the Venus E uses -
frames of [0x73][len][type][cmd][payload][xor] on service 0xFF00 - but answers
only runtime (0x03), device info (0x04) and Wi-Fi SSID (0x08), and lays the
runtime frame out its own way, without a checksum. The offsets were mapped
against the device display by https://github.com/falseroses/ha-marstek-ble (MIT).
"""
from __future__ import annotations

import asyncio
import logging
import struct
from collections import deque
from collections.abc import Callable
from datetime import timedelta
from functools import reduce
from operator import xor
from typing import TYPE_CHECKING, Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "0000ff01-0000-1000-8000-00805f9b34fb"

FRAME_START = 0x73
FRAME_READ = 0x23
FRAME_WRITE = 0x24
CMD_AC_OUTPUT = 0x02  # write frame; the V500 never answers it
CMD_RUNTIME = 0x03
CMD_DEVICE_INFO = 0x04
CMD_WIFI_SSID = 0x08

# The V500 takes 2-2.5 s to answer a request.
RESPONSE_TIMEOUT = 5.0

AC_INPUT_STATES = {0: "disconnected", 1: "connected", 2: "charging"}


class V500Error(Exception):
    """The V500 could not be reached or did not answer."""


def build_frame(cmd: int, payload: bytes = b"", frame_type: int = FRAME_READ) -> bytes:
    """Build a request frame; the length byte counts the whole frame."""
    frame = bytes([FRAME_START, len(payload) + 5, frame_type, cmd]) + payload
    return frame + bytes([reduce(xor, frame)])


def parse_runtime(frame: bytes) -> dict[str, Any]:
    """Decode the 0x03 runtime frame. Offsets count from the 0x73 start byte."""
    if len(frame) < 51:
        raise ValueError(f"runtime frame too short: {len(frame)} bytes")

    def u16(offset: int) -> int:
        return struct.unpack_from("<H", frame, offset)[0]

    return {
        "ac_output": frame[5] != 0,
        "remaining_capacity": u16(15),  # Wh
        "soc": u16(17) / 100,  # reported in 0.01 %
        "ac_input_power": u16(19),
        "output_power": u16(23),
        "ac_input_state": AC_INPUT_STATES.get(frame[29]),
        "rated_power": u16(49),
    }


def parse_text(frame: bytes) -> str:
    """Return the ASCII payload of a checksummed frame (device info, SSID)."""
    if reduce(xor, frame[:-1]) != frame[-1]:
        raise ValueError(f"bad checksum on 0x{frame[3]:02X} frame")
    return frame[4:-1].decode("ascii", "ignore").strip("\x00 ")


def parse_device_info(text: str) -> dict[str, str]:
    """Parse 'type=HMD-V2,id=...,mac=...,pmu=...' into a dict."""
    pairs = (part.split("=", 1) for part in text.split(",") if "=" in part)
    return {key.strip(): value.strip() for key, value in pairs}


class V500Client:
    """One persistent BLE link to a V500, one request in flight at a time.

    The link stays open between polls: reconnecting costs several seconds,
    longer than the V500 takes to answer. While it is open the Marstek app
    cannot connect over Bluetooth, only over Wi-Fi.
    """

    def __init__(self, name: str, ble_device: Callable[[], BLEDevice | None]) -> None:
        self._name = name
        self._ble_device = ble_device
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        # One reassembly buffer per characteristic, so chunks never interleave.
        self._bufs: dict[str, bytearray] = {}
        self._waiter: tuple[int, asyncio.Future[bytes]] | None = None
        # The last raw notifications, quoted in errors so a failure shows what did arrive.
        self._heard: deque[str] = deque(maxlen=3)

    async def request(self, cmd: int) -> bytes:
        """Send a read command and return the frame that answers it."""
        async with self._lock:
            future = asyncio.get_running_loop().create_future()
            self._waiter = (cmd, future)
            self._heard.clear()
            try:
                await self._write(build_frame(cmd))
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    return await future
            except TimeoutError as err:
                # A link can stay up while the station stops answering; start fresh.
                await self.disconnect()
                heard = "; ".join(self._heard) or "nothing"
                raise V500Error(f"no answer to 0x{cmd:02X}, heard: {heard}") from err
            finally:
                self._waiter = None

    async def set_ac_output(self, on: bool) -> None:
        """Switch the AC output. The new state shows in the next runtime frame."""
        async with self._lock:
            await self._write(build_frame(CMD_AC_OUTPUT, bytes([on]), FRAME_WRITE))

    async def disconnect(self) -> None:
        """Drop the link; the next request reconnects."""
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("%s: disconnect failed: %s", self._name, err)

    async def _write(self, frame: bytes) -> None:
        try:
            client = await self._connect()
            for buf in self._bufs.values():
                buf.clear()
            # Without response, as the Marstek app writes: the V500 is not known
            # to acknowledge write requests.
            await client.write_gatt_char(CHAR_WRITE, frame, response=False)
        except (BleakError, TimeoutError) as err:
            await self.disconnect()
            raise V500Error(f"{self._name}: {err}") from err

    async def _connect(self) -> BleakClientWithServiceCache:
        if self._client is not None and self._client.is_connected:
            return self._client
        device = self._ble_device()
        if device is None:
            raise V500Error(f"{self._name} is not in Bluetooth range")
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self._name,
            disconnected_callback=self._on_disconnect,
            ble_device_callback=self._ble_device,
        )
        # Listen on every notifying characteristic of the service: answers are
        # known on ff02, and the probes that mapped the V500 also listened on ff01 and ff06.
        service = client.services.get_service(SERVICE)
        if service is None:
            await client.disconnect()
            raise V500Error(f"{self._name} has no Marstek service {SERVICE}")
        for char in service.characteristics:
            if {"notify", "indicate"} & set(char.properties):
                await client.start_notify(char, self._notify_handler(char.uuid))
        self._client = client
        return client

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        if client is self._client:
            self._client = None

    def _notify_handler(self, uuid: str) -> Callable[[Any, bytearray], None]:
        buf = self._bufs.setdefault(uuid, bytearray())
        return lambda _sender, data: self._on_notify(uuid, buf, data)

    def _on_notify(self, uuid: str, buf: bytearray, data: bytearray) -> None:
        """Reassemble frames: one can arrive split over several notifications."""
        _LOGGER.debug("%s %s: %s", self._name, uuid[4:8], data.hex(" "))
        self._heard.append(f"{uuid[4:8]} {data[:24].hex()}")
        buf += data
        while True:
            start = buf.find(FRAME_START)
            if start < 0:
                buf.clear()
                return
            del buf[:start]
            if len(buf) < 2:
                return
            length = buf[1]
            if length < 5:  # not a real frame start, look for the next one
                del buf[0]
                continue
            if len(buf) < length:
                return
            frame = bytes(buf[:length])
            del buf[:length]
            if self._waiter and self._waiter[0] == frame[3] and not self._waiter[1].done():
                self._waiter[1].set_result(frame)


class MarstekV500Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls a Marstek V500 over Bluetooth LE."""

    def __init__(self, hass: HomeAssistant, client: V500Client, scan_interval: int) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.platforms: list[str] = []
        self.device_info_data: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Read runtime every cycle; identity and SSID once per setup."""
        try:
            data = {**(self.data or {}), **parse_runtime(await self.client.request(CMD_RUNTIME))}
        except (V500Error, ValueError) as err:
            raise UpdateFailed(f"Error communicating with Marstek V500: {err}") from err

        if not self.device_info_data:
            try:
                info = parse_device_info(parse_text(await self.client.request(CMD_DEVICE_INFO)))
                data["wifi_ssid"] = parse_text(await self.client.request(CMD_WIFI_SSID))
            except (V500Error, ValueError) as err:
                _LOGGER.debug("Could not read V500 identity: %s", err)
            else:
                self.device_info_data = {
                    **info,
                    "device": "V500",
                    "ver": f"PMU {info.get('pmu', '?')} / MPPT {info.get('mppt', '?')} / PCS {info.get('pcs', '?')}",
                }

        data["device_info"] = self.device_info_data
        return data

    async def async_set_ac_output(self, on: bool) -> None:
        """Switch the AC output and show the new state until the next poll confirms it."""
        try:
            await self.client.set_ac_output(on)
        except V500Error as err:
            raise HomeAssistantError(f"Could not switch V500 AC output: {err}") from err
        self.async_set_updated_data({**self.data, "ac_output": on})
