"""Turn all lights off, remembering them, and turn them back on later.

    uv run python examples/lights.py off [--label NAME]
    uv run python examples/lights.py on  [--label NAME]

The configuration is kept in ~/.config/adaptalux-control/lights-NAME.yaml, so you can
turn the lights off, quit, come back later and restore them. Running `off` again while
everything is already dark does not overwrite the saved configuration.
"""

import argparse
import asyncio
from pathlib import Path

from adaptalux_control import Lighting, Pod


async def main(action: str, label: str | None) -> None:
    path = (
        Path.home()
        / ".config"
        / "adaptalux-control"
        / f"lights-{label or 'default'}.yaml"
    )
    async with await Pod.connect(label=label) as pod:
        if action == "off":
            saved = await pod.lights_off()
            if saved.is_dark:
                print("already dark; saved configuration (if any) left alone")
            else:
                saved.save(path)
                print(f"lights off; saved to {path}")
        else:
            await pod.restore(Lighting.load(path))
            print("restored:", pod.arms, "boost:", pod.boost)


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("action", choices=["off", "on"])
parser.add_argument("--label", help="pod label from the registry")
args = parser.parse_args()
asyncio.run(main(args.action, args.label))
