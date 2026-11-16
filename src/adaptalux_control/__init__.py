from .pod import Pod, PodNotFound
from .protocol import encode_arms, encode_slots, percent_to_byte
from .registry import PodRegistry, UnknownPod, identify_pods, scan_pods

__all__ = [
    "Pod",
    "PodNotFound",
    "PodRegistry",
    "UnknownPod",
    "encode_arms",
    "encode_slots",
    "identify_pods",
    "main",
    "percent_to_byte",
    "scan_pods",
]


def main() -> None:
    import asyncio
    import sys

    if sys.argv[1:] == ["identify"]:
        asyncio.run(identify_pods())
    elif sys.argv[1:] == ["list"]:
        reg = PodRegistry.load()
        print(f"# {reg.path}")
        for label, address in sorted(reg.pods.items()):
            print(f"{label}: {address}")
    else:
        print("usage: adaptalux-control identify | list")
