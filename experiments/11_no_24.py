"""Is `24` required before `77`? `11_no_24.py PHASE [ARM] [PERCENT]`.

Run one phase per invocation (PHASE = 1 or 2) so the observer can report in
between. Each uses a FRESH connection and never sends `24`:
  1. no handshake at all (only enable notify), then 77 with ARM at PERCENT
  2. `23` only, then 77 with ARM at PERCENT
Watch whether the arm lights. Arm is switched back off after each phase.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

from adaptalux_control.adaptalux import CMD_STATUS, DEVICE_NAME, RX_UUID, TX_UUID
from adaptalux_control.protocol import encode_arms


async def phase(label: str, send_status: bool, arm: int, percent: float) -> None:
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if device is None:
        raise SystemExit("pod not found")
    async with BleakClient(device) as client:
        await client.start_notify(
            TX_UUID, lambda _s, d: print(f"   notify: {bytes(d).hex(' ')}")
        )
        if send_status:
            await client.write_gatt_char(RX_UUID, CMD_STATUS, response=True)
            await asyncio.sleep(1)
        print(f"{label}: sending 77 arm {arm} at {percent}% (no 24)")
        for _ in range(3):
            await client.write_gatt_char(
                RX_UUID, encode_arms({arm: percent}), response=True
            )
            await asyncio.sleep(0.3)
        await asyncio.sleep(6)
        await client.write_gatt_char(RX_UUID, encode_arms({}), response=True)
        print(f"{label}: arm off again")
    await asyncio.sleep(2)


async def main(which: int, arm: int, percent: float) -> None:
    if which == 1:
        await phase("phase 1 (nothing sent first)", False, arm, percent)
    else:
        await phase("phase 2 (23 only)", True, arm, percent)


args = sys.argv[1:]
asyncio.run(
    main(
        int(args[0]),
        int(args[1]) if len(args) > 1 else 1,
        float(args[2]) if len(args) > 2 else 50.0,
    )
)
