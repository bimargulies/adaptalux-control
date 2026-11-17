"""Pure encoding/decoding for the Adaptalux Control Pod wire protocol.

No Bluetooth here, so everything is unit-testable.

Control packet, written to the RX characteristic:

    77 c0 c1 c2 c3 c4 FLAG

* ``c0..c4`` are the five arm slots, one byte each. The byte is INVERTED:
  0xFF = 0 % (off), 0x80 = 50 %, 0x40 = 75 %, 0x00 = 100 %. Every packet sets
  all five slots; there is no "leave unchanged" value.
* ``FLAG`` is the global boost switch: 0x01 on, 0x00 off. It applies to every
  arm at once.

Slot byte -> arm number (arm numbers are the iPhone app's layout, looking at the
pod's holes: arms 1 and 2 on the top row, 3, 4 and 5 on the bottom row):

    arm 1 = c1   arm 2 = c0
    arm 3 = c3   arm 4 = c4   arm 5 = c2

Flash arms (Gen 2) take their power level (1-5) as a timed pulse on the arm's
slot byte instead of a byte value; see ``FLASH_LEVEL_SECONDS``.

The status reply to ``23`` is 11 bytes and may arrive split over several
notifications. Its first five bytes are the slot bytes in the same encoding
(an empty port reports 0x80). Byte 9 is the boost flag. The other bytes are not
decoded.
"""

from collections.abc import Mapping, Sequence

HEADER = 0x77
SLOT_COUNT = 5
PACKET_LEN = 7
STATUS_LEN = 11
STATUS_BOOST_INDEX = 9  # 00 = boost off, 01 = boost on

# Flash arm power level 1..5. The arm's slot byte is pulsed: 0xFF (about 0.2 s), then
# FLASH_PULSE_BYTE for a level-dependent time, then 0x00 (100 %, where flash arms
# must be left). FLASH_LEVEL_SECONDS is that time, from the first pulse write to
# the first 0x00 write. Each step is written two or three times, as the app does.
FLASH_PULSE_BYTE = 0x8D
FLASH_LEVEL_SECONDS = {1: 0.52, 2: 0.76, 3: 1.03, 4: 1.30, 5: 1.58}

# App arm number (1-based) -> index of its slot byte within the five slot bytes.
ARM_TO_SLOT = {1: 1, 2: 0, 3: 3, 4: 4, 5: 2}


def check_percent(percent: float) -> float:
    """Return `percent` if it is within 0..100, else raise ValueError.

    Nothing above 100 % is ever sent to the pod, and out-of-range values are
    refused rather than silently clamped.
    """
    if not 0.0 <= percent <= 100.0:  # also rejects NaN
        raise ValueError(f"brightness must be between 0 and 100 %, got {percent}")
    return percent


def percent_to_byte(percent: float) -> int:
    """0..100 % -> wire byte (inverted). Raises ValueError outside 0..100."""
    percent = check_percent(percent)
    return min(0xFF, round(2.56 * (100.0 - percent)))


def byte_to_percent(value: int) -> float:
    """Wire byte -> percent. 0xFF is exactly 0 %."""
    if value >= 0xFF:
        return 0.0
    return min(100.0, (256 - value) / 2.56)


def encode_slots(slot_percents: Sequence[float], boost: bool = False) -> bytes:
    """Build a control packet from five slot percentages (wire order).

    ``boost`` is the global boost flag; it applies to all arms.
    """
    if len(slot_percents) != SLOT_COUNT:
        raise ValueError(f"need {SLOT_COUNT} slot values, got {len(slot_percents)}")
    body = bytes(percent_to_byte(p) for p in slot_percents)
    return bytes([HEADER]) + body + bytes([1 if boost else 0])


def encode_arms(arm_percents: Mapping[int, float], boost: bool = False) -> bytes:
    """Build a control packet from {arm number: percent}; other arms are 0 %.

    ``boost`` is the global boost flag; it applies to all arms.
    """
    slots = [0.0] * SLOT_COUNT
    for arm, percent in arm_percents.items():
        slots[ARM_TO_SLOT[arm]] = percent
    return encode_slots(slots, boost)


def decode_control(packet: bytes) -> tuple[list[float], bool]:
    """Inverse of :func:`encode_slots`: (five slot percents, global boost flag)."""
    if len(packet) != PACKET_LEN or packet[0] != HEADER:
        raise ValueError(f"not a control packet: {packet.hex(' ')}")
    return [byte_to_percent(b) for b in packet[1:6]], bool(packet[6])


def slot_percents_to_arms(slots: Sequence[float]) -> dict[int, float]:
    """Reorder five wire-order slot percents into {arm number: percent}."""
    return {arm: slots[slot] for arm, slot in ARM_TO_SLOT.items()}


class StatusReassembler:
    """The 11-byte status reply may arrive split over several notifications."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> bytes | None:
        """Add a notification; return the full status once 11 bytes arrived."""
        self._buf += data
        if len(self._buf) < STATUS_LEN:
            return None
        status = bytes(self._buf[:STATUS_LEN])
        self._buf.clear()
        return status


def status_slot_percents(status: bytes) -> list[float]:
    """Current slot percents (wire order) from a status reply."""
    if len(status) != STATUS_LEN:
        raise ValueError(f"status must be {STATUS_LEN} bytes, got {len(status)}")
    return [byte_to_percent(b) for b in status[:SLOT_COUNT]]


def status_boost(status: bytes) -> bool:
    """Whether the pod reports boost as on, from a status reply."""
    if len(status) != STATUS_LEN:
        raise ValueError(f"status must be {STATUS_LEN} bytes, got {len(status)}")
    return bool(status[STATUS_BOOST_INDEX])
