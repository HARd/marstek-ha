"""Read-only Bluetooth probe for Marstek batteries we have no BLE map for yet (Venus A).

Scan for nearby Marstek devices:
    python3 ble_probe.py
Probe one of them (address as the scan prints it; on macOS that is a UUID):
    python3 ble_probe.py <ADDRESS> [monitor_seconds]   (default 60)
Add --system-data to also send 0x0D. On a Venus E an empty 0x0D reads grid
voltage and frequency, but the same command with a payload sets the charge
mode, so it is left out unless asked for.

Needs bleak (pip install bleak). Close the Marstek app first: the battery
accepts one Bluetooth connection at a time. Only commands that are reads on
the Venus E are sent - never reboot, mode, EPS or output writes.
Everything goes to the terminal and to ble_probe_<address>.txt.
"""
from __future__ import annotations

import asyncio
import sys
import time
from functools import reduce
from operator import xor

from bleak import BleakClient, BleakScanner

NAME_HINTS = ("MST", "HM_", "VENUS", "MARSTEK")
# Read-only on the Venus E: runtime, device info, Wi-Fi SSID, timers, BMS,
# config, logs, CT polling rate, network info, local API status.
READ_CMDS = [0x03, 0x04, 0x08, 0x13, 0x14, 0x1A, 0x1C, 0x22, 0x24, 0x28]
SYSTEM_DATA = 0x0D
WRITE_CHAR = "0000ff01-0000-1000-8000-00805f9b34fb"


def frame(cmd: int) -> bytes:
    """[0x73][len][0x23][cmd][xor] - the Hame request the Venus E and V500 answer."""
    head = bytes([0x73, 5, 0x23, cmd])
    return head + bytes([reduce(xor, head)])


def ascii_view(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


async def scan() -> None:
    print("Scanning 10 s ...")
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    rows = sorted(found.values(), key=lambda pair: -pair[1].rssi)
    for device, adv in rows:
        name = adv.local_name or device.name or ""
        if any(hint in name.upper() for hint in NAME_HINTS):
            print(f"{device.address}  rssi={adv.rssi}  {name}")
    print("No Marstek-looking names? Move closer and close the Marstek app.")


async def probe(address: str, seconds: int, cmds: list[int]) -> None:
    log = open(f"ble_probe_{address.replace(':', '')}.txt", "a")
    t0 = time.monotonic()
    last: dict[tuple[str, int | None], bytes] = {}

    def out(line: str) -> None:
        print(line)
        log.write(line + "\n")
        log.flush()

    def on_notify(uuid: str):
        short = uuid[4:8]

        def callback(_sender, data: bytearray) -> None:
            data = bytes(data)
            key = (short, data[3] if len(data) > 3 else None)
            prev, last[key] = last.get(key), data
            diff = ""
            if prev is not None and len(prev) == len(data):
                changed = [i for i in range(len(data)) if data[i] != prev[i]]
                diff = "  changed " + ",".join(f"{i}:{prev[i]:02x}>{data[i]:02x}" for i in changed) if changed else "  (same)"
            out(f"[{time.monotonic() - t0:6.1f}s] {short} len={len(data)} {data.hex(' ')}{diff}")
            if sum(32 <= b < 127 for b in data) > len(data) * 0.6:
                out(f"          ascii: {ascii_view(data)}")

        return callback

    async with BleakClient(address, timeout=30) as client:
        out(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} connected {address} mtu={client.mtu_size}")
        notify = []
        for service in client.services:
            out(f"service {service.uuid}")
            for char in service.characteristics:
                out(f"  char {char.uuid} {','.join(char.properties)}")
                if "read" in char.properties:
                    try:
                        value = bytes(await client.read_gatt_char(char))
                        out(f"    read: {value.hex(' ')}  {ascii_view(value)}")
                    except Exception as err:  # noqa: BLE001 - a probe logs and carries on
                        out(f"    read failed: {err}")
                if {"notify", "indicate"} & set(char.properties):
                    notify.append(char.uuid)

        for uuid in notify:
            try:
                await client.start_notify(uuid, on_notify(uuid))
                out(f"subscribed {uuid}")
            except Exception as err:  # noqa: BLE001
                out(f"subscribe {uuid} failed: {err}")

        out("\n=== passive listen 5 s (does it push anything on its own?)")
        await asyncio.sleep(5)

        if not any(c.uuid == WRITE_CHAR for s in client.services for c in s.characteristics):
            out(f"no {WRITE_CHAR} - not the Hame protocol, stopping before any write")
            return

        out("\n=== read sweep")
        for cmd in cmds:
            out(f"-> 0x{cmd:02X}  {frame(cmd).hex(' ')}")
            await client.write_gatt_char(WRITE_CHAR, frame(cmd), response=False)
            await asyncio.sleep(3)

        out(f"\n=== monitor: 0x03 every 3 s for {seconds} s - change ONE thing at a time")
        out("    (load on/off, grid plug, PV) and note the second shown")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            await client.write_gatt_char(WRITE_CHAR, frame(0x03), response=False)
            await asyncio.sleep(3)
    out("=== done")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cmds = READ_CMDS + ([SYSTEM_DATA] if "--system-data" in sys.argv else [])
    if not args:
        asyncio.run(scan())
    else:
        asyncio.run(probe(args[0], int(args[1]) if len(args) > 1 else 60, cmds))
