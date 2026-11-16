"""Send 24, then ramp brightness up/down on port 1, then port 2 (observed range 3..46)."""

import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

from adaptalux_control.adaptalux import (
    CMD_START,
    DEVICE_NAME,
    RX_UUID,
    TX_UUID,
    brightness_cmd,
)

t0 = time.monotonic()


def log(tag: str, data: bytes) -> None:
    print(f"{time.monotonic() - t0:7.2f}  {tag}  {data.hex(' ')}", flush=True)


async def send(client: BleakClient, data: bytes) -> None:
    log("W", data)
    await client.write_gatt_char(RX_UUID, data, response=True)


async def wiggle(client: BleakClient, port: int) -> None:
    print(f"\n=== PORT {port} (index {port - 1}) ===", flush=True)
    steps = list(range(5, 41, 5)) + list(range(40, 4, -5))
    for lvl in steps:
        levels = [None] * 5
        levels[port - 1] = lvl
        await send(client, brightness_cmd(levels))
        await asyncio.sleep(0.4)
    levels = [None] * 5
    levels[port - 1] = 5
    await send(client, brightness_cmd(levels))
    await asyncio.sleep(1.5)


async def main() -> None:
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if dev is None:
        raise SystemExit("Pod not found.")
    async with BleakClient(dev) as client:
        await client.start_notify(TX_UUID, lambda _, d: log("N", bytes(d)))
        await send(client, CMD_START)
        await asyncio.sleep(0.5)
        ports = [int(a) for a in sys.argv[1:]] or [1, 2]
        try:
            for port in ports:
                await wiggle(client, port)
        except Exception as e:  # noqa: BLE001
            print(f"\n!! stopped: {e!r} (connected={client.is_connected})", flush=True)


asyncio.run(main())
