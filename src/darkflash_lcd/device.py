"""Raw /dev/hidraw access to the cooler (no libusb, no native deps)."""

from __future__ import annotations

import os
from pathlib import Path

from . import PRODUCT_ID, VENDOR_ID
from .protocol import PACKET_SIZE

_HID_ID = f"HID_ID=0003:{VENDOR_ID:08X}:{PRODUCT_ID:08X}"


class DeviceError(Exception):
    pass


class NotFound(DeviceError):
    pass


class PermissionDenied(DeviceError):
    def __init__(self, path: str) -> None:
        super().__init__(f"no permission to open {path}")
        self.path = path


def find_hidraw(sys_root: Path = Path("/sys")) -> str | None:
    base = sys_root / "class" / "hidraw"
    if not base.is_dir():
        return None
    for node in sorted(base.iterdir()):
        try:
            uevent = (node / "device" / "uevent").read_text()
        except OSError:
            continue
        if any(line.strip().upper() == _HID_ID for line in uevent.splitlines()):
            return node.name
    return None


class Device:
    def __init__(self, path: str, fd: int) -> None:
        self.path = path
        self._fd: int | None = fd

    @classmethod
    def open(cls, sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev")) -> Device:
        name = find_hidraw(sys_root)
        if name is None:
            raise NotFound("darkFlash LCD (USB 5131:2007) not found")
        path = str(dev_root / name)
        try:
            fd = os.open(path, os.O_WRONLY)
        except PermissionError as e:
            raise PermissionDenied(path) from e
        except OSError as e:
            raise DeviceError(f"cannot open {path}: {e}") from e
        return cls(path, fd)

    def write(self, payload: bytes) -> None:
        if len(payload) != PACKET_SIZE:
            raise ValueError(f"payload must be {PACKET_SIZE} bytes, got {len(payload)}")
        if self._fd is None:
            raise DeviceError("device is closed")
        try:
            os.write(self._fd, b"\x00" + payload)
        except OSError as e:
            self.close()
            raise DeviceError(f"write to {self.path} failed: {e}") from e

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
