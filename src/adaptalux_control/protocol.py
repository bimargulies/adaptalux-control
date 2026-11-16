"""Pure encoding/decoding for the Adaptalux Control Pod wire protocol.

No Bluetooth here, so everything is unit-testable. See CLAUDE.md for how this
was derived from iPhone-app captures.

Control packet, written to the RX characteristic:

    77 c0 c1 c2 c3 c4 FLAG

* ``c0..c4`` are the five arm slots, one byte each. The byte is INVERTED:
  0xFF = 0 % (off), 0x80 = 50 %, 0x40 = 75 %, 0x00 = 100 %. Every packet sets
  all five slots; there is no "leave unchanged" value (an unused slot simply
  sits at 0xFF).
* ``FLAG`` is the *boost* switch: 0x01 on, 0x00 off. Boost is a single GLOBAL
  flag for the whole pod, not per arm: it brightens every arm, at every level.

The status reply to ``23`` is 11 bytes; its first five bytes are the five slot
bytes in the same encoding (0x80 = 50 % on a freshly powered pod).
"""

from collections.abc import Mapping, Sequence

HEADER = 0x77
SLOT_COUNT = 5
PACKET_LEN = 7
STATUS_LEN = 11

# App arm number (1-based, in the order the iPhone app lays them out: arms 1-2
# on the top row, 3-5 on the bottom row) -> index of its slot byte within the
# five slot bytes. Arms 1-4 come from the "four-arms" capture; all five were
# verified by driving real arms (arm 5 -> byte 2: the empty bottom-row slot).
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
