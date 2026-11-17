"""A lighting configuration: every arm's brightness, and boost."""

from dataclasses import dataclass

from .protocol import ARM_TO_SLOT, check_percent


@dataclass(frozen=True)
class Lighting:
    """Brightness (0-100 %) of arms 1-5, and the global boost flag.

    Flash arm levels are not part of this: the pod cannot report them. The object
    is plain data (``dataclasses.asdict`` turns it into a dict), so the caller
    decides whether to keep it in memory or write it somewhere.
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
