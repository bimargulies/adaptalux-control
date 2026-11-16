"""Connect, enable notify on TX, send 0x23, print every write/notification."""

import asyncio
import time

from bleak import BleakClient, BleakScanner

from adaptalux_control.adaptalux import CMD_STATUS, DEVICE_NAME, RX_UUID, TX_UUID

t0 = time.monotonic()


def log(tag: str, data: bytes) -> None:
    print(f"{time.monotonic() - t0:7.2f}  {tag}  {data.hex(' ')}", flush=True)


async def main() -> None:
    print(f"Scanning for {DEVICE_NAME} (10s)...", flush=True)
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if dev is None:
        raise SystemExit(
            "Pod not found. Is it in Bluetooth mode and the phone app closed?"
        )
    print("Found", dev, flush=True)
    async with BleakClient(dev) as client:
        await client.start_notify(TX_UUID, lambda _, d: log("N", bytes(d)))
        for _ in range(2):
            log("W", CMD_STATUS)
            await client.write_gatt_char(RX_UUID, CMD_STATUS, response=True)
            await asyncio.sleep(1)


asyncio.run(main())
