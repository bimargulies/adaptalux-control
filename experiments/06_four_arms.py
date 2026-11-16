"""Check the library against the four arms as plugged in (arms 1-4).

Close the phone app first and put the pod in Bluetooth mode. Boost stays off.
Watch the arms and compare with what each step prints.
"""

import asyncio

from adaptalux_control import Pod

PAUSE = 1.5


async def main() -> None:
    async with await Pod.connect() as pod:
        print("levels adopted from pod status:", pod.arms)

        print("\n1. all arms -> 0 %: every arm should go dark")
        await pod.set_all(0)
        await asyncio.sleep(PAUSE)

        for arm, pct in [(1, 25), (2, 50), (3, 75), (4, 100)]:
            print(f"2. arm {arm} -> {pct} %: only this arm should change")
            await pod.set_arms({arm: pct})
            await asyncio.sleep(PAUSE)

        print("\n3. ramp arm 1 25 -> 100 -> 25 % over 2 s each way")
        await pod.ramp({1: 100}, duration=2)
        await pod.ramp({1: 25}, duration=2)
        await asyncio.sleep(PAUSE)

        print("\n4. all arms -> 0 % and done")
        await pod.set_all(0)
        await asyncio.sleep(0.5)
        print("final levels:", pod.arms)


asyncio.run(main())
