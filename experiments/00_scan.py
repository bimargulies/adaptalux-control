"""List all nearby BLE devices with name, RSSI and advertised service UUIDs."""

import asyncio

from bleak import BleakScanner


async def main() -> None:
    found = await BleakScanner.discover(timeout=12, return_adv=True)
    for dev, adv in sorted(found.values(), key=lambda p: -p[1].rssi):
        print(
            f"{adv.rssi:4}  {dev.address}  {adv.local_name or dev.name}  {adv.service_uuids}"
        )


asyncio.run(main())
