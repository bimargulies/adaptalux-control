"""Set arm brightness once and exit.

    uv run python examples/set_arms.py 1=25 2=50 [--label NAME]
    uv run python examples/set_arms.py all=0

The pod keeps its levels after you disconnect.
"""

import argparse
import asyncio

from adaptalux_control import Pod


async def main(settings: list[str], label: str | None) -> None:
    async with await Pod.connect(label=label) as pod:
        print("before:", pod.arms)
        for setting in settings:
            name, _, value = setting.partition("=")
            if name == "all":
                await pod.set_all(float(value))
            else:
                await pod.set_arms({int(name): float(value)})
        print("after: ", pod.arms)


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("settings", nargs="+", help="ARM=PERCENT or all=PERCENT")
parser.add_argument("--label", help="pod label from the registry")
args = parser.parse_args()
asyncio.run(main(args.settings, args.label))
