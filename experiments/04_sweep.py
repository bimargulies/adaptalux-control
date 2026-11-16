"""Sweep port 1 from level 0 up to 126 (0xfe) in steps of 8, 1 s apart; always end at 0."""

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
        try:
            for lvl in [*range(0, 120, 8), 120, 126]:
                cmd = brightness_cmd(levels(lvl))
                print(f"level {lvl:3}  W {cmd.hex(' ')}", flush=True)
                await client.write_gatt_char(RX_UUID, cmd, response=True)
                await asyncio.sleep(1.0)
        finally:
            if client.is_connected:
                await client.write_gatt_char(
                    RX_UUID, brightness_cmd(levels(0)), response=True
                )
                print("back to level 0", flush=True)


asyncio.run(main())
