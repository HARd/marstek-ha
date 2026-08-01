"""Read-only cloud API client for Marstek (eu.hamedata.com).

The cloud API exposes a login and a device list, and nothing else - there are no
control endpoints, so this client can only read telemetry.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp

from .const import CLOUD_API_DEVICES, CLOUD_API_LOGIN, CLOUD_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class MarstekCloudError(Exception):
    """Cloud API request failed."""


class MarstekCloudAuthError(MarstekCloudError):
    """Cloud API rejected the credentials."""


class MarstekCloudClient:
    """Minimal async client for the Marstek cloud API."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        """Initialize the cloud client."""
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None

    async def _async_login(self) -> None:
        """Exchange credentials for a token."""
        # The API expects the password MD5-hashed as a query parameter. That is its
        # design, not a choice made here.
        params = {
            "pwd": hashlib.md5(self._password.encode()).hexdigest(),
            "mailbox": self._email,
        }
        data = await self._async_request(CLOUD_API_LOGIN, params, post=True)
        token = data.get("token")
        if not token:
            raise MarstekCloudAuthError(f"Login rejected by cloud API: {data}")
        self._token = token
        _LOGGER.debug("Obtained new Marstek cloud token")

    async def _async_request(
        self, url: str, params: dict[str, Any], post: bool = False
    ) -> dict[str, Any]:
        """Perform one HTTP request and decode the JSON body."""
        method = self._session.post if post else self._session.get
        try:
            async with method(
                url, params=params, timeout=aiohttp.ClientTimeout(total=CLOUD_TIMEOUT)
            ) as resp:
                # The API serves JSON as text/html on some endpoints
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise MarstekCloudError(f"Cloud request to {url} failed: {err}") from err

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return the list of devices on the account."""
        if self._token is None:
            await self._async_login()

        data = await self._async_request(CLOUD_API_DEVICES, {"token": self._token})

        # A missing "data" key means the token was not accepted. Refresh once and
        # retry rather than pattern-matching on error codes, which are undocumented.
        if "data" not in data:
            _LOGGER.debug("Cloud device list returned %s, refreshing token", data)
            self._token = None
            await self._async_login()
            data = await self._async_request(CLOUD_API_DEVICES, {"token": self._token})

        if "data" not in data:
            self._token = None
            if str(data.get("code")) == "8":
                raise MarstekCloudAuthError(f"No access permission (code 8): {data}")
            raise MarstekCloudError(f"Unexpected cloud response: {data}")

        return data["data"]


def _num(value: Any) -> float | None:
    """Coerce a cloud field to a number, or None if it is not one."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cloud_to_data(device: dict[str, Any]) -> dict[str, Any]:
    """Map a cloud device record onto the local API's data shape.

    Only fields the cloud actually reports are filled in. Everything else is left
    absent so entities that cannot be fed stay empty instead of reading a
    fabricated zero.
    """
    data: dict[str, Any] = {"cloud": device}

    soc = _num(device.get("soc"))
    charge = _num(device.get("charge"))
    discharge = _num(device.get("discharge"))

    es_status: dict[str, Any] = {}
    if soc is not None:
        es_status["bat_soc"] = soc
        data["bat_status"] = {"soc": soc}
    if charge is not None or discharge is not None:
        # Local API convention: positive means charging.
        es_status["bat_power"] = (charge or 0) - (discharge or 0)
    if es_status:
        data["es_status"] = es_status

    return data


def cloud_device_info(device: dict[str, Any]) -> dict[str, Any]:
    """Build the cached device-info block from a cloud device record."""
    return {
        "device": device.get("type") or device.get("name") or "Marstek",
        "ver": device.get("version", ""),
        "sn": device.get("sn", ""),
        "src": "Marstek Cloud",
    }
