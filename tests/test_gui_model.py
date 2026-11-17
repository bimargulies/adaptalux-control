import pytest

from adaptalux_control.gui import model
from adaptalux_control.gui.model import ArmSetting, PodSetting


def sample() -> PodSetting:
    s = PodSetting(boost=True)
    s.arms[1] = ArmSetting("led", 30)
    s.arms[2] = ArmSetting("flash", level=3)
    return s


def test_lighting_maps_modes_to_port_levels():
    lighting = sample().lighting()
    assert lighting.arms == {1: 30, 2: 100, 3: 0, 4: 0, 5: 0}
    assert lighting.boost


def test_roundtrip():
    back = model.load(model.dump({"fred": sample()}))
    assert back == {"fred": sample()}
    assert back["fred"].flash_levels() == {2: 3}
    assert back["fred"].led_arms() == [1]


def test_bad_values_refused():
    with pytest.raises(ValueError):
        ArmSetting("led", 101)
    with pytest.raises(ValueError):
        ArmSetting("flash", level=6)
    with pytest.raises(ValueError):
        ArmSetting("strobe")
    with pytest.raises(ValueError):
        model.load("pods: {x: {arms: {9: {mode: led}}}}")
