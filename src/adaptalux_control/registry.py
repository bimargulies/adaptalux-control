"""Per-Mac registry that maps friendly pod labels to pod addresses.

The pods give a Mac nothing that tells them apart (same name, serial number
"0000", all-zero system ID), and macOS hides the real Bluetooth address behind
a per-Mac UUID. So each Mac has to learn once which pod is which: ``identify_pods``
winks one pod at a time, asks the user what to call it, and stores the answer in
a YAML file that ``Pod.connect(label=...)`` reads from then on.

File format (default ``~/.config/adaptalux-control/pods.yaml``)::

    pods:
      bench: 11111111-2222-3333-4444-555555555555
      studio: 9D1E...

The addresses are only meaningful on the Mac that wrote them. If macOS ever
hands a pod a new UUID, run the identify flow again.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .adaptalux import DEVICE_NAME, SERVICE_UUID

DEFAULT_PATH = Path.home() / ".config" / "adaptalux-control" / "pods.yaml"


class UnknownPod(KeyError):
    pass


class PodRegistry:
    """Label -> address mapping, loaded from and saved to a YAML file."""

    def __init__(self, pods: dict[str, str] | None = None, path: Path | None = None):
        self.pods: dict[str, str] = dict(pods or {})
        self.path = Path(path) if path is not None else DEFAULT_PATH

    @classmethod
    def load(cls, path: Path | None = None) -> "PodRegistry":
        """Read the file; a missing file gives an empty registry."""
        path = Path(path) if path is not None else DEFAULT_PATH
        if not path.exists():
            return cls(path=path)
        data = yaml.safe_load(path.read_text()) or {}
        pods = data.get("pods") or {}
        if not isinstance(pods, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in pods.items()
        ):
            raise ValueError(f"{path}: 'pods' must map label strings to addresses")
        return cls(pods, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump({"pods": self.pods}, sort_keys=True))

    def address(self, label: str) -> str:
        try:
            return self.pods[label]
        except KeyError:
            known = ", ".join(sorted(self.pods)) or "none"
            raise UnknownPod(
                f"no pod labelled {label!r} (known: {known}); "
                "run `adaptalux-control identify`"
            ) from None

    def label_for(self, address: str) -> str | None:
        for label, addr in self.pods.items():
            if addr == address:
                return label
        return None

    def add(self, label: str, address: str) -> None:
        """Record a label. A label can only point at one pod, and vice versa."""
        # bleak on macOS hands out addresses as objc.pyobjc_unicode (a str
        # subclass) that yaml.safe_dump refuses; store plain str.
        label, address = str(label), str(address)
        if not label.strip():
            raise ValueError("label must not be empty")
        if label in self.pods and self.pods[label] != address:
            raise ValueError(f"label {label!r} is already used for another pod")
        old = self.label_for(address)
        if old is not None and old != label:
            del self.pods[old]  # relabel: one label per pod
        self.pods[label] = address


async def scan_pods(timeout: float = 10.0) -> list[str]:
    """Addresses of all pods currently advertising (in Bluetooth mode).

    A pod that is already connected to a phone does not advertise, so it will
    not appear here.
    """
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    return [
        str(dev.address)
        for dev, adv in found.values()
        if dev.name == DEVICE_NAME or SERVICE_UUID in (adv.service_uuids or [])
    ]


async def identify_pods(
    registry: PodRegistry | None = None,
    *,
    ask: Callable[[str], str] = input,
    say: Callable[[str], Any] = print,
    scan_timeout: float = 10.0,
) -> PodRegistry:
    """Wink each unlabelled, visible pod and ask what to call it.

    For every advertising pod that has no label yet: connect, wink its arms,
    and ``ask`` for a label (empty = skip). The registry is saved after each
    answer, then returned. Pods that already have a label are left alone, so
    this is safe to rerun after plugging in a new pod. ``ask`` is blocking and
    runs in a worker thread so the Bluetooth link stays serviced.
    """
    from .pod import Pod

    registry = registry if registry is not None else PodRegistry.load()
    addresses = await scan_pods(scan_timeout)
    if not addresses:
        say("No pods found. Put each in Bluetooth mode and close the phone app.")
        return registry
    for address in addresses:
        known = registry.label_for(address)
        if known is not None:
            say(f"{address}: already labelled {known!r}, skipping")
            continue
        async with await Pod.connect(address=address) as pod:
            await pod.wink()
            while True:
                label = (
                    await asyncio.to_thread(
                        ask, "Which pod just winked? Label (blank to skip): "
                    )
                ).strip()
                if not label:
                    break
                try:
                    registry.add(label, address)
                except ValueError as exc:
                    say(str(exc))
                    continue
                registry.save()
                say(f"saved {label!r} -> {address} in {registry.path}")
                break
    return registry
