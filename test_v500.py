"""Self-check for the V500 BLE client: framing, parsing and frame reassembly.

Run: python3 test_v500.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import struct
import sys
import types
from functools import reduce
from operator import xor
from pathlib import Path

SRC = Path(__file__).parent / "custom_components" / "marstek"


def _stub(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules.setdefault(name, module)


# Stand in for bleak and Home Assistant, neither of which is needed here.
BleakError = type("BleakError", (Exception,), {})
_stub("bleak")
_stub("bleak.exc", BleakError=BleakError)
_stub("bleak_retry_connector", BleakClientWithServiceCache=object, establish_connection=None)
_stub("homeassistant")
_stub("homeassistant.exceptions", HomeAssistantError=Exception)
_stub("homeassistant.helpers")


class _Coordinator:
    def __class_getitem__(cls, _item):
        return cls


_stub("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_Coordinator, UpdateFailed=Exception)

_pkg = types.ModuleType("_marstek")
_pkg.__path__ = [str(SRC)]
sys.modules["_marstek"] = _pkg
for name in ("const", "v500"):
    spec = importlib.util.spec_from_file_location(f"_marstek.{name}", SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"_marstek.{name}"] = module
    spec.loader.exec_module(module)
v500 = sys.modules["_marstek.v500"]


def runtime_frame() -> bytes:
    """A 55-byte V500 runtime frame: no checksum, length byte = whole frame."""
    frame = bytearray(55)
    frame[0:4] = bytes([0x73, 55, 0x23, 0x03])
    frame[5] = 1  # AC output on
    struct.pack_into("<H", frame, 15, 1997)  # Wh
    struct.pack_into("<H", frame, 17, 9945)  # 99.45 %
    struct.pack_into("<H", frame, 19, 494)  # AC in W
    struct.pack_into("<H", frame, 23, 21)  # out W
    frame[29] = 2  # charging
    struct.pack_into("<H", frame, 49, 500)
    return bytes(frame)


def text_frame(cmd: int, text: str) -> bytes:
    frame = bytes([0x73, len(text) + 5, 0x23, cmd]) + text.encode()
    return frame + bytes([reduce(xor, frame)])


class FakeChar:
    def __init__(self, handle, uuid, *properties):
        self.handle = handle
        self.uuid = f"0000{uuid}-0000-1000-8000-00805f9b34fb"
        self.properties = list(properties)


class FakeService:
    def __init__(self, uuid, *characteristics):
        self.uuid = f"0000{uuid}-0000-1000-8000-00805f9b34fb"
        self.characteristics = list(characteristics)


# ff06 sits in its own service, and a standard 0x2Axx characteristic notifies too.
FAKE_SERVICES = [
    FakeService("1801", FakeChar(3, "2a05", "indicate")),
    FakeService(
        "ff00",
        FakeChar(10, "ff01", "write-without-response", "write", "notify"),
        FakeChar(13, "ff02", "notify"),
        FakeChar(16, "ff03", "read"),
    ),
    FakeService("ff05", FakeChar(20, "ff06", "notify")),
]


class FakeBleak:
    """Answers each write on ff02 in 20-byte notifications, while ff01 chatters."""

    services = FAKE_SERVICES

    def __init__(self, replies):
        self.replies = replies
        self.is_connected = True
        self.written = []
        self.notify = {}

    async def start_notify(self, char, callback):
        self.notify[char.uuid[4:8]] = callback

    async def write_gatt_char(self, _char, data, response=None):
        assert response is False, "the V500 is written without response"
        self.written.append(bytes(data))
        if len(self.written) == 1:
            return  # the first request after connecting goes unanswered
        reply = self.replies.get(data[3])
        if reply is not None:
            async def push():
                self.notify["ff02"](None, bytearray(b"\x00\x01"))  # line noise before the frame
                for i in range(0, len(reply), 20):
                    await asyncio.sleep(0)
                    # A frame start on another characteristic must not corrupt this one.
                    self.notify["ff01"](None, bytearray(b"\x73\x30\x23"))
                    self.notify["ff02"](None, bytearray(reply[i:i + 20]))
            asyncio.get_running_loop().create_task(push())

    async def disconnect(self):
        self.is_connected = False


def check_frames() -> None:
    # Byte-for-byte what the Marstek app sends to switch AC output on and off.
    assert v500.build_frame(0x02, b"\x01", 0x24) == bytes.fromhex("730624020152")
    assert v500.build_frame(0x02, b"\x00", 0x24) == bytes.fromhex("730624020053")
    assert v500.build_frame(0x03) == bytes([0x73, 0x05, 0x23, 0x03, 0x73 ^ 0x05 ^ 0x23 ^ 0x03])

    assert v500.parse_runtime(runtime_frame()) == {
        "ac_output": True,
        "remaining_capacity": 1997,
        "soc": 99.45,
        "ac_input_power": 494,
        "output_power": 21,
        "ac_input_state": "charging",
        "rated_power": 500,
    }
    try:
        v500.parse_runtime(runtime_frame()[:40])
    except ValueError:
        pass
    else:
        raise AssertionError("short runtime frame accepted")

    info = text_frame(0x04, "type=HMD-V2,id=abc,mac=001122334455,pmu=110,mppt=105,pcs=120")
    assert v500.parse_device_info(v500.parse_text(info))["pcs"] == "120"
    try:
        v500.parse_text(info[:-1] + bytes([info[-1] ^ 1]))
    except ValueError:
        pass
    else:
        raise AssertionError("bad checksum accepted")


async def check_client() -> None:
    fake = FakeBleak({0x03: runtime_frame(), 0x08: text_frame(0x08, "home"), 0x13: b"\x73\x40\x23\x13"})

    async def establish(*_args, **_kwargs):
        return fake

    v500.establish_connection = establish
    v500.RESPONSE_TIMEOUT = 0.2
    client = v500.V500Client("HM_V500_test", lambda: object())

    assert await client.request(0x03) == runtime_frame()
    assert len(fake.written) == 2  # answered on the retry, same link
    assert set(fake.notify) == {"ff01", "ff02", "ff06"}  # vendor ones, in any service
    assert v500.parse_text(await client.request(0x08)) == "home"

    await client.set_ac_output(False)
    assert fake.written[-1] == bytes.fromhex("730624020053")

    # A truncated answer never completes: the request fails, says what did
    # arrive, and the dead link is dropped.
    try:
        await client.request(0x13)
    except v500.V500Error as err:
        assert "after 3 tries" in str(err) and "ff02 73402313" in str(err), err
        assert "listening on: ff01@ff00, ff02@ff00, ff06@ff05" in str(err), err
    else:
        raise AssertionError("unanswered request did not fail")
    assert not fake.is_connected and client._client is None

    fake.is_connected = True
    assert await client.request(0x03) == runtime_frame()  # reconnects


if __name__ == "__main__":
    check_frames()
    asyncio.run(check_client())
    print("v500 ok")
