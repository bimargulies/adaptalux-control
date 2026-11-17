import asyncio

import pytest

from adaptalux_control import registry as reg
from adaptalux_control.pod import Pod
from adaptalux_control.registry import PodRegistry, UnknownPod, identify_pods


def test_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "sub" / "pods.yaml"
    assert PodRegistry.load(path).pods == {}
    r = PodRegistry(path=path)
    r.add("bench", "AAA")
    r.add("studio", "BBB")
    r.save()
    assert PodRegistry.load(path).pods == {"bench": "AAA", "studio": "BBB"}
    assert "pods:" in path.read_text()


def test_unknown_label_and_conflicts():
    r = PodRegistry({"bench": "AAA"})
    with pytest.raises(UnknownPod, match="known: bench"):
        r.address("nope")
    with pytest.raises(ValueError):
        r.add("bench", "BBB")  # label already used by another pod
    r.add("desk", "AAA")  # relabel the same pod
    assert r.pods == {"desk": "AAA"}


def test_bad_file_rejected(tmp_path):
    p = tmp_path / "pods.yaml"
    p.write_text("pods: [1, 2]\n")
    with pytest.raises(ValueError):
        PodRegistry.load(p)


def test_connect_label_and_address_are_exclusive(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(Pod.connect(label="a", address="b"))
    with pytest.raises(UnknownPod):
        asyncio.run(Pod.connect(label="a", registry_path=tmp_path / "none.yaml"))


def test_identify_flow(tmp_path, monkeypatch):
    winked, answers = [], iter(["bench", "", "studio"])

    class FakePod:
        def __init__(self, address):
            self.address = address

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def wink(self):
            winked.append(self.address)

    async def fake_scan(timeout=10.0):
        return ["AAA", "BBB", "CCC", "DDD"]

    async def fake_connect(*, address, **kw):
        return FakePod(address)

    monkeypatch.setattr(reg, "scan_pods", fake_scan)
    monkeypatch.setattr(Pod, "connect", staticmethod(fake_connect))
    path = tmp_path / "pods.yaml"
    r = PodRegistry({"old": "DDD"}, path)
    asyncio.run(identify_pods(r, ask=lambda _p: next(answers), say=lambda _m: None))
    assert winked == ["AAA", "BBB", "CCC"]  # DDD already labelled
    assert PodRegistry.load(path).pods == {
        "bench": "AAA",
        "studio": "CCC",
        "old": "DDD",
    }


def test_str_subclass_address_saves(tmp_path):
    # bleak on macOS returns addresses as objc.pyobjc_unicode, a str subclass.
    class FakeObjcStr(str):
        pass

    reg = PodRegistry(path=tmp_path / "pods.yaml")
    reg.add("fred", FakeObjcStr("4208732D-47D9-1A99-83FC-591CAB731BB5"))
    reg.save()
    assert PodRegistry.load(tmp_path / "pods.yaml").address("fred") == (
        "4208732D-47D9-1A99-83FC-591CAB731BB5"
    )
