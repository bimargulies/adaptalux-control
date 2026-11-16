"""Ramp one arm: `08_ramp.py ARM TARGET [SECONDS]`."""

import asyncio
import sys

from adaptalux_control import Pod


async def main(arm: int, target: float, seconds: float) -> None:
    async with await Pod.connect() as pod:
        print("before:", pod.arms)
        await pod.ramp({arm: target}, duration=seconds)
        print("after: ", pod.arms)


asyncio.run(main(int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 2.0))
