"""Set a Gen 2 flash arm's power level (1-5).

    uv run python examples/flash.py ARM LEVEL [--label NAME] [--boost]

Boost must be on; pass --boost to switch it on first. Raises BoostOff otherwise.
"""

import argparse
import asyncio

from adaptalux_control import Pod


async def main(arm: int, level: int, label: str | None, boost: bool) -> None:
    async with await Pod.connect(label=label) as pod:
        if boost:
            await pod.set_boost(True)
        await pod.set_flash_level(arm, level)
        print(f"arm {arm} set to flash level {level}")


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("arm", type=int)
parser.add_argument("level", type=int, choices=range(1, 6))
parser.add_argument("--label", help="pod label from the registry")
parser.add_argument("--boost", action="store_true", help="turn boost on first")
args = parser.parse_args()
asyncio.run(main(args.arm, args.level, args.label, args.boost))
