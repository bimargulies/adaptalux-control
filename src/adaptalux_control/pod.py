"""Async client for the Adaptalux Control Pod 3.0, built on bleak."""

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
    status_boost,
    status_slot_percents,
)
from .registry import PodRegistry

RAMP_STEP_S = 0.06  # the iPhone app sends a packet about every 60 ms
KEEPALIVE_S = 30.0  # how often a session asks the pod for status

log = logging.getLogger(__name__)


class PodNotFound(Exception):
    pass


class BoostOff(ValueError):
    """The pod's boost is off, but the operation needs it on (flash arms)."""


class Pod:
    """A session with one pod, from ``connect`` until ``close``.

        async with await Pod.connect(label="bench") as pod:
            await pod.set_arms({1: 25, 2: 50})
            await pod.ramp({1: 0}, duration=2)
            await pod.set_boost(True)
            await pod.set_flash_level(2, 3)

    Before connecting, close the iPhone app (a pod talks to one device at a time)
    and put the pod in Bluetooth mode (hold its top button until the blue light
    flashes).

    Arms are numbered 1-5 as in the iPhone app (see ``protocol``). Brightness is
    0-100 %; anything outside that raises ValueError and is never sent. The pod
    can't be told to leave an arm unchanged, so this object remembers every
    arm's level (adopted from the pod when you connect) and resends all five each
    time. Unplugged arms report 50 %; that value is sent back to them harmlessly.

    Boost is a single global flag that brightens every arm. It is adopted from the
    pod at connect, so ordinary commands preserve it; ``read_boost`` re-reads it.

    While the session is open it asks the pod for its status every
    ``keepalive_interval`` seconds (default 30; ``None`` turns this off).
    ``status_age`` is the time since the pod last answered, and
    ``keepalive_error`` holds the exception if a keepalive write failed, which
    usually means the link is gone.
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
        self._status_boost: bool | None = None
        self._status_waiter: asyncio.Future[None] | None = None

    # -- connection ---------------------------------------------------------

    @classmethod
    async def connect(
        cls,
        *,
        address: str | None = None,
        label: str | None = None,
        registry_path: Path | None = None,
        timeout: float = 10.0,
        keepalive_interval: float | None = KEEPALIVE_S,
    ) -> Self:
        """Find a pod and open a session.

        Pick the pod by ``label`` (from this Mac's pod registry, see
        :mod:`adaptalux_control.registry`), by ``address``, or neither to take the
        first pod found. With more than one pod advertising, use a label: the
        unlabelled form could pick either. Raises PodNotFound if it is not seen
        within ``timeout`` seconds.
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
                    d.name == DEVICE_NAME or SERVICE_UUID in (adv.service_uuids or [])
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
        """Open like the iPhone app: 23 (status), then 24."""
        await self._write(CMD_STATUS)
        try:
            await asyncio.wait_for(self._status_ready.wait(), timeout=2.0)
            assert self._status_slots is not None
            self._slots = list(self._status_slots)  # adopt the pod's current state
            if self._status_boost is not None:
                self._boost = self._status_boost  # and its boost, so we don't flip it
        except TimeoutError:
            pass  # no answer: assume all arms off, boost off
        await self._write(CMD_START)
        await self._write(CMD_START)

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
        """Last known brightness of each arm in percent, {1: ..., ..., 5: ...}."""
        return slot_percents_to_arms(self._slots)

    @property
    def status_age(self) -> float | None:
        """Seconds since the pod last sent a status reply (None: never)."""
        if self._last_status_time is None:
            return None
        return time.monotonic() - self._last_status_time

    @property
    def boost(self) -> bool:
        """Last known state of the global boost flag."""
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
        """Set a Gen 2 flash arm's power level, 1 (shortest flash) to 5 (most power).

        The level is sent as a timed pulse on the arm's slot, and the arm's port is
        left at 100 % power, which flash arms need; you do not set that yourself.
        Flash arms also need boost: this reads the pod's actual boost state first
        and raises :class:`BoostOff` without sending anything if it is off (turn it
        on with ``set_boost(True)``). Also raises ValueError for a bad arm or level.

        Returns once the pulse is sent; the arm's lights then show it reaching the
        level, which is near-instant for small changes but can take up to about a
        minute for a big jump up. The pod cannot report a flash arm's level, so
        remember what you set. Do not use this on LED arms.
        """
        if arm not in ARM_TO_SLOT:
            raise ValueError(f"no such arm {arm}; arms are 1-{SLOT_COUNT}")
        if level not in FLASH_LEVEL_SECONDS:
            raise ValueError(f"flash level must be 1-5, got {level!r}")
        if not await self.read_boost():
            raise BoostOff("flash arms need boost: call set_boost(True) first")
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
        """Set all five arms to the same brightness."""
        await self.set_arms({arm: percent for arm in ARM_TO_SLOT})

    async def wink(self, times: int = 3, on: float = 0.35, off: float = 0.25) -> None:
        """Flash all arms so a person can see which pod this is.

        Only plugged-in arms visibly light. Levels are restored afterwards and the
        boost flag is not touched. Do not use this with flash arms plugged in.
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

    async def set_boost(self, on: bool) -> None:
        """Turn the global boost on or off. It affects every arm at once."""
        self._boost = on
        await self._send_state()

    async def read_boost(self, timeout: float = 2.0) -> bool:
        """Ask the pod whether boost is on, and remember the answer.

        This notices boost being changed at the pod itself. Raises TimeoutError if
        the pod does not answer.
        """
        waiter = asyncio.get_running_loop().create_future()
        self._status_waiter = waiter
        try:
            await self._write(CMD_STATUS)
            await asyncio.wait_for(waiter, timeout)
        finally:
            self._status_waiter = None
        assert self._status_boost is not None
        self._boost = self._status_boost
        return self._boost

    async def ramp(
        self,
        targets: dict[int, float],
        duration: float = 1.0,
        step: float = RAMP_STEP_S,
    ) -> None:
        """Move arms linearly to their target brightness over ``duration`` seconds.

        Targets outside 0..100 % raise ValueError before anything is sent. Do not
        use this on flash arms.
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
        self._status_boost = status_boost(status)
        if self._status_waiter is not None and not self._status_waiter.done():
            self._status_waiter.set_result(None)
        self._last_status_time = time.monotonic()
        log.debug("status: %s", status.hex(" "))
        if not self._status_ready.is_set():
            self._status_slots = status_slot_percents(status)
            self._status_ready.set()
