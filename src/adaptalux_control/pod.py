"""Async client for the Adaptalux Control Pod, built on bleak."""

import asyncio
from types import TracebackType
from typing import Any, Self

from .adaptalux import (
    CMD_START,
    CMD_STATUS,
    DEVICE_NAME,
    RX_UUID,
    SERVICE_UUID,
    TX_UUID,
)
from .protocol import (
    ARM_TO_SLOT,
    SLOT_COUNT,
    check_percent,
    StatusReassembler,
    encode_slots,
    slot_percents_to_arms,
    status_slot_percents,
)

RAMP_STEP_S = 0.06  # the iPhone app sends a packet about every 60 ms


class PodNotFound(Exception):
    pass


class Pod:
    """Control a pod.

    Close the iPhone app first (the pod takes one central at a time) and put
    the pod in Bluetooth mode (hold its top button until the blue light
    flashes).

        async with await Pod.connect() as pod:
            await pod.set_arms({1: 25, 2: 50, 3: 75, 4: 100})
            await pod.ramp({1: 0}, duration=2)

    Arms are numbered 1-5 in the iPhone app's layout order; percentages are
    0-100; anything outside that raises ValueError and is never sent. The pod has no "leave unchanged" value, so this object remembers the
    level of every arm and resends all five each time.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._slots = [0.0] * SLOT_COUNT
        self._boost = False  # global boost flag: applies to every arm
        self._status = StatusReassembler()
        self._status_ready = asyncio.Event()
        self._status_slots: list[float] | None = None

    # -- connection ---------------------------------------------------------

    @classmethod
    async def connect(
        cls,
        *,
        name: str = DEVICE_NAME,
        address: str | None = None,
        timeout: float = 10.0,
    ) -> Self:
        """Find the pod (by address if given, else by name or service UUID)."""
        from bleak import BleakClient, BleakScanner

        if address is not None:
            device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda d, adv: (
                    d.name == name or SERVICE_UUID in (adv.service_uuids or [])
                ),
                timeout=timeout,
            )
        if device is None:
            raise PodNotFound(
                "Pod not found: is it in Bluetooth mode and the phone app closed?"
            )
        pod = cls(BleakClient(device))
        await pod._open()
        return pod

    async def _open(self) -> None:
        await self._client.connect()
        await self._client.start_notify(TX_UUID, self._on_notify)
        await self._handshake()

    async def _handshake(self) -> None:
        """Same opening as the app: 23 (status), then 24."""
        await self._write(CMD_STATUS)
        try:
            await asyncio.wait_for(self._status_ready.wait(), timeout=2.0)
            assert self._status_slots is not None
            self._slots = list(self._status_slots)  # adopt the pod's current state
        except TimeoutError:
            pass  # keep all-zero assumption
        await self._write(CMD_START)
        await self._write(CMD_START)

    async def close(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    # -- state --------------------------------------------------------------

    @property
    def arms(self) -> dict[int, float]:
        """Last known percentage of each arm, {1: .., ..., 5: ..}."""
        return slot_percents_to_arms(self._slots)

    @property
    def boost(self) -> bool:
        """Global boost flag (pod-wide, not per arm)."""
        return self._boost

    # -- commands -----------------------------------------------------------

    async def set_arms(self, levels: dict[int, float]) -> None:
        """Set some arms (others keep their level) in one packet.

        Raises ValueError, without sending anything, if an arm is unknown or a
        level is outside 0..100 %: values above 100 % are never sent.
        """
        for arm, percent in levels.items():
            if arm not in ARM_TO_SLOT:
                raise ValueError(f"no such arm {arm}; arms are 1-{SLOT_COUNT}")
            check_percent(percent)
        for arm, percent in levels.items():
            self._slots[ARM_TO_SLOT[arm]] = percent
        await self._send_state()

    async def set_all(self, percent: float) -> None:
        await self.set_arms({arm: percent for arm in ARM_TO_SLOT})

    async def set_boost(self, on: bool) -> None:
        """Turn the global boost on/off; it brightens all arms at once."""
        self._boost = on
        await self._send_state()

    async def ramp(
        self,
        targets: dict[int, float],
        duration: float = 1.0,
        step: float = RAMP_STEP_S,
    ) -> None:
        """Move the given arms linearly to their targets over `duration` s.

        Targets outside 0..100 % raise ValueError before anything is sent.
        """
        for arm, target in targets.items():
            if arm not in ARM_TO_SLOT:
                raise ValueError(f"no such arm {arm}; arms are 1-{SLOT_COUNT}")
            check_percent(target)
        start = self.arms
        steps = max(1, round(duration / step))
        for i in range(1, steps + 1):
            frac = i / steps
            await self.set_arms(
                {
                    a: min(100.0, max(0.0, start[a] + (t - start[a]) * frac))
                    for a, t in targets.items()
                }
            )
            if i < steps:
                await asyncio.sleep(step)

    # -- internals ----------------------------------------------------------

    async def _send_state(self) -> None:
        await self._write(encode_slots(self._slots, self._boost))

    async def _write(self, data: bytes) -> None:
        await self._client.write_gatt_char(RX_UUID, data, response=True)

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        status = self._status.feed(bytes(data))
        if status is not None and not self._status_ready.is_set():
            self._status_slots = status_slot_percents(status)
            self._status_ready.set()
