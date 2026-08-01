"""Self-check for the Marstek cloud client: token refresh and field mapping.

Run: python3 test_cloud.py
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
import types
from pathlib import Path

SRC = Path(__file__).parent / "custom_components" / "marstek"

# Stand in for aiohttp, which is a Home Assistant dependency and not needed here.
_aiohttp = types.ModuleType("aiohttp")
_aiohttp.ClientError = type("ClientError", (Exception,), {})
_aiohttp.ClientTimeout = lambda total=None: ("timeout", total)
_aiohttp.ClientSession = object
sys.modules.setdefault("aiohttp", _aiohttp)

_pkg = types.ModuleType("_marstek")
_pkg.__path__ = [str(SRC)]
sys.modules["_marstek"] = _pkg
_spec = importlib.util.spec_from_file_location("_marstek.cloud", SRC / "cloud.py")
cloud = importlib.util.module_from_spec(_spec)
sys.modules["_marstek.cloud"] = cloud
_spec.loader.exec_module(cloud)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Serves canned payloads and records every request."""

    def __init__(self, logins, device_lists):
        self._logins = list(logins)
        self._device_lists = list(device_lists)
        self.login_params = []
        self.device_params = []

    def post(self, url, params=None, timeout=None):
        self.login_params.append(params)
        return FakeResponse(self._logins.pop(0))

    def get(self, url, params=None, timeout=None):
        self.device_params.append(params)
        return FakeResponse(self._device_lists.pop(0))


DEVICE = {
    "devid": "abc123",
    "name": "Venus E",
    "type": "HMG-50",
    "sn": "SN0001",
    "version": "156",
    "soc": 61.5,
    "charge": 800,
    "discharge": 0,
    "load": 240,
    "profit": 12.34,
}


def test_mapping():
    data = cloud.cloud_to_data(DEVICE)
    assert data["es_status"]["bat_soc"] == 61.5, data
    # positive means charging, matching the local API convention
    assert data["es_status"]["bat_power"] == 800, data
    assert data["bat_status"]["soc"] == 61.5, data
    assert data["cloud"]["profit"] == 12.34, data

    # discharging flips the sign
    assert cloud.cloud_to_data({**DEVICE, "charge": 0, "discharge": 500})["es_status"]["bat_power"] == -500

    # Fields the cloud does not report must stay absent, never a fabricated zero,
    # otherwise energy sensors would record a reset to 0.
    sparse = cloud.cloud_to_data({"devid": "x"})
    assert "es_status" not in sparse, sparse
    assert "bat_status" not in sparse, sparse
    for key in ("ongrid_power", "total_pv_energy", "pv_status", "em_status"):
        assert key not in str(sparse) or key == "devid", sparse

    info = cloud.cloud_device_info(DEVICE)
    assert info["device"] == "HMG-50" and info["ver"] == "156", info


async def test_token_refresh():
    # First device call comes back without "data" (stale token), so the client must
    # log in again and retry exactly once.
    session = FakeSession(
        logins=[{"token": "T1"}, {"token": "T2"}],
        device_lists=[{"code": "-1", "msg": "invalid"}, {"data": [DEVICE]}],
    )
    client = cloud.MarstekCloudClient(session, "a@b.c", "hunter2")
    devices = await client.async_get_devices()

    assert devices == [DEVICE]
    assert len(session.login_params) == 2, session.login_params
    assert [p["token"] for p in session.device_params] == ["T1", "T2"]
    # The password must go out hashed, never in the clear.
    assert session.login_params[0]["pwd"] == hashlib.md5(b"hunter2").hexdigest()
    assert "hunter2" not in str(session.login_params)


async def test_permission_error():
    session = FakeSession(
        logins=[{"token": "T1"}, {"token": "T2"}],
        device_lists=[{"code": "8"}, {"code": "8"}],
    )
    client = cloud.MarstekCloudClient(session, "a@b.c", "pw")
    try:
        await client.async_get_devices()
        raise AssertionError("expected an auth error")
    except cloud.MarstekCloudAuthError:
        pass
    assert client._token is None, "token must be dropped so the next cycle re-logs in"


async def test_login_rejected():
    session = FakeSession(logins=[{"msg": "bad password"}], device_lists=[])
    client = cloud.MarstekCloudClient(session, "a@b.c", "pw")
    try:
        await client.async_get_devices()
        raise AssertionError("expected an auth error")
    except cloud.MarstekCloudAuthError:
        pass


async def main():
    test_mapping()
    await test_token_refresh()
    await test_permission_error()
    await test_login_rejected()
    print("ok")


asyncio.run(main())
