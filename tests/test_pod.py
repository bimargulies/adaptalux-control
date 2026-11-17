import asyncio

import pytest

from adaptalux_control.adaptalux import CMD_START, CMD_STATUS, RX_UUID
from adaptalux_control.lighting import Lighting
from adaptalux_control.pod import BoostOff, Pod


class FakeClient:
    is_connected = True

    def __init__(self):
        self.writes: list[bytes] = []
        self.notify = None
        self.boost = 0  # the fake pod's boost flag, as last written in a 77 packet

    async def connect(self): ...

    async def start_notify(self, _uuid, cb):
        self.notify = cb

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == RX_UUID and response
        self.writes.append(bytes(data))
        if data[0] == 0x77:
            self.boost = data[6]
        if data == CMD_STATUS:
            self.notify(
                None, bytearray.fromhex(f"808080808000aa001b{self.boost:02x}77")
            )

    async def disconnect(self):
        self.is_connected = False


async def make() -> tuple[Pod, FakeClient]:
    c = FakeClient()
    pod = Pod(c)
    await pod._open()
    return pod, c


def test_handshake_and_initial_state():
    async def go():
        pod, c = await make()
        assert c.writes == [CMD_STATUS, CMD_START, CMD_START]
        assert pod.arms == pytest.approx({a: 50 for a in range(1, 6)}, abs=0.5)

    asyncio.run(go())


def test_set_arms_keeps_other_arms():
    async def go():
        pod, c = await make()
        await pod.set_arms({1: 25})
        # arm 1 is wire byte 1; the rest keep the 50 % the pod reported
        assert c.writes[-1].hex() == "7780c080808000"

    asyncio.run(go())


def test_ramp_ends_at_target():
    async def go():
        pod, c = await make()
        await pod.ramp({4: 100}, duration=0.1, step=0.02)
        assert pod.arms[4] == 100
        assert c.writes[-1][5] == 0x00  # arm 4 is wire byte index 3 -> packet[4]

    asyncio.run(go())


def test_boost_and_unknown_arm():
    async def go():
        pod, c = await make()
        await pod.set_boost(True)
        assert c.writes[-1][-1] == 1
        with pytest.raises(ValueError):
            await pod.set_arms({6: 10})

    asyncio.run(go())


def test_refuses_above_100_and_sends_nothing():
    async def go():
        pod, c = await make()
        n = len(c.writes)
        for bad in ({1: 100.5}, {1: 50, 2: 101}, {1: -1}):
            with pytest.raises(ValueError):
                await pod.set_arms(bad)
        with pytest.raises(ValueError):
            await pod.set_all(150)
        with pytest.raises(ValueError):
            await pod.ramp({1: 120}, duration=0.1)
        assert len(c.writes) == n
        assert all(v <= 100 for v in pod.arms.values())

    asyncio.run(go())


def test_wink_restores_levels_and_boost_untouched():
    async def go():
        pod, c = await make()
        await pod.set_arms({1: 40})
        await pod.set_boost(True)
        before = pod.arms
        n = len(c.writes)
        await pod.wink(times=2, on=0, off=0)
        assert pod.arms == before and pod.boost
        assert all(w[-1] == 1 for w in c.writes[n:])  # boost flag kept
        assert c.writes[-1] == c.writes[n - 1]  # last write = original state
        assert len(c.writes) == n + 2 * 2 + 1

    asyncio.run(go())


def test_keepalive_asks_for_status_and_stops_on_close():
    async def go():
        c = FakeClient()
        pod = Pod(c, keepalive_interval=0.02)
        await pod._open()
        n = c.writes.count(CMD_STATUS)
        await asyncio.sleep(0.1)
        assert c.writes.count(CMD_STATUS) >= n + 2
        assert pod.status_age is not None and pod.status_age < 0.05
        await pod.close()
        n = c.writes.count(CMD_STATUS)
        await asyncio.sleep(0.06)
        assert c.writes.count(CMD_STATUS) == n  # task cancelled

    asyncio.run(go())


def test_keepalive_failure_is_recorded_not_raised():
    async def go():
        c = FakeClient()
        pod = Pod(c, keepalive_interval=0.02)
        await pod._open()

        async def boom(*a, **k):
            raise OSError("link lost")

        c.write_gatt_char = boom
        await asyncio.sleep(0.06)
        assert isinstance(pod.keepalive_error, OSError)
        await pod.close()

    asyncio.run(go())


def test_keepalive_can_be_disabled():
    async def go():
        c = FakeClient()
        pod = Pod(c, keepalive_interval=None)
        await pod._open()
        assert pod._keepalive_task is None
        await pod.close()

    asyncio.run(go())


def test_flash_level_sequence(monkeypatch):
    monkeypatch.setattr(
        "adaptalux_control.pod.FLASH_LEVEL_SECONDS",
        {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0},
    )

    async def go():
        pod, c = await make()
        await pod.set_boost(True)
        n = len(c.writes)
        await pod.set_flash_level(2, 3)  # app arm 2 = wire byte 0 = packet[1]
        seq = [w for w in c.writes[n:] if w[0] == 0x77]  # skip the 23 boost check
        assert [p[1] for p in seq] == [0xFF] * 3 + [0x8D] * 2 + [0x00] * 2
        assert all(p[2:] == seq[0][2:] for p in seq)  # other slots and boost unchanged
        assert all(p[-1] == 1 for p in seq)
        assert pod.arms[2] == 100

    asyncio.run(go())


def test_flash_level_refusals():
    async def go():
        pod, c = await make()
        n = len(c.writes)
        with pytest.raises(ValueError):
            await pod.set_flash_level(2, 3)  # boost off
        await pod.set_boost(True)
        n = len(c.writes)
        for arm, level in ((9, 3), (2, 0), (2, 6), (2, 2.5)):
            with pytest.raises(ValueError):
                await pod.set_flash_level(arm, level)
        assert len(c.writes) == n

    asyncio.run(go())


def test_boost_adopted_from_pod_at_connect():
    async def go():
        c = FakeClient()
        c.boost = 1  # pod already has boost on, as george did
        pod = Pod(c)
        await pod._open()
        assert pod.boost is True
        await pod.set_arms({1: 20})
        assert c.writes[-1][-1] == 1  # an ordinary write must not switch it off

    asyncio.run(go())


def test_read_boost_sees_changes_made_at_the_pod():
    async def go():
        pod, c = await make()
        assert await pod.read_boost() is False
        c.boost = 1  # someone presses the pod's own boost control
        assert await pod.read_boost() is True
        assert pod.boost is True

    asyncio.run(go())


def test_flash_level_checks_the_pods_real_boost():
    async def go():
        pod, c = await make()
        await pod.set_boost(True)
        c.boost = 0  # pod's boost goes off behind our back
        n = len([w for w in c.writes if w[0] == 0x77])
        with pytest.raises(BoostOff):
            await pod.set_flash_level(2, 3)
        assert len([w for w in c.writes if w[0] == 0x77]) == n  # no pulse sent

    asyncio.run(go())


def test_lights_off_returns_the_old_state_and_restore_brings_it_back():
    async def go():
        pod, c = await make()
        await pod.set_arms({1: 25, 2: 80})
        await pod.set_boost(True)
        saved = await pod.lights_off()
        assert saved.arms[1] == 25 and saved.arms[2] == 80 and saved.boost
        assert c.writes[-1].hex() == "77ffffffffff01"  # all dark, boost untouched
        await pod.restore(saved)
        assert pod.arms[1] == pytest.approx(25, abs=0.5)
        assert pod.arms[2] == pytest.approx(80, abs=0.5)
        assert pod.boost

    asyncio.run(go())


def test_lights_off_keeps_nothing_itself():
    async def go():
        pod, _ = await make()
        await pod.set_arms({1: 40})
        first = await pod.lights_off()
        second = await pod.lights_off()  # already dark: returns the dark state
        assert first.arms[1] == 40 and second.is_dark and not first.is_dark

    asyncio.run(go())


def test_lights_off_some_arms_and_refusal():
    async def go():
        pod, c = await make()
        await pod.set_all(60)
        await pod.lights_off([2])
        assert pod.arms[2] == 0 and pod.arms[1] == pytest.approx(60, abs=0.5)
        n = len(c.writes)
        with pytest.raises(ValueError):
            await pod.lights_off([9])
        assert len(c.writes) == n

    asyncio.run(go())


def test_lighting_validation():
    with pytest.raises(ValueError):
        Lighting({1: 10}, False)  # needs all five arms
    with pytest.raises(ValueError):
        Lighting({a: 101 for a in range(1, 6)}, False)  # never above 100 %
