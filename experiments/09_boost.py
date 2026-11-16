"""Toggle the boost flag: `09_boost.py [ARM] [PERCENT] [CYCLES]`.

Holds one arm at a fixed level and flips the last byte of the `77` packet
(boost) on and off with pauses, so you can watch for a brightness change.
Boost is always switched back off at the end.
"""

import asyncio
import sys

from adaptalux_control import Pod


async def main(arm: int, percent: float, cycles: int) -> None:
    async with await Pod.connect() as pod:
        try:
            await pod.set_arms({arm: percent})
            print(f"arm {arm} at {percent}%, boost OFF (baseline)")
            await asyncio.sleep(3)
            for i in range(cycles):
                await pod.set_boost(True)
                print(f"[{i + 1}/{cycles}] boost ON  (flag byte 01)")
                await asyncio.sleep(3)
                await pod.set_boost(False)
                print(f"[{i + 1}/{cycles}] boost OFF (flag byte 00)")
                await asyncio.sleep(3)
        finally:
            await pod.set_boost(False)


args = sys.argv[1:]
asyncio.run(
    main(
        int(args[0]) if args else 1,
        float(args[1]) if len(args) > 1 else 50.0,
        int(args[2]) if len(args) > 2 else 2,
    )
)
