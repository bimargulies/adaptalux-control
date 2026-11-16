"""Known UUIDs and commands for the Adaptalux Control Pod (see CLAUDE.md)."""

DEVICE_NAME = "Adaptalux3"
SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # pod -> host (notify)
RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"  # host -> pod (write)

CMD_STATUS = bytes([0x23])
CMD_START = bytes([0x24])
NO_CHANGE = 0xFF


def brightness_cmd(levels: list[int | None], last: int = 0x00) -> bytes:
    """Build `77 p1..p5 last`. A level of None leaves that port unchanged;
    otherwise the byte sent is 0x80 | level (hypothesis, unconfirmed)."""
    assert len(levels) == 5
    body = bytes(NO_CHANGE if v is None else (0x80 | v) for v in levels)
    return bytes([0x77]) + body + bytes([last])
