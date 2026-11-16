"""Try turning port 2 off by writing raw value 0x00 (bit 7 clear)."""

import asyncio

from bleak import BleakClient, BleakScanner

from adaptalux_control.adaptalux import CMD_START, DEVICE_NAME, RX_UUID, TX_UUID


async def main() -> None:
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if dev is None:
        raise SystemExit("Pod not found.")
    async with BleakClient(dev) as client:
        await client.start_notify(TX_UUID, lambda _, d: print("N", bytes(d).hex(" ")))
        await client.write_gatt_char(RX_UUID, CMD_START, response=True)
        await asyncio.sleep(0.5)
        cmd = bytes([0x77, 0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0x00])
        print("W", cmd.hex(" "), flush=True)
        await client.write_gatt_char(RX_UUID, cmd, response=True)
        await asyncio.sleep(1.5)


asyncio.run(main())
