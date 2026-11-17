"""Show, or switch, the pod's global boost.

uv run python examples/boost.py            # just report it
uv run python examples/boost.py on|off [--label NAME]
"""

import argparse
import asyncio

from adaptalux_control import Pod


async def main(state: str | None, label: str | None) -> None:
    async with await Pod.connect(label=label) as pod:
        print("boost at connect:", pod.boost)
        if state is not None:
            await pod.set_boost(state == "on")
            print("boost now:       ", await pod.read_boost())


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("state", nargs="?", choices=["on", "off"])
parser.add_argument("--label", help="pod label from the registry")
args = parser.parse_args()
asyncio.run(main(args.state, args.label))
