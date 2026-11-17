"""Async client for the Adaptalux Control Pod, built on bleak."""

import asyncio
import logging
import time
from pathlib import Path
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
    FLASH_LEVEL_SECONDS,
    FLASH_PULSE_BYTE,
    SLOT_COUNT,
    StatusReassembler,
    check_percent,
    encode_slots,
    slot_percents_to_arms,
    status_slot_percents,
)
from .registry import PodRegistry

RAMP_STEP_S = 0.06  # the iPhone app sends a packet about every 60 ms
KEEPALIVE_S = 30.0  # how often a session asks the pod for status

log = logging.getLogger(__name__)


class PodNotFound(Exception):
    pass


class Pod:
    """Control a pod. A ``Pod`` is a session: from ``connect`` until ``close``.

    While the session is open it asks the pod for its status every
    ``keepalive_interval`` seconds (default 30; ``None`` turns this off), in
    case the pod drops idle links or stops advertising. ``status_age`` says how
    long ago the pod last answered, and ``keepalive_error`` holds the exception
    if a keepalive write failed (usually: the link is gone).

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

    def __init__(
        self, client: Any, keepalive_interval: float | None = KEEPALIVE_S
    ) -> None:
        self._client = client
        self._keepalive_interval = keepalive_interval
        self._keepalive_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()  # keepalive and commands share the link
        self._last_status_time: float | None = None
        self.keepalive_error: BaseException | None = None
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
        label: str | None = None,
        registry_path: Path | None = None,
        timeout: float = 10.0,
        keepalive_interval: float | None = KEEPALIVE_S,
    ) -> Self:
        """Find the pod.

        By ``label`` (looked up in this Mac's pod registry, see
        :mod:`adaptalux_control.registry`), else by ``address``, else the first
        pod found by name or service UUID. With two pods advertising, use a
        label: the unlabelled form could pick either.
        """
        from bleak import BleakClient, BleakScanner

        if label is not None:
            if address is not None:
                raise ValueError("pass either label or address, not both")
            address = PodRegistry.load(registry_path).address(label)

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
        pod = cls(BleakClient(device), keepalive_interval)
        await pod._open()
        return pod

    async def _open(self) -> None:
        await self._client.connect()
        await self._client.start_notify(TX_UUID, self._on_notify)
        await self._handshake()
        if self._keepalive_interval is not None:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

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

    async def wink(self, times: int = 3, on: float = 0.35, off: float = 0.25) -> None:
        """Flash all arms so a person can see which pod this is.

        Only arms that are plugged in will visibly light. Levels are restored
        afterwards; the boost flag is not touched.
        """
        saved = list(self._slots)
        try:
            for _ in range(times):
                self._slots = [100.0] * SLOT_COUNT
                await self._send_state()
                await asyncio.sleep(on)
                self._slots = [0.0] * SLOT_COUNT
                await self._send_state()
                await asyncio.sleep(off)
        finally:
            self._slots = saved
            await self._send_state()

    async def close(self) -> None:
        task, self._keepalive_task = self._keepalive_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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
    def status_age(self) -> float | None:
        """Seconds since the pod last sent a status reply (None: never)."""
        if self._last_status_time is None:
            return None
        return time.monotonic() - self._last_status_time

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

    async def set_flash_level(self, arm: int, level: int) -> None:
        """Set a Gen 2 flash arm's power level (1-5), as the iPhone app does.

        The level is sent as a timed pulse on the arm's slot (see
        ``protocol.FLASH_PULSE_BYTE``), then the arm is left at 100 %, which
        flash arms need. Boost must already be on (``set_boost(True)``): a Pod
        assumes boost is off until told otherwise, and flash arms do not charge
        without it. The call returns once the pulse is sent; the arm then
        charges to the new level; small changes show up almost at once, but a
        big jump up (seen: 2 -> 5) took up to about a minute, with the arm's
        LEDs climbing meanwhile. Do not use this on LED arms. Raises ValueError, sending
        nothing, for a bad arm or level or if boost is off.
        """
        if arm not in ARM_TO_SLOT:
            raise ValueError(f"no such arm {arm}; arms are 1-{SLOT_COUNT}")
        if level not in FLASH_LEVEL_SECONDS:
            raise ValueError(f"flash level must be 1-5, got {level!r}")
        if not self._boost:
            raise ValueError("flash arms need boost: call set_boost(True) first")
        index = 1 + ARM_TO_SLOT[arm]  # position of the arm's byte in the packet

        async def send(byte: int, times: int) -> None:
            packet = bytearray(encode_slots(self._slots, self._boost))
            packet[index] = byte
            for _ in range(times):
                await self._write(bytes(packet))

        loop = asyncio.get_running_loop()
        await send(0xFF, 3)
        pulse_start = loop.time()
        await send(FLASH_PULSE_BYTE, 2)
        await asyncio.sleep(
            max(0.0, pulse_start + FLASH_LEVEL_SECONDS[level] - loop.time())
        )
        self._slots[ARM_TO_SLOT[arm]] = 100.0
        await send(0x00, 2)

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
        async with self._write_lock:
            await self._client.write_gatt_char(RX_UUID, data, response=True)

    async def _keepalive_loop(self) -> None:
        assert self._keepalive_interval is not None
        try:
            while True:
                await asyncio.sleep(self._keepalive_interval)
                await self._write(CMD_STATUS)
        except Exception as exc:  # noqa: BLE001 - record any failure; cancel passes through
            self.keepalive_error = exc
            log.warning("pod keepalive failed: %r", exc)

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        status = self._status.feed(bytes(data))
        if status is None:
            return
        self._last_status_time = time.monotonic()
        log.debug("status: %s", status.hex(" "))
        if not self._status_ready.is_set():
            self._status_slots = status_slot_percents(status)
            self._status_ready.set()
