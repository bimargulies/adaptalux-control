"""Ramp one arm smoothly to a brightness.

uv run python examples/ramp.py ARM PERCENT [--seconds 2] [--label NAME]
"""

import argparse
import asyncio

from adaptalux_control import Pod


async def main(arm: int, percent: float, seconds: float, label: str | None) -> None:
    async with await Pod.connect(label=label) as pod:
        print("before:", pod.arms)
        await pod.ramp({arm: percent}, duration=seconds)
        print("after: ", pod.arms)


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("arm", type=int)
parser.add_argument("percent", type=float)
parser.add_argument("--seconds", type=float, default=2.0)
parser.add_argument("--label", help="pod label from the registry")
args = parser.parse_args()
asyncio.run(main(args.arm, args.percent, args.seconds, args.label))
