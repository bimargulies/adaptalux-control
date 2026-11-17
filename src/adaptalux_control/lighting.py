"""A remembered lighting configuration: every arm's brightness, and boost."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from .protocol import ARM_TO_SLOT, check_percent


@dataclass(frozen=True)
class Lighting:
    """Brightness (0-100 %) of arms 1-5, and the global boost flag.

    Flash arm levels are not part of this: the pod cannot report them.
    """

    arms: dict[int, float]
    boost: bool = False

    def __post_init__(self) -> None:
        if set(self.arms) != set(ARM_TO_SLOT):
            raise ValueError(f"arms must be exactly {sorted(ARM_TO_SLOT)}")
        for percent in self.arms.values():
            check_percent(percent)

    @property
    def is_dark(self) -> bool:
        """True if every arm is at 0 %."""
        return all(percent == 0 for percent in self.arms.values())

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"arms": dict(self.arms), "boost": self.boost}
        path.write_text(yaml.safe_dump(data, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "Lighting":
        data = yaml.safe_load(Path(path).read_text())
        try:
            arms = {int(arm): float(percent) for arm, percent in data["arms"].items()}
            return cls(arms, bool(data.get("boost", False)))
        except (AttributeError, KeyError, TypeError) as exc:
            raise ValueError(f"{path}: not a saved lighting file") from exc
