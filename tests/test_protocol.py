import pytest

from adaptalux_control.protocol import (
    StatusReassembler,
    byte_to_percent,
    decode_control,
    encode_arms,
    encode_slots,
    percent_to_byte,
    slot_percents_to_arms,
    status_slot_percents,
)


def test_known_bytes_from_capture():
    assert [percent_to_byte(p) for p in (0, 25, 50, 75, 100)] == [
        0xFF,
        0xC0,
        0x80,
        0x40,
        0x00,
    ]


def test_roundtrip():
    for p in range(101):
        assert byte_to_percent(percent_to_byte(p)) == pytest.approx(p, abs=0.5)


def test_out_of_range_refused():
    for bad in (-5, 100.01, 150, float("nan")):
        with pytest.raises(ValueError):
            percent_to_byte(bad)
    with pytest.raises(ValueError):
        encode_arms({1: 101})


def test_four_arms_final_packet_from_capture():
    # Final state of the four-arms capture, boost off.
    assert encode_arms({1: 25, 2: 50, 3: 75, 4: 100}).hex() == "7780c0ff400000"


def test_status_boost():
    from adaptalux_control.protocol import status_boost

    assert (
        status_boost(bytes.fromhex("80808080800 0bd00020077".replace(" ", ""))) is False
    )
    assert status_boost(bytes.fromhex("808080808000bd00020177")) is True


def test_boost_flag():
    assert encode_slots([0] * 5, boost=True) == bytes.fromhex("77ffffffffff01")


def test_decode_control():
    slots, boost = decode_control(bytes.fromhex("7780c0ff400000"))
    assert boost is False
    assert slots == pytest.approx([50, 25, 0, 75, 100], abs=0.5)
    assert slot_percents_to_arms(slots) == pytest.approx(
        {1: 25, 2: 50, 3: 75, 4: 100, 5: 0}, abs=0.5
    )


def test_status_reassembly():
    r = StatusReassembler()
    full = bytes.fromhex("808080808000aa001b0177")
    assert r.feed(full[:4]) is None
    assert r.feed(full[4:]) == full
    assert status_slot_percents(full) == pytest.approx([50] * 5, abs=0.5)


def test_status_charging_and_battery():
    from adaptalux_control.protocol import status_battery_raw, status_charging

    plugged = bytes.fromhex("8000808080 01 b3 00 02 01 77".replace(" ", ""))
    unplugged = bytes.fromhex("8000808080 00 b3 00 02 01 77".replace(" ", ""))
    assert status_charging(plugged) is True
    assert status_charging(unplugged) is False
    assert status_battery_raw(plugged) == 0xB3


def test_battery_percent_matches_app_readings():
    from adaptalux_control.protocol import battery_percent

    for raw, app in [(179, 66), (178, 65), (171, 54), (170, 53), (155, 32)]:
        assert abs(battery_percent(raw) - app) <= 1
    assert battery_percent(0) == 0 and battery_percent(255) == 100
