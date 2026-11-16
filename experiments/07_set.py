"""Set arm levels once and exit: `07_set.py 1=25 2=50`, or `07_set.py all=0`.

The pod keeps its levels after we disconnect. Prints levels before and after.
"""

import asyncio
import sys

from adaptalux_control import Pod


async def main(args: list[str]) -> None:
    async with await Pod.connect() as pod:
        print("before:", pod.arms)
        for a in args:
            name, _, value = a.partition("=")
            if name == "all":
                await pod.set_all(float(value))
            else:
                await pod.set_arms({int(name): float(value)})
            await asyncio.sleep(0.2)
        print("after: ", pod.arms)


asyncio.run(main(sys.argv[1:]))
