"""Ramp port 1 from level 5 down to 0 (0x85 -> 0x80)."""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

from adaptalux_control.adaptalux import (
    CMD_START,
    DEVICE_NAME,
    RX_UUID,
    TX_UUID,
    brightness_cmd,
)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 2  # 1-based


def levels(v: int) -> list[int | None]:
    out: list[int | None] = [None] * 5
    out[PORT - 1] = v
    return out


async def main() -> None:
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if dev is None:
        raise SystemExit("Pod not found.")
    async with BleakClient(dev) as client:
        await client.start_notify(TX_UUID, lambda _, d: print("N", bytes(d).hex(" ")))
        await client.write_gatt_char(RX_UUID, CMD_START, response=True)
        await asyncio.sleep(0.5)
        for lvl in range(5, -1, -1):
            cmd = brightness_cmd(levels(lvl))
            print("W", cmd.hex(" "), flush=True)
            await client.write_gatt_char(RX_UUID, cmd, response=True)
            await asyncio.sleep(1.0)


asyncio.run(main())
