"""The window: one section per pod, a standby button, and menus."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..lighting import Lighting
from ..pod import BoostOff, Pod, PodNotFound
from ..protocol import ARM_TO_SLOT
from ..registry import PodRegistry, scan_pods
from . import model
from .model import ArmSetting, PodSetting

CONFIG_DIR = Path.home() / ".config" / "adaptalux-control"
LED_SEND_INTERVAL = 0.06  # seconds between brightness packets while a slider moves
STYLE = "QPushButton:checked { background: #3478f6; color: white; }"

Connector = Callable[[str], Awaitable[Pod]]


def _segment(text: str, width: int) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setFixedSize(width, 24)
    button.setStyleSheet(STYLE)
    return button


class ArmRow(QWidget):
    """One arm: a three-way switch (empty / LED / flash) and its control."""

    modeChanged = Signal(int, str)
    ledChanged = Signal(int, float)
    flashChosen = Signal(int, int)

    def __init__(self, arm: int) -> None:
        super().__init__()
        self.arm = arm
        self.level: int | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"{arm}"))

        self.mode_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for mode, text in (("empty", "Empty"), ("led", "LED"), ("flash", "Flash")):
            button = _segment(text, 46)
            group.addButton(button)
            button.clicked.connect(partial(self._pick, mode))
            layout.addWidget(button)
            self.mode_buttons[mode] = button
        self.mode_buttons["empty"].setChecked(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(QWidget())  # empty: nothing to control
        led = QWidget()
        led_layout = QHBoxLayout(led)
        led_layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.percent_label = QLabel("0%")
        self.percent_label.setFixedWidth(36)
        self.slider.valueChanged.connect(self._slid)
        led_layout.addWidget(self.slider)
        led_layout.addWidget(self.percent_label)
        self.stack.addWidget(led)
        flash = QWidget()
        flash_layout = QHBoxLayout(flash)
        flash_layout.setContentsMargins(0, 0, 0, 0)
        flash_layout.setSpacing(2)
        self.flash_group = QButtonGroup(self)
        self.flash_buttons: dict[int, QPushButton] = {}
        for level in range(1, 6):
            button = _segment(str(level), 26)
            self.flash_group.addButton(button)
            button.clicked.connect(partial(self._flash, level))
            flash_layout.addWidget(button)
            self.flash_buttons[level] = button
        self.stack.addWidget(flash)
        layout.addWidget(self.stack, 1)

    @property
    def mode(self) -> str:
        return next(m for m, b in self.mode_buttons.items() if b.isChecked())

    def _pick(self, mode: str) -> None:
        self.stack.setCurrentIndex(("empty", "led", "flash").index(mode))
        self.modeChanged.emit(self.arm, mode)

    def _slid(self, value: int) -> None:
        self.percent_label.setText(f"{value}%")
        self.ledChanged.emit(self.arm, float(value))

    def _flash(self, level: int) -> None:
        self.level = level
        self.flashChosen.emit(self.arm, level)

    def setting(self) -> ArmSetting:
        return ArmSetting(self.mode, float(self.slider.value()), self.level)

    def show_setting(self, setting: ArmSetting) -> None:
        """Update the widgets without sending anything."""
        for widget in (self.slider, *self.mode_buttons.values()):
            widget.blockSignals(True)
        self.mode_buttons[setting.mode].setChecked(True)
        self.slider.setValue(round(setting.percent))
        self.percent_label.setText(f"{round(setting.percent)}%")
        self.stack.setCurrentIndex(("empty", "led", "flash").index(setting.mode))
        self.level = setting.level
        self.flash_group.setExclusive(False)
        for level, button in self.flash_buttons.items():
            button.setChecked(level == setting.level)
        self.flash_group.setExclusive(True)
        for widget in (self.slider, *self.mode_buttons.values()):
            widget.blockSignals(False)


class PodPanel(QGroupBox):
    """One pod: connection, boost, and five arm rows."""

    def __init__(
        self, label: str, connector: Connector, initial: PodSetting | None = None
    ) -> None:
        super().__init__(label)
        self.label = label
        self._initial = initial  # arm modes remembered from a saved file
        self.touched = False  # True once the user has configured this pod
        self._connector = connector
        self.pod: Pod | None = None
        self.standby = False
        self._saved: Lighting | None = None
        self._lock = asyncio.Lock()  # one pod operation at a time
        self._pending: dict[int, float] = {}
        self._flusher: asyncio.Future | None = None
        self._tasks: set[asyncio.Future] = set()

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.boost = QCheckBox("Boost")
        self.boost.toggled.connect(self._boost_toggled)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.start)
        top.addWidget(self.boost)
        top.addWidget(self.status, 1)
        top.addWidget(self.connect_button)
        layout.addLayout(top)
        self.activity = QLabel("")
        self.activity.setWordWrap(True)
        self.activity.setMinimumHeight(24)
        self.activity_box = QFrame()
        self.activity_box.setFrameShape(QFrame.Shape.StyledPanel)
        box_layout = QVBoxLayout(self.activity_box)
        box_layout.setContentsMargins(6, 2, 6, 2)
        box_layout.addWidget(self.activity)
        layout.addWidget(self.activity_box)

        self.rows: dict[int, ArmRow] = {}
        for arm in sorted(ARM_TO_SLOT):
            row = ArmRow(arm)
            row.modeChanged.connect(self._mode_changed)
            row.ledChanged.connect(self._led_changed)
            row.flashChosen.connect(self._flash_chosen)
            layout.addWidget(row)
            self.rows[arm] = row

        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_link)
        self._watch.start(3000)
        self._enable()

    # -- plumbing -------------------------------------------------------------

    def _spawn(self, coro: Awaitable) -> asyncio.Future:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Future) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()):
            self._say(f"{type(exc).__name__}: {exc}", error=True)

    def _say(self, text: str, error: bool = False) -> None:
        """The last thing that happened, in the box under the controls."""
        self.activity.setStyleSheet("color: #d33;" if error else "")
        self.activity.setText(text)

    def _link(self, text: str, error: bool = False) -> None:
        """The connection state, always visible at the top."""
        self.status.setStyleSheet("color: #d33;" if error else "")
        self.status.setText(text)

    def _enable(self) -> None:
        live = self.pod is not None and not self.standby
        self.boost.setEnabled(live)
        for row in self.rows.values():
            row.setEnabled(live)
        self.connect_button.setVisible(self.pod is None)

    # -- connection -----------------------------------------------------------

    def start(self) -> None:
        if self.pod is None and not self._tasks:
            self._spawn(self._connect())

    async def _connect(self) -> None:
        self.connect_button.setEnabled(False)
        self._link("connecting…")
        try:
            self.pod = await self._connector(self.label)
        except PodNotFound:
            self._link("not found: is it in Bluetooth mode?", error=True)
            return
        finally:
            self.connect_button.setEnabled(True)
        self.boost.blockSignals(True)
        self.boost.setChecked(self.pod.boost)
        self.boost.blockSignals(False)
        self._link("connected")
        self._adopt_initial()
        self._enable()

    def _adopt_initial(self) -> None:
        """Show the remembered arm modes. Nothing is sent to the pod.

        The pod can't say what is plugged in, so modes and flash levels come from
        the file; LED brightness and boost come from the pod itself.
        """
        initial, self._initial = self._initial, None
        if initial is None or self.pod is None:
            return
        for arm, row in self.rows.items():
            saved = initial.arms[arm]
            row.show_setting(ArmSetting(saved.mode, self.pod.arms[arm], saved.level))
        self.touched = any(a.mode != "empty" for a in initial.arms.values())

    def _check_link(self) -> None:
        if self.pod is not None and self.pod.keepalive_error is not None:
            self._link("link lost", error=True)
            self._tasks.add(task := asyncio.ensure_future(self.pod.close()))
            task.add_done_callback(self._tasks.discard)
            self.pod = None
            self._enable()
        elif self.pod is not None and not self._lock.locked() and not self._tasks:
            self._spawn(self._sync_boost())

    async def _sync_boost(self) -> None:
        """Follow boost changes made at the pod itself."""
        async with self._lock:
            if self.pod is None or self.standby:
                return
            on = await self.pod.read_boost()
        if on != self.boost.isChecked():
            self.boost.blockSignals(True)
            self.boost.setChecked(on)
            self.boost.blockSignals(False)

    async def close(self) -> None:
        self._watch.stop()
        if self._flusher is not None:
            self._flusher.cancel()
        if self.pod is not None:
            await self.pod.close()
            self.pod = None

    # -- user actions ---------------------------------------------------------

    def _boost_toggled(self, on: bool) -> None:
        self.touched = True

        async def go() -> None:
            async with self._lock:
                await self.pod.set_boost(on)

        if self.pod is not None:
            self._spawn(go())

    def _mode_changed(self, arm: int, mode: str) -> None:
        self.touched = True
        if mode == "empty":
            self._queue_led(arm, 0.0)
        elif mode == "led":
            self._queue_led(arm, self.rows[arm].slider.value())
        else:  # a flash port must sit at 100 %; the level is chosen separately
            self._queue_led(arm, 100.0)

    def _led_changed(self, arm: int, percent: float) -> None:
        self._queue_led(arm, percent)

    def _queue_led(self, arm: int, percent: float) -> None:
        self.touched = True
        if self.pod is None:
            return
        self._pending[arm] = percent
        if self._flusher is None or self._flusher.done():
            self._flusher = self._spawn(self._flush())

    async def _flush(self) -> None:
        while self._pending:
            async with self._lock:
                batch, self._pending = self._pending, {}
                await self.pod.set_arms(batch)
            await asyncio.sleep(LED_SEND_INTERVAL)

    def _flash_chosen(self, arm: int, level: int) -> None:
        self.touched = True

        async def go() -> None:
            async with self._lock:
                try:
                    await self.pod.set_flash_level(arm, level)
                except BoostOff:
                    self._say("flash arms need Boost: turn it on", error=True)
                    return
            self._say(f"arm {arm}: flash level {level}")

        if self.pod is not None:
            self._spawn(go())

    # -- whole-pod operations -------------------------------------------------

    def setting(self) -> PodSetting:
        return PodSetting(
            boost=self.boost.isChecked(),
            arms={arm: row.setting() for arm, row in self.rows.items()},
        )

    async def wink(self) -> None:
        async with self._lock:
            await self.pod.wink()

    async def go_standby(self) -> None:
        """Turn the LED arms off, remembering how they were. Flash arms and boost stay."""
        if self.pod is None or self.standby:
            return
        async with self._lock:
            self._pending.clear()
            self._saved = await self.pod.lights_off(self.setting().led_arms())
            self.standby = True
        self._enable()

    async def resume(self) -> None:
        if self.pod is None or not self.standby:
            return
        async with self._lock:
            await self.pod.restore(self._saved)
            self.standby = False
        self._enable()

    async def apply(self, setting: PodSetting) -> None:
        """Show ``setting`` and send it: boost and LED levels in one packet, then flash levels."""
        self.touched = True
        for arm, row in self.rows.items():
            row.show_setting(setting.arms[arm])
        self.boost.blockSignals(True)
        self.boost.setChecked(setting.boost)
        self.boost.blockSignals(False)
        async with self._lock:
            await self.pod.restore(setting.lighting())
            for arm, level in setting.flash_levels().items():
                await self.pod.set_flash_level(arm, level)


async def ask_text(parent: QWidget, title: str, text: str) -> str:
    """A text prompt that keeps the event loop (and the Bluetooth link) running."""
    dialog = QInputDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(text)
    done: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    dialog.finished.connect(
        lambda result: done.set_result(dialog.textValue().strip() if result else "")
    )
    dialog.open()
    return await done


async def default_connector(label: str) -> Pod:
    return await Pod.connect(label=label)


class MainWindow(QMainWindow):
    def __init__(
        self,
        registry: PodRegistry | None = None,
        connector: Connector = default_connector,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Adaptalux")
        self.registry = registry if registry is not None else PodRegistry.load()
        self._connector = connector
        self.panels: dict[str, PodPanel] = {}
        self._busy: asyncio.Future | None = None
        self._closing = False

        central = QWidget()
        outer = QVBoxLayout(central)
        self.standby_button = QPushButton("Standby")
        self.standby_button.setCheckable(True)
        self.standby_button.setFixedHeight(40)
        self.standby_button.setStyleSheet(
            "QPushButton:checked { background: #d9822b; color: white; }"
        )
        self.standby_button.clicked.connect(self._standby_clicked)
        outer.addWidget(self.standby_button)

        self.pod_area = QVBoxLayout()
        self.pod_area.setAlignment(Qt.AlignmentFlag.AlignTop)
        holder = QWidget()
        holder.setLayout(self.pod_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        self.setCentralWidget(central)
        self.resize(400, 820)
        self._settings = settings or QSettings("adaptalux-control", "gui")
        self._startup = self._load_last_configuration()
        if geometry := self._settings.value("geometry"):
            self.restoreGeometry(geometry)

        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "Save Configuration…", self.save_configuration)
        self._action(file_menu, "Restore Configuration…", self.restore_configuration)
        pods_menu = self.menuBar().addMenu("Pods")
        self._action(pods_menu, "Identify Pods…", self.identify)
        self._action(pods_menu, "Reconnect All", self.reconnect_all)

        self.refresh_panels()

    # -- helpers --------------------------------------------------------------

    def _action(self, menu, text: str, fn: Callable[[], object]) -> None:
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False: fn())
        menu.addAction(action)

    def _say(self, text: str) -> None:
        self.message.setText(text)

    def _run(self, coro: Awaitable) -> None:
        """Run one window-level job at a time, showing any error."""
        if self._busy is not None and not self._busy.done():
            self._say("busy: wait for the current action to finish")
            return
        self._busy = asyncio.ensure_future(coro)
        self._busy.add_done_callback(self._job_done)

    def _job_done(self, task: asyncio.Future) -> None:
        if not task.cancelled() and (exc := task.exception()):
            self._say(f"{type(exc).__name__}: {exc}")

    def refresh_panels(self) -> None:
        for label in sorted(self.registry.pods):
            if label not in self.panels:
                panel = PodPanel(label, self._connector, self._startup.get(label))
                self.panels[label] = panel
                self.pod_area.addWidget(panel)
                panel.start()
        if not self.panels:
            self._say("No pods named yet: use Pods → Identify Pods…")

    def _load_last_configuration(self) -> dict[str, PodSetting]:
        """Arm modes from the file used last time; empty if there is none."""
        name = self._settings.value("last_config")
        if not name:
            return {}
        try:
            settings = model.load(Path(name).read_text())
        except (ValueError, OSError):
            return {}
        self._say(f"arm modes from {name}")
        return settings

    def connected(self) -> list[PodPanel]:
        return [p for p in self.panels.values() if p.pod is not None]

    # -- actions --------------------------------------------------------------

    def _standby_clicked(self, on: bool) -> None:
        async def go() -> None:
            panels = self.connected()
            if on:
                await asyncio.gather(*(p.go_standby() for p in panels))
            else:
                await asyncio.gather(*(p.resume() for p in panels))
            self.standby_button.setText("Resume" if on else "Standby")

        self._run(go())

    def reconnect_all(self) -> None:
        for panel in self.panels.values():
            panel.start()

    def save_configuration(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        name, _ = QFileDialog.getSaveFileName(
            self, "Save configuration", str(CONFIG_DIR / "lights.yaml"), "YAML (*.yaml)"
        )
        if name:
            settings = {
                label: p.setting() for label, p in self.panels.items() if p.touched
            }
            if not settings:
                self._say("nothing to save: no pod has been set up yet")
                return
            Path(name).write_text(model.dump(settings))
            self._settings.setValue("last_config", name)
            self._say(f"saved {name} ({', '.join(sorted(settings))})")

    def restore_configuration(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Restore configuration", str(CONFIG_DIR), "YAML (*.yaml)"
        )
        if not name:
            return
        try:
            settings = model.load(Path(name).read_text())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Restore configuration", str(exc))
            return

        async def go() -> None:
            skipped = []
            jobs = []
            for label, setting in settings.items():
                panel = self.panels.get(label)
                if panel is None or panel.pod is None:
                    skipped.append(label)
                else:
                    jobs.append(panel.apply(setting))
            await asyncio.gather(*jobs)
            self._settings.setValue("last_config", name)
            self._say(
                f"restored {name}"
                + (f"; not connected, skipped: {', '.join(skipped)}" if skipped else "")
            )

        self._run(go())

    def identify(self) -> None:
        async def go() -> None:
            self._say("scanning for unnamed pods…")
            addresses = await scan_pods(8.0)
            fresh = [a for a in addresses if self.registry.label_for(a) is None]
            if not fresh:
                self._say(
                    "no unnamed pods found (a pod in use by this window or a phone does not advertise)"
                )
                return
            for address in fresh:
                async with await Pod.connect(address=address) as pod:
                    await pod.wink()
                    while True:
                        label = await ask_text(
                            self,
                            "Identify pod",
                            "Which pod just winked? Name (blank to skip):",
                        )
                        if not label:
                            break
                        try:
                            self.registry.add(label, address)
                        except ValueError as exc:
                            self._say(str(exc))
                            continue
                        self.registry.save()
                        break
            self.refresh_panels()
            self._say("done")

        self._run(go())

    # -- shutdown -------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        event.ignore()
        self._closing = True
        self._settings.setValue("geometry", self.saveGeometry())

        async def shutdown() -> None:
            await asyncio.gather(
                *(p.close() for p in self.panels.values()), return_exceptions=True
            )
            self.close()

        asyncio.ensure_future(shutdown())


def _name_mac_app(name: str) -> None:
    """Make the macOS menu bar and Dock say ``name`` instead of "Python"."""
    try:
        from Foundation import NSBundle
    except ImportError:
        return
    info = NSBundle.mainBundle().infoDictionary()
    info["CFBundleName"] = name


def main() -> None:
    import qasync

    _name_mac_app("Adaptalux")
    app = QApplication(sys.argv)
    app.setApplicationName("Adaptalux")
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    app.aboutToQuit.connect(stop.set)
    window = MainWindow()
    window.show()
    with loop:
        loop.run_until_complete(stop.wait())
