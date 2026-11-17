import asyncio
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from test_pod import FakeClient

from adaptalux_control.gui.app import MainWindow
from adaptalux_control.pod import Pod
from adaptalux_control.registry import PodRegistry

app = QApplication.instance() or QApplication([])


async def settle():
    for _ in range(5):
        await asyncio.sleep(0.1)


def window():
    clients: dict[str, FakeClient] = {}

    async def connector(label):
        clients[label] = FakeClient()
        pod = Pod(clients[label], keepalive_interval=None)
        await pod._open()
        return pod

    reg = PodRegistry({"fred": "x", "george": "y"})
    return MainWindow(reg, connector), clients


def test_led_slider_sends_and_standby_restores():
    async def go():
        w, clients = window()
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


def test_flash_needs_boost_then_pulses():
    async def go():
        w, clients = window()
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
