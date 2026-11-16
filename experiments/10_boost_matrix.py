"""Boost across levels and arms: `10_boost_matrix.py`.

Part A: all arms at 25 / 50 / 100 %, boost off then on.
Part B: each arm alone at 50 %, boost on then off.
Boost is always switched off at the end.
"""

import asyncio

from adaptalux_control import Pod

HOLD = 2.5


async def main() -> None:
    async with await Pod.connect() as pod:
        try:
            for level in (25, 50, 100):
                await pod.set_boost(False)
                await pod.set_all(level)
                print(f"A: all arms {level}%  boost OFF")
                await asyncio.sleep(HOLD)
                await pod.set_boost(True)
                print(f"A: all arms {level}%  boost ON")
                await asyncio.sleep(HOLD)
            await pod.set_boost(False)
            for arm in range(1, 6):
                await pod.set_all(0)
                await pod.set_arms({arm: 50})
                print(f"B: arm {arm} alone 50%  boost OFF")
                await asyncio.sleep(HOLD)
                await pod.set_boost(True)
                print(f"B: arm {arm} alone 50%  boost ON")
                await asyncio.sleep(HOLD)
                await pod.set_boost(False)
        finally:
            await pod.set_boost(False)
            await pod.set_all(0)


asyncio.run(main())
