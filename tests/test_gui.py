import asyncio
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from test_pod import FakeClient

from adaptalux_control.gui import model
from adaptalux_control.gui.app import MainWindow
from adaptalux_control.gui.model import ArmSetting, PodSetting
from adaptalux_control.pod import Pod
from adaptalux_control.registry import PodRegistry

app = QApplication.instance() or QApplication([])


async def settle():
    for _ in range(5):
        await asyncio.sleep(0.1)


def window(tmp_path, last_config=None):
    clients: dict[str, FakeClient] = {}
    settings = QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat)
    if last_config:
        settings.setValue("last_config", str(last_config))

    async def connector(label):
        clients[label] = FakeClient()
        pod = Pod(clients[label], keepalive_interval=None)
        await pod._open()
        return pod

    reg = PodRegistry({"fred": "x", "george": "y"})
    return MainWindow(reg, connector, settings), clients


def test_led_slider_sends_and_standby_restores(tmp_path):
    async def go():
        w, clients = window(tmp_path)
        await settle()
        fred = w.panels["fred"]
        assert fred.pod is not None
        row = fred.rows[1]
        row.mode_buttons["led"].click()
        row.slider.setValue(25)
        await settle()
        assert clients["fred"].writes[-1].hex() == "7780c080808000"
        w.standby_button.click()
        await settle()
        assert (
            clients["fred"].writes[-1].hex() == "7780ff80808000"
        )  # arm 1 dark, others untouched
        assert not fred.rows[1].isEnabled()
        w.standby_button.click()
        await settle()
        assert clients["fred"].writes[-1].hex() == "7780c080808000"
        assert fred.rows[1].isEnabled()
        await w.panels["fred"].close()
        await w.panels["george"].close()

    asyncio.run(go())


def test_resume_while_dropped_unlocks_and_relights_on_reconnect(tmp_path):
    async def go():
        w, clients = window(tmp_path)
        await settle()
        george = w.panels["george"]
        george.rows[1].mode_buttons["led"].click()
        george.rows[1].slider.setValue(25)
        await settle()
        w.standby_button.click()
        await settle()
        assert clients["george"].writes[-1].hex() == "7780ff80808000"
        clients["george"].is_connected = False  # link drops during standby
        george._check_link()
        await settle()
        w.standby_button.click()  # Resume while george is away
        await settle()
        assert not george.standby
        w.reconnect_all()
        await settle()
        assert george.pod is not None
        assert george.rows[1].isEnabled() and george.boost.isEnabled()
        assert clients["george"].writes[-1].hex() == "7780c080808000"
        for panel in w.panels.values():
            await panel.close()

    asyncio.run(go())


def test_restore_during_standby_unlocks_controls(tmp_path, monkeypatch):
    path = tmp_path / "lights.yaml"
    setting = PodSetting()
    setting.arms[1] = ArmSetting("led", 60)
    path.write_text(model.dump({"fred": setting}))
    monkeypatch.setattr(
        "adaptalux_control.gui.app.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(path), ""),
    )

    async def go():
        w, _clients = window(tmp_path)
        await settle()
        fred = w.panels["fred"]
        fred.rows[1].mode_buttons["led"].click()
        await settle()
        w.standby_button.click()
        await settle()
        assert not fred.rows[1].isEnabled()
        w.restore_configuration()
        await settle()
        assert fred.rows[1].isEnabled() and not fred.standby
        for panel in w.panels.values():
            await panel.close()

    asyncio.run(go())


def test_flash_needs_boost_then_pulses(tmp_path):
    async def go():
        w, clients = window(tmp_path)
        await settle()
        p = w.panels["george"]
        p.rows[2].mode_buttons["flash"].click()
        p.rows[2].flash_buttons[2].click()
        await settle()
        assert "need Boost" in p.activity.text()
        p.boost.setChecked(True)
        p.rows[2].flash_buttons[1].click()
        await asyncio.sleep(1.2)  # level 1 pulse ~0.5 s
        sevens = [w_ for w_ in clients["george"].writes if w_[0] == 0x77]
        assert 0x8D in [x[1] for x in sevens]
        assert sevens[-1][1] == 0x00 and sevens[-1][-1] == 1
        for panel in w.panels.values():
            await panel.close()

    asyncio.run(go())


def test_last_configuration_sets_modes_without_sending(tmp_path):
    saved = PodSetting()
    saved.arms[1] = ArmSetting("flash", level=3)
    saved.arms[2] = ArmSetting("led", 70)
    path = tmp_path / "last.yaml"
    path.write_text(model.dump({"george": saved}))

    async def go():
        w, clients = window(tmp_path, path)
        await settle()
        george, fred = w.panels["george"], w.panels["fred"]
        assert george.rows[1].mode == "flash" and george.rows[1].level == 3
        assert george.rows[2].mode == "led"
        assert george.rows[2].slider.value() == 50  # brightness comes from the pod
        assert fred.rows[1].mode == "empty"
        assert [x for x in clients["george"].writes if x[0] == 0x77] == []
        for panel in w.panels.values():
            await panel.close()

    asyncio.run(go())


def test_untouched_pods_are_not_saved(tmp_path, monkeypatch):
    saved_to = tmp_path / "out.yaml"
    monkeypatch.setattr(
        "adaptalux_control.gui.app.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(saved_to), ""),
    )

    async def go():
        w, _ = window(tmp_path)
        await settle()
        w.panels["fred"].rows[1].mode_buttons["led"].click()
        w.save_configuration()
        assert list(model.load(saved_to.read_text())) == ["fred"]
        assert w._settings.value("last_config") == str(saved_to)
        for panel in w.panels.values():
            await panel.close()

    asyncio.run(go())


def test_dropped_link_offers_connect_again(tmp_path):
    async def go():
        w, clients = window(tmp_path)
        await settle()
        fred = w.panels["fred"]
        fred._say("BleakError: disconnected", error=True)
        clients["fred"].is_connected = False  # bleak noticed the pod went away
        fred._check_link()
        await settle()
        assert fred.pod is None
        assert "link lost" in fred.status.text()
        assert fred.connect_button.isVisibleTo(fred)
        w.reconnect_all()
        await settle()
        assert fred.pod is not None and fred.pod.is_connected
        assert fred.activity.text() == "reconnected"
        await w.panels["fred"].close()
        await w.panels["george"].close()

    asyncio.run(go())


def test_silent_pod_is_dropped_and_reconnect_all_resets_live_pods(tmp_path):
    async def go():
        w, clients = window(tmp_path)
        await settle()
        fred, george = w.panels["fred"], w.panels["george"]

        async def no_answer(*_a, **_k):
            raise TimeoutError

        fred.pod.read_boost = no_answer  # connected, but the pod stopped replying
        fred._check_link()
        await settle()
        assert fred.pod is not None  # one miss is tolerated
        fred._check_link()
        await settle()
        assert fred.pod is None and "not answering" in fred.status.text()

        old_george = clients["george"]
        w.reconnect_all()
        await settle()
        assert fred.pod is not None and fred.activity.text() == "reconnected"
        assert clients["george"] is not old_george  # a fresh connection
        assert not old_george.is_connected and george.pod.is_connected
        await fred.close()
        await george.close()

    asyncio.run(go())


def test_action_without_a_pod_is_refused_politely(tmp_path):
    async def go():
        w, _clients = window(tmp_path)
        await settle()
        fred = w.panels["fred"]
        await fred.close()  # e.g. dropped while the click waited for the pod
        fred._flash_chosen(1, 3)
        await settle()
        assert fred.activity.text() == "not sent: fred is not connected"
        await w.panels["george"].close()

    asyncio.run(go())


def test_battery_shown_as_percent_with_low_warning(tmp_path):
    async def go():
        w, _clients = window(tmp_path)
        await settle()
        fred = w.panels["fred"]
        assert fred.power.text() == "battery 53 %"  # the fake pod reports 0xaa = 170
        fred.pod.charging = True
        fred._show_power()
        assert fred.power.text() == "battery 53 % · charging"
        fred.pod.charging, fred.pod.battery_raw = False, 140
        fred._show_power()
        assert fred.power.text() == "battery 9 % · low"
        await fred.close()
        fred._enable()
        assert fred.power.text() == ""
        await w.panels["george"].close()

    asyncio.run(go())
