"""Self-check for the Marstek UDP client: socket reuse and stale-reply handling.

Run: python3 test_api_udp.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import socket
import sys
import types
from pathlib import Path

SRC = Path(__file__).parent / "custom_components" / "marstek"

# Load api.py without pulling in custom_components/marstek/__init__.py (needs homeassistant)
_pkg = types.ModuleType("_marstek")
_pkg.__path__ = [str(SRC)]
sys.modules["_marstek"] = _pkg
_spec = importlib.util.spec_from_file_location("_marstek.api", SRC / "api.py")
api = importlib.util.module_from_spec(_spec)
sys.modules["_marstek.api"] = api
_spec.loader.exec_module(api)


class FakeDevice:
    """Minimal UDP device that records the source port of every request."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.src_ports: list[int] = []
        self.behaviour = "reply"  # reply | stale_then_reply | silent

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            data, addr = await loop.sock_recvfrom(self.sock, 4096)
            self.src_ports.append(addr[1])
            req = json.loads(data.decode())
            if self.behaviour == "silent":
                continue
            if self.behaviour == "stale_then_reply":
                # A late reply to some earlier request, which must not be mistaken
                # for the answer to the current one.
                bogus = {"id": req["id"] + 5000, "method": req["method"], "result": {"stale": True}}
                await loop.sock_sendto(self.sock, json.dumps(bogus).encode(), addr)
            ok = {"id": req["id"], "method": req["method"], "result": {"ok": req["id"]}}
            await loop.sock_sendto(self.sock, json.dumps(ok).encode(), addr)


async def main() -> None:
    dev = FakeDevice()
    server = asyncio.create_task(dev.serve())
    client = api.MarstekApiClient(host="127.0.0.1", port=dev.port)

    # 1. Every request reuses one source port -- the device must not see a new
    #    UDP endpoint per poll.
    for _ in range(5):
        res = await client.async_get_es_status()
        assert "result" in res, res
    assert len(dev.src_ports) == 5, dev.src_ports
    assert len(set(dev.src_ports)) == 1, f"socket not reused: {dev.src_ports}"

    # 2. A stale reply sitting in the shared buffer is skipped, not returned.
    dev.behaviour = "stale_then_reply"
    res = await client.async_get_bat_status()
    assert "stale" not in res["result"], res
    assert res["result"]["ok"] == res["id"], res

    # 3. Timeouts do not kill the socket: same port before and after.
    dev.behaviour = "silent"
    port_before = client._sock.getsockname()[1]
    try:
        await client.async_send_command("PV.GetStatus", timeout=0.2, retries=1)
        raise AssertionError("expected a timeout")
    except api.MarstekTimeoutError:
        pass
    dev.behaviour = "reply"
    res = await client.async_get_pv_status()
    assert "result" in res, res
    assert client._sock.getsockname()[1] == port_before, "socket was recreated after timeout"

    # 4. close() releases the socket; the next call transparently rebuilds one.
    client.close()
    assert client._sock is None
    res = await client.async_get_wifi_status()
    assert "result" in res, res

    server.cancel()
    client.close()
    dev.sock.close()
    print("ok")


asyncio.run(main())
