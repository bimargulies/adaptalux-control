"""What the GUI shows for each pod, and its save file. No Qt here."""

from dataclasses import dataclass, field

import yaml

from ..lighting import Lighting
from ..protocol import ARM_TO_SLOT, check_percent

MODES = ("empty", "led", "flash")


@dataclass
class ArmSetting:
    """One arm's port: what is plugged in, and its brightness or flash level.

    ``level`` is None until a flash level has been chosen: the pod cannot report it.
    """

    mode: str = "empty"
    percent: float = 0.0
    level: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        check_percent(self.percent)
        if self.level is not None and self.level not in range(1, 6):
            raise ValueError(f"flash level must be 1-5, got {self.level!r}")


@dataclass
class PodSetting:
    boost: bool = False
    arms: dict[int, ArmSetting] = field(
        default_factory=lambda: {arm: ArmSetting() for arm in sorted(ARM_TO_SLOT)}
    )

    def lighting(self) -> Lighting:
        """Port levels: empty = 0 %, LED = its brightness, flash = 100 %."""
        levels = {
            arm: {"empty": 0.0, "led": a.percent, "flash": 100.0}[a.mode]
            for arm, a in self.arms.items()
        }
        return Lighting(levels, self.boost)

    def flash_levels(self) -> dict[int, int]:
        return {
            arm: a.level
            for arm, a in self.arms.items()
            if a.mode == "flash" and a.level is not None
        }

    def led_arms(self) -> list[int]:
        return [arm for arm, a in self.arms.items() if a.mode == "led"]


def dump(settings: dict[str, PodSetting]) -> str:
    pods = {}
    for label, pod in settings.items():
        arms = {}
        for arm, a in pod.arms.items():
            entry: dict = {"mode": a.mode}
            if a.mode == "led":
                entry["percent"] = round(a.percent, 1)
            elif a.mode == "flash" and a.level is not None:
                entry["level"] = a.level
            arms[arm] = entry
        pods[label] = {"boost": pod.boost, "arms": arms}
    return yaml.safe_dump({"pods": pods}, sort_keys=True)


def load(text: str) -> dict[str, PodSetting]:
    data = yaml.safe_load(text) or {}
    out: dict[str, PodSetting] = {}
    for label, pod in (data.get("pods") or {}).items():
        setting = PodSetting(boost=bool(pod.get("boost", False)))
        for arm, entry in (pod.get("arms") or {}).items():
            if int(arm) not in ARM_TO_SLOT:
                raise ValueError(f"{label}: no such arm {arm}")
            setting.arms[int(arm)] = ArmSetting(
                mode=entry.get("mode", "empty"),
                percent=float(entry.get("percent", 0.0)),
                level=entry.get("level"),
            )
        out[str(label)] = setting
    return out
