"""Hold sessions on pods and watch them: `12_session_soak.py MINUTES [LABEL ...]`.

Connects to each label (default: fred george) with the 30 s status keepalive,
then every 30 s prints, per pod: connected?, seconds since last status reply,
and any keepalive error. No lights are changed. Ctrl-C or the time limit ends it.
"""

import asyncio
import sys
import time

from adaptalux_control import Pod


async def main(minutes: float, labels: list[str]) -> None:
    t0 = time.monotonic()
    pods: dict[str, Pod] = {}
    try:
        for label in labels:
            pods[label] = await Pod.connect(label=label, timeout=20)
            print(f"{time.monotonic() - t0:6.0f}s  {label}: connected", flush=True)
        while time.monotonic() - t0 < minutes * 60:
            await asyncio.sleep(30)
            for label, pod in pods.items():
                age = pod.status_age
                print(
                    f"{time.monotonic() - t0:6.0f}s  {label}: "
                    f"connected={pod._client.is_connected} "
                    f"status_age={'-' if age is None else f'{age:.0f}s'} "
                    f"error={pod.keepalive_error!r}",
                    flush=True,
                )
    finally:
        for pod in pods.values():
            await pod.close()
        print("closed", flush=True)


args = sys.argv[1:]
asyncio.run(main(float(args[0]) if args else 10, args[1:] or ["fred", "george"]))
