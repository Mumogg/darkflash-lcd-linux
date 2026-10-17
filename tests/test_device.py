import os
from pathlib import Path

import pytest

from darkflash_lcd.device import Device, DeviceError, NotFound, PermissionDenied, find_hidraw


def make_sys(tmp_path: Path, nodes: dict[str, str]) -> Path:
    sys_root = tmp_path / "sys"
    for name, hid_id in nodes.items():
        d = sys_root / "class" / "hidraw" / name / "device"
        d.mkdir(parents=True)
        (d / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=x\n")
    return sys_root


def test_find_hidraw_picks_matching_node(tmp_path):
    sys_root = make_sys(tmp_path, {
        "hidraw0": "0003:0000046D:0000C52B",
        "hidraw6": "0003:00005131:00002007",
    })
    assert find_hidraw(sys_root) == "hidraw6"


def test_find_hidraw_none_when_absent(tmp_path):
    assert find_hidraw(make_sys(tmp_path, {"hidraw0": "0003:0000046D:0000C52B"})) is None


def test_open_not_found(tmp_path):
    with pytest.raises(NotFound):
        Device.open(sys_root=make_sys(tmp_path, {}), dev_root=tmp_path / "dev")


def test_open_permission_denied(tmp_path):
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    node = dev / "hidraw6"
    node.write_bytes(b"")
    node.chmod(0o000)
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    with pytest.raises(PermissionDenied) as e:
        Device.open(sys_root=sys_root, dev_root=dev)
    assert e.value.path.endswith("hidraw6")


def test_write_prepends_report_id(tmp_path):
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "hidraw6").write_bytes(b"")
    d = Device.open(sys_root=sys_root, dev_root=dev)
    d.write(bytes(range(64)))
    d.close()
    assert (dev / "hidraw6").read_bytes() == b"\x00" + bytes(range(64))


def test_write_rejects_wrong_size(tmp_path):
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "hidraw6").write_bytes(b"")
    d = Device.open(sys_root=sys_root, dev_root=dev)
    with pytest.raises(ValueError):
        d.write(b"\x00" * 10)


def test_write_after_close_raises_device_error(tmp_path):
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "hidraw6").write_bytes(b"")
    d = Device.open(sys_root=sys_root, dev_root=dev)
    d.close()
    with pytest.raises(DeviceError):
        d.write(bytes(64))
