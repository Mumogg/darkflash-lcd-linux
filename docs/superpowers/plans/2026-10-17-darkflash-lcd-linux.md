# darkflash-lcd-linux Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a public, installable Linux app that drives the darkFlash DN240D/DN360D pump-head segment LCD (USB `5131:2007`) with live system stats, configurable from a Qt GUI.

**Architecture:** One Python package. `protocol` (pure packet encoder, byte-exact port of the Windows app) → `device` (raw `/dev/hidraw` I/O) are driven by a systemd **user** daemon that reads `sensors` per `config` and is the only writer to the device. CLI and PySide6 GUI talk to the daemon over a Unix socket (JSON lines, `ipc`).

**Tech Stack:** Python ≥ 3.10, `psutil`, optional `PySide6` (extra `[gui]`), `pytest`, `ruff`, hatchling build backend, systemd user service, udev `uaccess`.

**Spec:** `docs/superpowers/specs/2026-10-17-darkflash-lcd-linux-design.md`

## Global Constraints

- Repo root: `$HOME/darkflash-lcd-linux` (quote it). Remote: `Mumogg/darkflash-lcd-linux`. License MIT.
- Package `darkflash_lcd` under `src/`; console scripts `darkflash-lcd` and `darkflash-lcd-gui`.
- Python ≥ 3.10; runtime deps: `psutil` only. GUI dep `PySide6` only via extra `[gui]`; nothing outside `darkflash_lcd/gui/` may import PySide6.
- USB IDs: vendor `0x5131`, product `0x2007`; hidraw write = `b"\x00" + 64-byte payload`.
- Config: `$XDG_CONFIG_HOME/darkflash-lcd/config.toml` (default `~/.config/...`). Socket: `$XDG_RUNTIME_DIR/darkflash-lcd.sock`.
- Defaults: `interval_ms = 500` (min 100), `unit = "C"`, `fields = ["cpu.temp", "cpu.usage", "ram.usage", "cpu.freq"]`.
- Field ranges: big = temperature in tenths 0–9999 (≥ 1000 blinks "E" exactly like Windows); left/right = 0–199; bottom = 0–9999.
- No `sudo` at runtime; the udev rule is the only privileged install step.
- User-facing strings in GUI/CLI exist in English and Spanish.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Git identity is repo-local (already set).
- Local dev env: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev,gui]'`; run tests with `.venv/bin/pytest`.

**Deviation from spec (deliberate):** a source that fails to read is sent as `0` (the display has no reliable "blank" glyph for every field) and is reported as an error in `status`/GUI, instead of "shown blank".

## Review Focus

1. **Device unplugged / replugged while the daemon runs** → daemon logs once, keeps running, resumes writing within ~2 s of the device returning. (Task 6 test `test_reconnects_after_write_error`.)
2. **No permission on `/dev/hidrawN` (udev rule missing)** → `doctor`/`status` say "no permission" with the fix, never a traceback. (Task 2 test `test_open_permission_denied`, Task 7 test `test_doctor_reports_permission`.)
3. **Selected sensor disappears** (e.g. config names `hwmon.nct6798.fan2` after a kernel change) → field shows 0, status lists the missing id, daemon doesn't crash. (Task 6 test `test_missing_source_sends_zero_and_reports`.)
4. **Hand-edited invalid config.toml** → daemon keeps last good config and reports the parse error. (Task 5 test `test_invalid_toml_returns_defaults_and_error`, Task 6 test `test_reload_with_bad_config_keeps_previous`.)
5. **Two daemons / stale socket file after a crash** → second daemon refuses to start if the socket answers; removes the socket file if nobody answers. (Task 6 test `test_stale_socket_is_replaced`.)

---

### Task 1: Project scaffold + protocol encoder (byte-exact with Windows)

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.gitignore`, `src/darkflash_lcd/__init__.py`, `src/darkflash_lcd/protocol.py`
- Create: `tests/fixtures/windows_golden.json` (copied), `tests/test_protocol.py`
- Create: `tools/reverse/` (copied scripts) + `docs/PROTOCOL.md`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `darkflash_lcd.protocol.Reading(temp_tenths: int, left: int, right: int, bottom: int)` (frozen dataclass); `Encoder()` with `.encode(Reading) -> bytes` (64 bytes) and attribute `.seq: int`; `closing_packet() -> bytes`; `PACKET_SIZE = 64`; `RANGES = {"temp_tenths": (0, 9999), "left": (0, 199), "right": (0, 199), "bottom": (0, 9999)}`.

- [ ] **Step 1: Scaffold files**

`pyproject.toml`:
```toml
[build-system]
requires = ["hatchling>=1.18"]
build-backend = "hatchling.build"

[project]
name = "darkflash-lcd"
version = "0.1.0"
description = "Linux driver/app for the darkFlash DN240D / DN360D AIO pump LCD (USB 5131:2007)"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
dependencies = ["psutil>=5.9", "tomli>=2.0; python_version < '3.11'"]
keywords = ["darkflash", "dn240d", "dn360d", "nebula", "aio", "lcd", "linux", "liquid cooler"]
classifiers = ["Operating System :: POSIX :: Linux", "Programming Language :: Python :: 3"]

[project.optional-dependencies]
gui = ["PySide6>=6.5"]
dev = ["pytest>=7", "ruff>=0.4"]

[project.scripts]
darkflash-lcd = "darkflash_lcd.cli:main"

[project.gui-scripts]
darkflash-lcd-gui = "darkflash_lcd.gui.app:main"

[project.urls]
Homepage = "https://github.com/Mumogg/darkflash-lcd-linux"

[tool.hatch.build.targets.wheel]
packages = ["src/darkflash_lcd"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`LICENSE`: standard MIT text, `Copyright (c) 2026 Mumogg`.

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
```

`src/darkflash_lcd/__init__.py`:
```python
"""Linux app for the darkFlash DN240D / DN360D AIO pump-head LCD."""

__version__ = "0.1.0"
VENDOR_ID = 0x5131
PRODUCT_ID = 0x2007
```

- [ ] **Step 2: Copy golden fixture and reverse-engineering tools**

```bash
R="$HOME/darkflash-lcd-linux"
S="$(mktemp -d)"
mkdir -p "$R/tests/fixtures" "$R/tools/reverse"
cp "$S/golden_11.json" "$R/tests/fixtures/windows_golden.json"
cp "$S/tools/ildump.py" "$S/tools/ildump_lib.py" "$S/tools/ilvm.py" "$S/tools/oracle.py" "$S/tools/verify.py" "$R/tools/reverse/"
```
The fixture is 400 consecutive packets (`{"in": [v0,v1,v2,v3], "out": hex}`) produced by running the original `SendData2` in the IL interpreter, starting from `seq = 0` and blink phase 0. Order matters (sequence counter and "E" blink).

Write `tools/reverse/README.md` explaining: extract the MSI with `7z`, the cab inside it, point `DN_EXE` at the `.NET` exe (`ComputereMonitor`), `pip install dnfile dncil`, run `verify.py <dir-containing-protocol.py> <seed> <out.json>` to compare the port against the original. Write `docs/PROTOCOL.md` with the packet table from the spec's "Packet format" section plus the corrected facts: hundreds digit of left/right fields is a single "1" segment (left: bank byte 7 bit 0x80; right: bank byte 6 bit 0x02); leading-zero rules (bottom field blanks up to 3 leading zeros; left/right blank the tens only if hundreds and tens are 0; big field blanks hundreds if 0); decimal point = bank1 byte 9 bit 0x80, off while v0 ≥ 1000; bank 2 carries a 2-digit integer temperature (`v0 // 10`, ≥ 100 shows a fixed pattern) and two 12-step bar graphs driven by `right` and `0` (Windows sends exactly that); the 60-segment ring code (`smg88_60`, `TM1721_show3..5`) is never called for this device.

- [ ] **Step 3: Write the failing tests**

`tests/test_protocol.py`:
```python
import json
from pathlib import Path

from darkflash_lcd.protocol import PACKET_SIZE, Encoder, Reading, closing_packet

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "windows_golden.json").read_text())


def test_matches_windows_app_byte_for_byte():
    enc = Encoder()
    for i, case in enumerate(GOLDEN):
        got = enc.encode(Reading(*case["in"])).hex()
        assert got == case["out"], f"case {i} {case['in']}"


def test_packet_size_and_constant_byte():
    p = Encoder().encode(Reading(425, 12, 34, 1234))
    assert len(p) == PACKET_SIZE
    assert p[2] == 1


def test_sequence_wraps_at_256():
    enc = Encoder()
    enc.seq = 255
    assert enc.encode(Reading(0, 0, 0, 0))[0] == 255
    assert enc.encode(Reading(0, 0, 0, 0))[0] == 0


def test_out_of_range_values_are_clamped():
    enc_a, enc_b = Encoder(), Encoder()
    assert enc_a.encode(Reading(-5, 250, 999, 12345)) == enc_b.encode(Reading(0, 199, 199, 9999))


def test_e_blinks_on_alternate_packets_when_hot():
    enc = Encoder()
    first = enc.encode(Reading(1234, 0, 0, 0))
    second = enc.encode(Reading(1234, 0, 0, 0))
    third = enc.encode(Reading(1234, 0, 0, 0))
    assert first[24:40] != second[24:40]
    assert first[24:40] == third[24:40]


def test_closing_packet():
    p = closing_packet()
    assert len(p) == PACKET_SIZE and p[1] == 15 and sum(p) == 15
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m venv .venv && .venv/bin/pip install -q -e '.[dev]' && .venv/bin/pytest tests/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'darkflash_lcd.protocol'`

- [ ] **Step 5: Implement `src/darkflash_lcd/protocol.py`**

```python
"""Packet encoder for the darkFlash DN240D/DN360D pump-head segment LCD.

Byte-for-byte port of ``frmMain.SendData2`` + ``TM1721_show1/2`` from the
official Windows app ("darkFlash DN-D"). Verified against the original code in
``tests/fixtures/windows_golden.json``; see ``docs/PROTOCOL.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

PACKET_SIZE = 64
BLANK = 10
E = 14
RANGES = {"temp_tenths": (0, 9999), "left": (0, 199), "right": (0, 199), "bottom": (0, 9999)}

# One-byte glyphs (bottom field and right round field).
_GLYPH_BYTE = {0: 0xF5, 1: 0x05, 2: 0xD3, 3: 0x97, 4: 0x27, 5: 0xB6,
               6: 0xF6, 7: 0x15, 8: 0xF7, 9: 0xB7, E: 0xF2, BLANK: 0x08}
# Glyphs split as (high nibble of byte n, low nibble of byte n+1): left field, big field.
_GLYPH_SPLIT = {0: (0x50, 0x0F), 1: (0x50, 0x00), 2: (0x30, 0x0D), 3: (0x70, 0x09),
                4: (0x70, 0x02), 5: (0x60, 0x0B), 6: (0x60, 0x0F), 7: (0x50, 0x01),
                8: (0x70, 0x0F), 9: (0x70, 0x0B), E: (0x20, 0x0F)}
# Bank 2 two-digit integer temperature glyphs.
_GLYPH_BANK2 = {0: (0xF0, 0x0A), 1: (0x00, 0x0A), 2: (0xB0, 0x0C), 3: (0x90, 0x0E),
                4: (0x40, 0x0E), 5: (0xD0, 0x06), 6: (0xF0, 0x06), 7: (0x80, 0x0A),
                8: (0xF0, 0x0E), 9: (0xD0, 0x0E)}

# Always-on symbols in each 16-byte bank.
_BANK1_BASE = (0x08, 0x08, 0x00, 0x08, 0x08, 0x00, 0x8D, 0x00,
               0x80, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00)
_BANK2_BASE = (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x08, 0x08, 0x01, 0x01, 0x00)
_BANK2_OVER_99 = ((12, 0xF0), (13, 0xF4), (14, 0x04))

# Bank 2 bar graphs: (threshold, ((byte, mask), ...)); highest threshold reached wins.
_BAR_A = (
    (1, ((10, 0x80),)),
    (200, ((10, 0xC0), (11, 0x04))),
    (300, ((10, 0xE0), (11, 0x06))),
    (400, ((10, 0xF0), (11, 0x07))),
    (600, ((9, 0x10), (10, 0xF1), (11, 0x07))),
    (800, ((9, 0x30), (10, 0xF3), (11, 0x07))),
    (1000, ((9, 0x70), (10, 0xF7), (11, 0x07))),
    (1200, ((9, 0xF0), (10, 0xFF), (11, 0x07))),
    (1400, ((0, 0x88), (9, 0xF0), (10, 0xFF), (11, 0x07))),
    (1600, ((0, 0xCC), (9, 0xF0), (10, 0xFF), (11, 0x07))),
    (1800, ((0, 0xEE), (9, 0xF0), (10, 0xFF), (11, 0x07))),
    (2000, ((0, 0xFF), (9, 0xF0), (10, 0xFF), (11, 0x07))),
)
_BAR_B = (
    (1, ((11, 0x80),)),
    (500, ((11, 0xC0), (12, 0x04))),
    (700, ((11, 0xE0), (12, 0x06))),
    (900, ((11, 0xF0), (12, 0x07))),
    (1100, ((2, 0x11), (11, 0xF0), (12, 0x07))),
    (1300, ((2, 0x33), (11, 0xF0), (12, 0x07))),
    (1500, ((2, 0x77), (11, 0xF0), (12, 0x07))),
    (1700, ((2, 0xFF), (11, 0xF0), (12, 0x07))),
    (1900, ((1, 0x88), (2, 0xFF), (11, 0xF0), (12, 0x07))),
    (2100, ((1, 0xCC), (2, 0xFF), (11, 0xF0), (12, 0x07))),
    (2300, ((1, 0xEE), (2, 0xFF), (11, 0xF0), (12, 0x07))),
    (2500, ((1, 0xFF), (2, 0xFF), (11, 0xF0), (12, 0x07))),
)


@dataclass(frozen=True)
class Reading:
    """Values for the four display fields.

    temp_tenths: big field in tenths (425 -> "42.5").
    left / right: the two round fields (0-199).
    bottom: the 4-digit field (0-9999).
    """

    temp_tenths: int
    left: int
    right: int
    bottom: int


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _digits(v: int, n: int) -> list[int]:
    return [v // 10**k % 10 for k in range(n - 1, -1, -1)]


def _put_byte(bank: list[int], idx: int, digit: int) -> None:
    bank[idx] |= _GLYPH_BYTE.get(digit, 0)


def _put_split(bank: list[int], idx: int, digit: int) -> None:
    hi, lo = _GLYPH_SPLIT.get(digit, (0, 0))
    bank[idx] |= hi
    bank[idx + 1] |= lo


def _bar(table: tuple, value: int) -> tuple:
    lit: tuple = ()
    for threshold, masks in table:
        if value >= threshold:
            lit = masks
    return lit


class Encoder:
    """Stateful encoder: sequence counter + "E" blink phase, like the Windows app."""

    def __init__(self) -> None:
        self.seq = 0
        self._blink = 0

    def encode(self, r: Reading) -> bytes:
        v0 = _clamp(r.temp_tenths, *RANGES["temp_tenths"])
        v1 = _clamp(r.left, *RANGES["left"])
        v2 = _clamp(r.right, *RANGES["right"])
        v3 = _clamp(r.bottom, *RANGES["bottom"])

        p = bytearray(PACKET_SIZE)
        p[0] = self.seq
        self.seq = (self.seq + 1) & 0xFF
        p[2] = 1
        p[5:8] = bytes(_digits(v0, 3))
        p[9:12] = bytes(_digits(v1, 3))
        p[13:16] = bytes(_digits(v2, 3))
        p[16:20] = bytes(_digits(v3, 4))
        p[24:40] = bytes(self._bank1(v0, v1, v2, v3))
        p[40:56] = bytes(_bank2(v0 // 10, v2, 0))
        return bytes(p)

    def _bank1(self, v0: int, v1: int, v2: int, v3: int) -> list[int]:
        bank = list(_BANK1_BASE)

        d3 = _digits(v3, 4)
        for k in range(3):
            if d3[k] != 0:
                break
            d3[k] = BLANK
        d2 = _digits(v2, 3)
        if d2[0] == 0 and d2[1] == 0:
            d2[1] = BLANK
        d1 = _digits(v1, 3)
        if d1[0] == 0 and d1[1] == 0:
            d1[1] = BLANK
        d0 = _digits(v0, 3)
        point = True
        if v0 >= 1000:
            self._blink += 1
            d0 = [E, E, BLANK] if self._blink % 2 == 0 else _digits(v0 // 10, 3)
            point = False
        elif d0[0] == 0:
            d0[0] = BLANK

        for k, digit in enumerate(reversed(d3)):  # bottom: units..thousands -> bytes 0..3
            _put_byte(bank, k, digit)
        if d2[0]:  # right round field: "1" segment, tens byte 5, units byte 4
            bank[6] |= 0x02
        _put_byte(bank, 5, d2[1])
        _put_byte(bank, 4, d2[2])
        if d1[0]:  # left round field: "1" segment, tens 7/8, units 6/7
            bank[7] |= 0x80
        _put_split(bank, 7, d1[1])
        _put_split(bank, 6, d1[2])
        _put_split(bank, 10, d0[0])  # big field: hundreds 10/11, tens 9/10, units 8/9
        _put_split(bank, 9, d0[1])
        _put_split(bank, 8, d0[2])
        if point:
            bank[9] |= 0x80
        return bank


def _bank2(temp_c: int, bar_a: int, bar_b: int) -> list[int]:
    bank = list(_BANK2_BASE)
    if temp_c > 99:
        for i, m in _BANK2_OVER_99:
            bank[i] |= m
    else:
        tens, units = divmod(temp_c, 10)
        hi, lo = _GLYPH_BANK2[units]
        bank[13] |= hi
        bank[14] |= lo
        if tens:
            hi, lo = _GLYPH_BANK2[tens]
            bank[12] |= hi
            bank[13] |= lo
    for i, m in _bar(_BAR_A, bar_a) + _bar(_BAR_B, bar_b):
        bank[i] |= m
    return bank


def closing_packet() -> bytes:
    """Packet the Windows app sends once when it exits."""
    p = bytearray(PACKET_SIZE)
    p[1] = 15
    return bytes(p)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_protocol.py -v`
Expected: 6 passed.

- [ ] **Step 7: Add CI** — `.github/workflows/ci.yml`:
```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.10", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e '.[dev]'
      - run: ruff check src tests
      - run: pytest -q
```

- [ ] **Step 8: Lint + commit**

```bash
.venv/bin/ruff check src tests
git add -A && git commit -m "feat: byte-exact protocol encoder with Windows golden tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: hidraw device access

**Files:**
- Create: `src/darkflash_lcd/device.py`, `tests/test_device.py`

**Interfaces:**
- Consumes: `VENDOR_ID`, `PRODUCT_ID` from `darkflash_lcd`.
- Produces: `find_hidraw(sys_root: Path = Path("/sys")) -> str | None` (returns node name like `"hidraw6"`); `class DeviceError(Exception)`, `class NotFound(DeviceError)`, `class PermissionDenied(DeviceError)` (has `.path: str`); `class Device` with `Device.open(sys_root=Path("/sys"), dev_root=Path("/dev")) -> Device`, `.path: str`, `.write(payload: bytes) -> None` (raises `DeviceError` on I/O failure), `.close() -> None`.

- [ ] **Step 1: Write the failing tests** — `tests/test_device.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_device.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `src/darkflash_lcd/device.py`**
```python
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
    def open(cls, sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev")) -> "Device":
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
```
Note: `HID_ID` in uevent is upper-case hex already (`0003:00005131:00002007`); `.upper()` keeps the match robust.

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_device.py -v` → 7 passed.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: hidraw device discovery and writes" ` (+ Co-Authored-By trailer).

---

### Task 3: Hardware validation on the real cooler (human checkpoint)

**Files:**
- Create: `packaging/70-darkflash-lcd.rules`, `scripts/hw_smoke.py`
- Modify (only if the hardware disagrees): `src/darkflash_lcd/protocol.py`, `docs/PROTOCOL.md`, `tests/test_protocol.py`

**Interfaces:**
- Consumes: `Device.open()`, `Encoder`, `Reading`, `closing_packet()`.
- Produces: confirmed field mapping recorded in `docs/PROTOCOL.md` ("Hardware-validated" section). Later tasks assume: big = temperature, `left` = CPU-labelled circle, `right` = RAM-labelled circle, `bottom` = MHz. If the user reports left/right swapped, swap the *labels* used by later tasks (field names `left`/`right` stay positional).

- [ ] **Step 1: Write the udev rule** — `packaging/70-darkflash-lcd.rules`:
```
# darkFlash DN240D / DN360D pump LCD — give the logged-in user access (no root needed at runtime)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="5131", ATTRS{idProduct}=="2007", TAG+="uaccess"
```

- [ ] **Step 2: Write `scripts/hw_smoke.py`**
```python
"""Send fixed frames to the cooler so a human can confirm what the display shows."""

import sys
import time

sys.path.insert(0, "src")
from darkflash_lcd.device import Device  # noqa: E402
from darkflash_lcd.protocol import Encoder, Reading, closing_packet  # noqa: E402

STEPS = {
    "a": Reading(425, 12, 34, 1234),
    "b": Reading(999, 188, 199, 9999),
    "c": Reading(5, 1, 7, 8),
    "e": Reading(1234, 100, 100, 1000),
}


def main() -> None:
    step = sys.argv[1]
    dev = Device.open()
    enc = Encoder()
    if step == "close":
        dev.write(closing_packet())
        return
    end = time.monotonic() + float(sys.argv[2] if len(sys.argv) > 2 else 15)
    while time.monotonic() < end:
        dev.write(enc.encode(STEPS[step]))
        time.sleep(0.2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Install the rule (user runs, needs sudo)**

Ask the user to run: `! sudo cp packaging/70-darkflash-lcd.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw`
Verify: `ls -l /dev/hidraw*` → the 5131:2007 node has a `+` ACL; `getfacl /dev/hidrawN` lists `user:<you>:rw-`.

- [ ] **Step 4: Run each frame and record what the user sees**

Run, one at a time, asking the user (photo welcome) after each:
- `.venv/bin/python scripts/hw_smoke.py a` → expected `42.5°C`, one circle `12%`, other `34%`, `1234MHz`. Which circle (CPU or RAM label) shows 12?
- `... b` → `99.9`, `188`, `199`, `9999`.
- `... c` → `0.5` (hundreds blank), `1`, `7`, `8` (leading zeros blank).
- `... e 6` → alternating `EE` / `123` without decimal point; circles `100`; `1000MHz`.
- `... close` → what happens (blank? standby? logo?).
Also ask: does the blue ring change at any point?

- [ ] **Step 5: Reconcile**

If everything matches: write the "Hardware-validated (2026-10-17, DN240D)" section in `docs/PROTOCOL.md` listing each observation. If something differs: add a failing test in `tests/test_protocol.py` that encodes the observed truth, fix `protocol.py` (keep the golden test passing unless the hardware proves the Windows behaviour itself is wrong — then document why and mark the golden case), re-run `.venv/bin/pytest -q`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "test: hardware-validated display mapping + udev rule"` (+ trailer).

---

### Task 4: Sensor sources

**Files:**
- Create: `src/darkflash_lcd/sensors.py`, `tests/test_sensors.py`

**Interfaces:**
- Produces: `Source` dataclass `(id: str, name: str, kind: str, unit: str, read: Callable[[], float | None])` where `kind ∈ {"temp", "percent", "freq", "rpm"}`; `discover(sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")) -> list[Source]` (stable ids, no duplicates, built-ins first); `read_all(sources) -> dict[str, float | None]`.
- Built-in ids: `cpu.temp`, `cpu.usage`, `ram.usage`, `cpu.freq`, `cpu.freq_max`, `gpu.temp` (only if found), `nvme.temp` (only if found). Generic: `hwmon.<chipname>.<temp|fan><N>` (chip name made unique with `-<k>` suffix when repeated, e.g. `spd5118-1`).

- [ ] **Step 1: Write the failing tests** — `tests/test_sensors.py`:
```python
from pathlib import Path

from darkflash_lcd import sensors


def hwmon(root: Path, idx: int, name: str, entries: dict[str, str]) -> None:
    d = root / "class" / "hwmon" / f"hwmon{idx}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    for k, v in entries.items():
        (d / k).write_text(v + "\n")


def cpufreq(root: Path, khz: list[int]) -> None:
    for n, f in enumerate(khz):
        d = root / "devices" / "system" / "cpu" / f"cpu{n}" / "cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_cur_freq").write_text(f"{f}\n")


def by_id(srcs):
    return {s.id: s for s in srcs}


def test_amd_cpu_temp_prefers_tctl(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50375", "temp1_label": "Tctl",
                                   "temp3_input": "40000", "temp3_label": "Tccd1"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.temp"].read() == 50.375
    assert s["cpu.temp"].kind == "temp"


def test_intel_cpu_temp_uses_package(tmp_path):
    hwmon(tmp_path, 0, "coretemp", {"temp1_input": "61000", "temp1_label": "Package id 0",
                                    "temp2_input": "55000", "temp2_label": "Core 0"})
    assert by_id(sensors.discover(sys_root=tmp_path))["cpu.temp"].read() == 61.0


def test_gpu_and_nvme_detected(tmp_path):
    hwmon(tmp_path, 0, "nvme", {"temp1_input": "42850", "temp1_label": "Composite"})
    hwmon(tmp_path, 4, "amdgpu", {"temp1_input": "47000", "temp1_label": "edge"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["gpu.temp"].read() == 47.0
    assert s["nvme.temp"].read() == 42.85


def test_generic_hwmon_ids_are_unique(tmp_path):
    hwmon(tmp_path, 2, "spd5118", {"temp1_input": "41000"})
    hwmon(tmp_path, 3, "spd5118", {"temp1_input": "40000"})
    hwmon(tmp_path, 5, "nct6798", {"fan2_input": "1180", "fan2_label": "CPU_FAN"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["hwmon.spd5118.temp1"].read() == 41.0
    assert s["hwmon.spd5118-1.temp1"].read() == 40.0
    assert s["hwmon.nct6798.fan2"].kind == "rpm"
    assert s["hwmon.nct6798.fan2"].read() == 1180.0
    assert "CPU_FAN" in s["hwmon.nct6798.fan2"].name


def test_no_fans_means_no_rpm_sources(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    assert not [s for s in sensors.discover(sys_root=tmp_path) if s.kind == "rpm"]


def test_cpu_freq_avg_and_max_in_mhz(tmp_path):
    cpufreq(tmp_path, [3000000, 4000000, 5000000])
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.freq"].read() == 4000.0
    assert s["cpu.freq_max"].read() == 5000.0


def test_vanished_file_reads_none(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    (tmp_path / "class" / "hwmon" / "hwmon1" / "temp1_input").unlink()
    assert s["cpu.temp"].read() is None


def test_usage_sources_always_present(tmp_path):
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.usage"].kind == "percent" and s["ram.usage"].kind == "percent"
    assert 0 <= s["ram.usage"].read() <= 100


def test_read_all(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    vals = sensors.read_all(sensors.discover(sys_root=tmp_path))
    assert vals["cpu.temp"] == 50.0
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_sensors.py -v` → FAIL.

- [ ] **Step 3: Implement `src/darkflash_lcd/sensors.py`**
```python
"""System sensor sources (hwmon, cpufreq, psutil, nvidia-smi)."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psutil


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str  # "temp" | "percent" | "freq" | "rpm"
    unit: str
    read: Callable[[], "float | None"]


def _read_number(path: Path, scale: float) -> float | None:
    try:
        return int(path.read_text().strip()) / scale
    except (OSError, ValueError):
        return None


def _label(d: Path, prefix: str) -> str | None:
    try:
        return (d / f"{prefix}_label").read_text().strip()
    except OSError:
        return None


def _hwmon_dirs(sys_root: Path) -> list[tuple[str, Path]]:
    base = sys_root / "class" / "hwmon"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir(), key=lambda p: int(re.sub(r"\D", "", p.name) or 0)):
        try:
            out.append(((d / "name").read_text().strip(), d))
        except OSError:
            continue
    return out


def _temp_source(sid: str, name: str, path: Path) -> Source:
    return Source(sid, name, "temp", "°C", lambda p=path: _read_number(p, 1000))


def _pick(d: Path, labels: list[str]) -> Path | None:
    entries = sorted(d.glob("temp*_input"))
    for want in labels:
        for e in entries:
            if _label(d, e.name[: -len("_input")]) == want:
                return e
    return entries[0] if entries else None


def _cpu_freq(sys_root: Path, how: Callable[[list[float]], float]) -> Callable[[], float | None]:
    def read() -> float | None:
        vals = [
            v
            for f in (sys_root / "devices" / "system" / "cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")
            if (v := _read_number(f, 1000)) is not None
        ]
        return how(vals) if vals else None

    return read


class _NvidiaSmi:
    """`nvidia-smi` is slow; cache its answer for 2 s."""

    def __init__(self) -> None:
        self._at = 0.0
        self._val: float | None = None

    def read(self) -> float | None:
        if time.monotonic() - self._at > 2:
            self._at = time.monotonic()
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2, check=True,
                ).stdout
                self._val = float(out.splitlines()[0])
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                self._val = None
        return self._val


def discover(sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")) -> list[Source]:
    del proc_root  # psutil reads /proc itself; parameter kept for symmetry in tests
    psutil.cpu_percent(interval=None)  # prime the counter
    out: list[Source] = []
    chips = _hwmon_dirs(sys_root)
    by_name = {}
    for name, d in chips:
        by_name.setdefault(name, d)

    for chip, labels in (("k10temp", ["Tdie", "Tctl"]), ("zenpower", ["Tdie", "Tctl"]),
                         ("coretemp", ["Package id 0"])):
        if chip in by_name and (p := _pick(by_name[chip], labels)):
            out.append(_temp_source("cpu.temp", "CPU temperature", p))
            break
    out.append(Source("cpu.usage", "CPU usage", "percent", "%",
                      lambda: float(psutil.cpu_percent(interval=None))))
    out.append(Source("ram.usage", "RAM usage", "percent", "%",
                      lambda: float(psutil.virtual_memory().percent)))
    out.append(Source("cpu.freq", "CPU frequency (average)", "freq", "MHz",
                      _cpu_freq(sys_root, lambda v: sum(v) / len(v))))
    out.append(Source("cpu.freq_max", "CPU frequency (fastest core)", "freq", "MHz",
                      _cpu_freq(sys_root, max)))
    if "amdgpu" in by_name and (p := _pick(by_name["amdgpu"], ["edge", "junction"])):
        out.append(_temp_source("gpu.temp", "GPU temperature", p))
    elif shutil.which("nvidia-smi"):
        out.append(Source("gpu.temp", "GPU temperature (NVIDIA)", "temp", "°C", _NvidiaSmi().read))
    if "nvme" in by_name and (p := _pick(by_name["nvme"], ["Composite"])):
        out.append(_temp_source("nvme.temp", "NVMe temperature", p))

    seen: dict[str, int] = {}
    for name, d in chips:
        k = seen.get(name, 0)
        seen[name] = k + 1
        chip_id = name if k == 0 else f"{name}-{k}"
        for f in sorted(d.glob("temp*_input")) + sorted(d.glob("fan*_input")):
            prefix = f.name[: -len("_input")]
            label = _label(d, prefix) or prefix
            if prefix.startswith("fan"):
                out.append(Source(f"hwmon.{chip_id}.{prefix}", f"{chip_id} {label}", "rpm", "RPM",
                                  lambda p=f: _read_number(p, 1)))
            else:
                out.append(_temp_source(f"hwmon.{chip_id}.{prefix}", f"{chip_id} {label}", f))
    return out


def read_all(sources: list[Source]) -> dict[str, float | None]:
    vals: dict[str, float | None] = {}
    for s in sources:
        try:
            vals[s.id] = s.read()
        except Exception:  # a broken sensor must never stop the display loop
            vals[s.id] = None
    return vals
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_sensors.py -v` → 9 passed. Then sanity-check on the real machine: `.venv/bin/python -c "from darkflash_lcd import sensors as s; print(s.read_all(s.discover()))"` — expect `cpu.temp` ≈ the `k10temp Tctl` value from `sensors`.

- [ ] **Step 5: Commit** — `git commit -am "feat: sensor discovery (hwmon, cpufreq, psutil, nvidia-smi)"` after `git add -A` (+ trailer).

---

### Task 5: Config file + field mapping

**Files:**
- Create: `src/darkflash_lcd/config.py`, `src/darkflash_lcd/fields.py`, `tests/test_config.py`, `tests/test_fields.py`

**Interfaces:**
- Produces (config): `Config(interval_ms: int = 500, unit: str = "C", fields: tuple[str, str, str, str] = DEFAULT_FIELDS)` frozen dataclass; `DEFAULT_FIELDS`; `config_path() -> Path`; `load(path: Path) -> tuple[Config, str | None]` (error message or None; on error returns defaults); `save(path: Path, cfg: Config) -> None`.
- Produces (fields): `FIELD_KINDS: tuple[frozenset[str], ...]` = `({"temp"}, {"percent","temp"}, {"percent","temp"}, {"freq","rpm"})`; `compatible(field_index: int, source: Source) -> bool`; `to_reading(values: list[float | None], kinds: list[str | None], unit: str) -> Reading`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
from darkflash_lcd.config import DEFAULT_FIELDS, Config, load, save


def test_missing_file_gives_defaults(tmp_path):
    cfg, err = load(tmp_path / "nope.toml")
    assert cfg == Config() and err is None
    assert cfg.fields == DEFAULT_FIELDS


def test_roundtrip(tmp_path):
    p = tmp_path / "c" / "config.toml"
    cfg = Config(interval_ms=250, unit="F", fields=("gpu.temp", "cpu.usage", "cpu.temp", "hwmon.nct6798.fan2"))
    save(p, cfg)
    assert load(p) == (cfg, None)


def test_invalid_toml_returns_defaults_and_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("interval_ms = [oops")
    cfg, err = load(p)
    assert cfg == Config() and err


def test_bad_values_are_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('interval_ms = 10\nunit = "K"\nfields = ["a"]\n')
    cfg, err = load(p)
    assert cfg == Config() and "interval_ms" in err


def test_quotes_in_ids_survive(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config(fields=('hwmon.a"b.temp1', "cpu.usage", "ram.usage", "cpu.freq"))
    save(p, cfg)
    assert load(p)[0] == cfg
```

`tests/test_fields.py`:
```python
from darkflash_lcd.fields import compatible, to_reading
from darkflash_lcd.protocol import Reading
from darkflash_lcd.sensors import Source


def src(kind):
    return Source("x", "x", kind, "", lambda: 1.0)


def test_compatibility():
    assert compatible(0, src("temp")) and not compatible(0, src("percent"))
    assert compatible(1, src("percent")) and compatible(2, src("temp"))
    assert compatible(3, src("rpm")) and compatible(3, src("freq")) and not compatible(3, src("temp"))


def test_to_reading_celsius():
    r = to_reading([42.46, 12.6, 34.4, 4321.7], ["temp", "percent", "percent", "freq"], "C")
    assert r == Reading(425, 13, 34, 4322)


def test_to_reading_fahrenheit_converts_temps_only():
    r = to_reading([50.0, 40.0, 30.0, 1000.0], ["temp", "temp", "percent", "rpm"], "F")
    assert r == Reading(1220, 104, 30, 1000)


def test_none_becomes_zero():
    assert to_reading([None, None, None, None], [None] * 4, "C") == Reading(0, 0, 0, 0)
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_config.py tests/test_fields.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/darkflash_lcd/config.py`:
```python
"""~/.config/darkflash-lcd/config.toml"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_FIELDS = ("cpu.temp", "cpu.usage", "ram.usage", "cpu.freq")


@dataclass(frozen=True)
class Config:
    interval_ms: int = 500
    unit: str = "C"
    fields: tuple[str, str, str, str] = DEFAULT_FIELDS


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "darkflash-lcd" / "config.toml"


def load(path: Path) -> tuple[Config, str | None]:
    if not path.exists():
        return Config(), None
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        return Config(), f"{path}: {e}"
    interval = data.get("interval_ms", 500)
    unit = data.get("unit", "C")
    fields = data.get("fields", list(DEFAULT_FIELDS))
    if not isinstance(interval, int) or interval < 100:
        return Config(), f"{path}: interval_ms must be an integer >= 100"
    if unit not in ("C", "F"):
        return Config(), f'{path}: unit must be "C" or "F"'
    if not (isinstance(fields, list) and len(fields) == 4 and all(isinstance(f, str) for f in fields)):
        return Config(), f"{path}: fields must be a list of 4 sensor ids"
    return Config(interval, unit, tuple(fields)), None


def save(path: Path, cfg: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON string escaping is valid TOML basic-string escaping for these values.
    text = (
        "# darkflash-lcd configuration — see `darkflash-lcd sensors` for ids\n"
        f"interval_ms = {cfg.interval_ms}\n"
        f"unit = {json.dumps(cfg.unit)}\n"
        f"fields = [{', '.join(json.dumps(f) for f in cfg.fields)}]\n"
    )
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
```

`src/darkflash_lcd/fields.py`:
```python
"""Which sources fit which display field, and turning values into a Reading."""

from __future__ import annotations

from .protocol import Reading
from .sensors import Source

FIELD_KINDS = (
    frozenset({"temp"}),
    frozenset({"percent", "temp"}),
    frozenset({"percent", "temp"}),
    frozenset({"freq", "rpm"}),
)


def compatible(field_index: int, source: Source) -> bool:
    return source.kind in FIELD_KINDS[field_index]


def _conv(v: float | None, kind: str | None, unit: str) -> float:
    if v is None:
        return 0.0
    if kind == "temp" and unit == "F":
        return v * 9 / 5 + 32
    return v


def to_reading(values: list[float | None], kinds: list[str | None], unit: str) -> Reading:
    v = [_conv(x, k, unit) for x, k in zip(values, kinds)]
    return Reading(round(v[0] * 10), round(v[1]), round(v[2]), round(v[3]))
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_config.py tests/test_fields.py -v` → 9 passed.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: config file and field mapping"` (+ trailer).

---

### Task 6: IPC + daemon

**Files:**
- Create: `src/darkflash_lcd/ipc.py`, `src/darkflash_lcd/daemon.py`, `tests/test_daemon.py`

**Interfaces:**
- Consumes: `Device`, `DeviceError`, `NotFound`, `PermissionDenied`, `Encoder`, `Reading`, `closing_packet`, `discover`, `read_all`, `Config`, `load`, `config_path`, `to_reading`.
- Produces (ipc): `socket_path() -> Path`; `request(msg: dict, path: Path | None = None, timeout: float = 2.0) -> dict` (raises `ConnectionError` if no daemon); `serve(path: Path, handler: Callable[[dict], dict]) -> socketserver.BaseServer` (started in a daemon thread; caller calls `.shutdown()` + `.server_close()`).
- Produces (daemon): `class Daemon(open_device: Callable[[], Device], sources_factory: Callable[[], list[Source]], cfg_path: Path)` with `.tick() -> None` (one refresh), `.handle(msg: dict) -> dict`, `.run(stop: threading.Event) -> None`, `.state: dict` (`connection` ∈ `"connected" | "not_found" | "no_permission" | "error"`, `values`, `reading`, `errors: list[str]`, `paused: bool`); `main() -> int` (CLI entry `darkflash-lcd daemon`).
- Messages: `{"cmd": "status"|"reload"|"sensors"|"test"|"pause"|"resume"}`, `{"cmd": "preview", "values": [v0,v1,v2,v3], "seconds": N}`. Replies: `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.

- [ ] **Step 1: Write the failing tests** — `tests/test_daemon.py`:
```python
import threading
from pathlib import Path

import pytest

from darkflash_lcd import ipc
from darkflash_lcd.config import Config, save
from darkflash_lcd.daemon import Daemon
from darkflash_lcd.device import DeviceError, NotFound
from darkflash_lcd.sensors import Source


class FakeDevice:
    def __init__(self, fail_after=None):
        self.packets = []
        self.fail_after = fail_after
        self.path = "/dev/hidraw-fake"

    def write(self, p):
        if self.fail_after is not None and len(self.packets) >= self.fail_after:
            raise DeviceError("unplugged")
        self.packets.append(p)

    def close(self):
        pass


def sources(temp=42.5):
    return [
        Source("cpu.temp", "CPU", "temp", "°C", lambda: temp),
        Source("cpu.usage", "CPU %", "percent", "%", lambda: 12.0),
        Source("ram.usage", "RAM %", "percent", "%", lambda: 34.0),
        Source("cpu.freq", "MHz", "freq", "MHz", lambda: 1234.0),
    ]


def make(tmp_path, devices):
    it = iter(devices)

    def opener():
        d = next(it)
        if isinstance(d, Exception):
            raise d
        return d

    return Daemon(opener, sources, tmp_path / "config.toml")


def test_tick_writes_encoded_reading(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.tick()
    assert len(dev.packets) == 1
    assert dev.packets[0][5:8] == bytes([4, 2, 5])
    assert d.state["connection"] == "connected"


def test_not_found_is_reported_and_retried(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [NotFound("x"), dev])
    d.tick()
    assert d.state["connection"] == "not_found"
    d._next_open = 0  # skip the 2 s back-off
    d.tick()
    assert d.state["connection"] == "connected" and dev.packets


def test_reconnects_after_write_error(tmp_path):
    first, second = FakeDevice(fail_after=1), FakeDevice()
    d = make(tmp_path, [first, second])
    d.tick()
    d.tick()  # write fails -> disconnected
    assert d.state["connection"] == "error"
    d._next_open = 0
    d.tick()
    assert second.packets and d.state["connection"] == "connected"


def test_missing_source_sends_zero_and_reports(tmp_path):
    save(tmp_path / "config.toml", Config(fields=("nope.temp", "cpu.usage", "ram.usage", "cpu.freq")))
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.tick()
    assert dev.packets[0][5:8] == bytes([0, 0, 0])
    assert any("nope.temp" in e for e in d.state["errors"])


def test_reload_with_bad_config_keeps_previous(tmp_path):
    p = tmp_path / "config.toml"
    save(p, Config(interval_ms=300))
    d = make(tmp_path, [FakeDevice()])
    p.write_text("interval_ms = [")
    r = d.handle({"cmd": "reload"})
    assert r["ok"] is False and d.cfg.interval_ms == 300


def test_preview_overrides_values_then_expires(tmp_path, monkeypatch):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    now = [1000.0]
    monkeypatch.setattr("darkflash_lcd.daemon.time.monotonic", lambda: now[0])
    assert d.handle({"cmd": "preview", "values": [999, 1, 2, 3], "seconds": 5})["ok"]
    d.tick()
    assert dev.packets[-1][5:8] == bytes([9, 9, 9])
    now[0] += 6
    d.tick()
    assert dev.packets[-1][5:8] == bytes([4, 2, 5])


def test_pause_stops_writes(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    d.handle({"cmd": "pause"})
    d.tick()
    assert not dev.packets
    d.handle({"cmd": "resume"})
    d.tick()
    assert dev.packets


def test_sensors_command_lists_sources(tmp_path):
    d = make(tmp_path, [FakeDevice()])
    r = d.handle({"cmd": "sensors"})
    assert {s["id"] for s in r["sensors"]} >= {"cpu.temp", "cpu.freq"}
    assert r["sensors"][0]["value"] == 42.5


def test_unknown_command(tmp_path):
    assert make(tmp_path, [FakeDevice()]).handle({"cmd": "x"})["ok"] is False


def test_ipc_roundtrip(tmp_path):
    sock = tmp_path / "s.sock"
    srv = ipc.serve(sock, lambda m: {"ok": True, "echo": m})
    try:
        assert ipc.request({"cmd": "status"}, sock)["echo"] == {"cmd": "status"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_request_without_daemon_raises(tmp_path):
    with pytest.raises(ConnectionError):
        ipc.request({"cmd": "status"}, tmp_path / "none.sock")


def test_stale_socket_is_replaced(tmp_path):
    sock = tmp_path / "s.sock"
    sock.write_text("")  # leftover file from a crash, nobody listening
    srv = ipc.serve(sock, lambda m: {"ok": True})
    try:
        assert ipc.request({"cmd": "status"}, sock)["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_second_server_refuses_when_first_alive(tmp_path):
    sock = tmp_path / "s.sock"
    srv = ipc.serve(sock, lambda m: {"ok": True})
    try:
        with pytest.raises(RuntimeError):
            ipc.serve(sock, lambda m: {"ok": True})
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_loop_stops_and_sends_closing_packet(tmp_path):
    dev = FakeDevice()
    d = make(tmp_path, [dev])
    stop = threading.Event()
    t = threading.Thread(target=d.run, args=(stop,))
    t.start()
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive()
    assert dev.packets[-1][1] == 15
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_daemon.py -v` → FAIL.

- [ ] **Step 3: Implement `src/darkflash_lcd/ipc.py`**
```python
"""JSON-lines over a Unix socket between the daemon and the CLI/GUI."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Callable


def socket_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/darkflash-lcd-{os.getuid()}"
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(base) / "darkflash-lcd.sock"


def request(msg: dict, path: Path | None = None, timeout: float = 2.0) -> dict:
    path = path or socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(json.dumps(msg).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise ConnectionError(f"darkflash-lcd daemon not reachable at {path}: {e}") from e
    return json.loads(buf)


def _alive(path: Path) -> bool:
    try:
        request({"cmd": "status"}, path, timeout=0.5)
        return True
    except (ConnectionError, ValueError):
        return False


def serve(path: Path, handler: Callable[[dict], dict]) -> socketserver.BaseServer:
    if path.exists():
        if _alive(path):
            raise RuntimeError(f"another darkflash-lcd daemon is already running ({path})")
        path.unlink()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            line = self.rfile.readline()
            try:
                reply = handler(json.loads(line))
            except Exception as e:  # never kill the server on a bad message
                reply = {"ok": False, "error": str(e)}
            self.wfile.write(json.dumps(reply).encode() + b"\n")

    srv = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    srv.daemon_threads = True
    os.chmod(path, 0o600)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
```

- [ ] **Step 4: Implement `src/darkflash_lcd/daemon.py`**
```python
"""The only process that writes to the display."""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from typing import Callable

from . import ipc
from .config import Config, config_path, load
from .device import Device, DeviceError, NotFound, PermissionDenied
from .fields import to_reading
from .protocol import Encoder, Reading, closing_packet
from .sensors import Source, discover, read_all

log = logging.getLogger("darkflash-lcd")
RETRY_S = 2.0
TEST_FRAMES = [Reading(888, 188, 188, 8888), Reading(0, 0, 0, 0), Reading(1888, 199, 199, 9999)]


class Daemon:
    def __init__(self, open_device: Callable[[], Device],
                 sources_factory: Callable[[], list[Source]], cfg_path: Path) -> None:
        self._open = open_device
        self._sources_factory = sources_factory
        self.cfg_path = cfg_path
        self.cfg, err = load(cfg_path)
        self.sources = {s.id: s for s in sources_factory()}
        self.enc = Encoder()
        self.dev: Device | None = None
        self._next_open = 0.0
        self._preview: tuple[Reading, float] | None = None
        self._test_until = 0.0
        self._lock = threading.Lock()
        self.state: dict = {"connection": "not_found", "values": {}, "reading": None,
                            "errors": [err] if err else [], "paused": False, "device": None}

    # ---- device ----
    def _ensure_device(self) -> bool:
        if self.dev is not None:
            return True
        if time.monotonic() < self._next_open:
            return False
        try:
            self.dev = self._open()
            self.state.update(connection="connected", device=self.dev.path)
            log.info("display connected at %s", self.dev.path)
            return True
        except NotFound:
            conn = "not_found"
        except PermissionDenied as e:
            conn = "no_permission"
            self.state["device"] = e.path
        except DeviceError:
            conn = "error"
        if self.state["connection"] != conn:
            log.warning("display unavailable: %s", conn)
        self.state["connection"] = conn
        self._next_open = time.monotonic() + RETRY_S
        return False

    # ---- one refresh ----
    def tick(self) -> None:
        with self._lock:
            ids = list(self.cfg.fields)
            vals = read_all([self.sources[i] for i in ids if i in self.sources])
            errors = [f"unknown sensor: {i}" for i in ids if i not in self.sources]
            errors += [f"sensor read failed: {i}" for i in ids if i in vals and vals[i] is None]
            reading = to_reading([vals.get(i) for i in ids],
                                 [self.sources[i].kind if i in self.sources else None for i in ids],
                                 self.cfg.unit)
            now = time.monotonic()
            if now < self._test_until:
                reading = TEST_FRAMES[int(now * 2) % len(TEST_FRAMES)]
            elif self._preview and now < self._preview[1]:
                reading = self._preview[0]
            else:
                self._preview = None
            self.state.update(values={i: vals.get(i) for i in ids}, reading=reading.__dict__,
                              errors=errors)
            if self.state["paused"] or not self._ensure_device():
                return
            try:
                self.dev.write(self.enc.encode(reading))
            except DeviceError as e:
                log.warning("%s", e)
                self.dev = None
                self.state["connection"] = "error"
                self._next_open = time.monotonic() + RETRY_S

    # ---- IPC ----
    def handle(self, msg: dict) -> dict:
        cmd = msg.get("cmd")
        if cmd == "status":
            return {"ok": True, **self.state, "config": self.cfg.__dict__ | {"fields": list(self.cfg.fields)}}
        if cmd == "reload":
            cfg, err = load(self.cfg_path)
            if err:
                return {"ok": False, "error": err}
            with self._lock:
                self.cfg = cfg
                self.sources = {s.id: s for s in self._sources_factory()}
            return {"ok": True}
        if cmd == "sensors":
            vals = read_all(list(self.sources.values()))
            return {"ok": True, "sensors": [
                {"id": s.id, "name": s.name, "kind": s.kind, "unit": s.unit, "value": vals[s.id]}
                for s in self.sources.values()]}
        if cmd == "preview":
            v = [int(x) for x in msg["values"]]
            self._preview = (Reading(*v), time.monotonic() + float(msg.get("seconds", 5)))
            return {"ok": True}
        if cmd == "test":
            self._test_until = time.monotonic() + 6
            return {"ok": True}
        if cmd in ("pause", "resume"):
            self.state["paused"] = cmd == "pause"
            return {"ok": True}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    def run(self, stop: threading.Event) -> None:
        try:
            while True:  # always at least one refresh
                self.tick()
                if stop.wait(self.cfg.interval_ms / 1000):
                    break
        finally:
            if self.dev is not None:
                try:
                    self.dev.write(closing_packet())
                except DeviceError:
                    pass
                self.dev.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    d = Daemon(Device.open, discover, config_path())
    try:
        srv = ipc.serve(ipc.socket_path(), d.handle)
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    log.info("darkflash-lcd daemon started")
    try:
        d.run(stop)
    finally:
        srv.shutdown()
        srv.server_close()
        ipc.socket_path().unlink(missing_ok=True)
    return 0
```

- [ ] **Step 5: Run tests** — `.venv/bin/pytest tests/test_daemon.py -v` → 14 passed. Full suite `.venv/bin/pytest -q` green.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: daemon with IPC, reconnect, preview and test pattern"` (+ trailer).

---

### Task 7: CLI (incl. `doctor`)

**Files:**
- Create: `src/darkflash_lcd/i18n.py`, `src/darkflash_lcd/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `ipc.request`, `daemon.main`, `find_hidraw`, `Device`, `PermissionDenied`, `NotFound`, `discover`, `read_all`, `Config`, `load`, `save`, `config_path`.
- Produces: `i18n.current_lang() -> str`; `i18n.t(key: str, lang: str | None = None, **kw) -> str` (es if `LANG`/`LC_ALL`/`LC_MESSAGES` starts with `es`, else en); `cli.main(argv: list[str] | None = None) -> int`; `cli.doctor(sys_root=Path("/sys"), dev_root=Path("/dev"), rules_dirs=(Path("/etc/udev/rules.d"), Path("/usr/lib/udev/rules.d"))) -> list[tuple[bool, str]]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cli.py`:
```python
import json

from darkflash_lcd import cli, i18n
from tests.test_device import make_sys


def test_i18n_spanish(monkeypatch):
    monkeypatch.setenv("LANG", "es_CR.UTF-8")
    assert i18n.t("doctor.usb_ok", node="x") != i18n.t("doctor.usb_ok", lang="en", node="x")


def test_doctor_reports_missing_usb(tmp_path):
    checks = cli.doctor(sys_root=make_sys(tmp_path, {}), dev_root=tmp_path, rules_dirs=())
    assert checks[0][0] is False


def test_doctor_reports_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    sys_root = make_sys(tmp_path, {"hidraw6": "0003:00005131:00002007"})
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "hidraw6").write_bytes(b"")
    (dev / "hidraw6").chmod(0o000)
    checks = cli.doctor(sys_root=sys_root, dev_root=dev, rules_dirs=())
    texts = " ".join(t for _, t in checks)
    assert checks[0][0] is True
    assert "udev" in texts


def test_sensors_command_without_daemon_reads_directly(capsys, monkeypatch):
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    assert cli.main(["sensors", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(s["id"] == "cpu.usage" for s in data)


def test_config_set_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: {"ok": True})
    assert cli.main(["config", "set", "field1", "gpu.temp"]) == 0
    assert '"gpu.temp"' in (tmp_path / "darkflash-lcd" / "config.toml").read_text()


def test_show_requires_daemon(monkeypatch, capsys):
    monkeypatch.setattr(cli.ipc, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
    assert cli.main(["show", "425", "1", "2", "3"]) == 1
```
Add an empty `tests/__init__.py` so `from tests.test_device import make_sys` works.

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_cli.py -v` → FAIL.

- [ ] **Step 3: Implement `src/darkflash_lcd/i18n.py`**
```python
"""Tiny en/es string table. Add a language by adding a dict."""

from __future__ import annotations

import os

STRINGS = {
    "en": {
        "doctor.usb_ok": "USB device 5131:2007 found ({node})",
        "doctor.usb_missing": "Cooler not found on USB. Check that the pump's USB cable is plugged into an internal USB 2.0 header on the motherboard.",
        "doctor.perm_ok": "Write access to {path}",
        "doctor.perm_missing": "No permission on {path}. Install the udev rule: sudo cp packaging/70-darkflash-lcd.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger",
        "doctor.rule_ok": "udev rule installed",
        "doctor.rule_missing": "udev rule not installed (70-darkflash-lcd.rules)",
        "doctor.daemon_ok": "Daemon running, display {conn}",
        "doctor.daemon_missing": "Daemon not running. Start it: systemctl --user enable --now darkflash-lcd",
        "doctor.sensors": "Sensors detected: {n} ({ids})",
        "status.connected": "connected", "status.not_found": "not found",
        "status.no_permission": "no permission", "status.error": "error",
        "no_daemon": "The darkflash-lcd daemon is not running (systemctl --user start darkflash-lcd).",
    },
    "es": {
        "doctor.usb_ok": "Dispositivo USB 5131:2007 encontrado ({node})",
        "doctor.usb_missing": "No se encontró la líquida por USB. Revisa que el cable USB de la bomba esté conectado a un header USB 2.0 interno de la placa madre.",
        "doctor.perm_ok": "Acceso de escritura a {path}",
        "doctor.perm_missing": "Sin permisos en {path}. Instala la regla udev: sudo cp packaging/70-darkflash-lcd.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger",
        "doctor.rule_ok": "Regla udev instalada",
        "doctor.rule_missing": "Regla udev no instalada (70-darkflash-lcd.rules)",
        "doctor.daemon_ok": "Servicio activo, pantalla {conn}",
        "doctor.daemon_missing": "El servicio no está activo. Inícialo: systemctl --user enable --now darkflash-lcd",
        "doctor.sensors": "Sensores detectados: {n} ({ids})",
        "status.connected": "conectada", "status.not_found": "no encontrada",
        "status.no_permission": "sin permisos", "status.error": "error",
        "no_daemon": "El servicio darkflash-lcd no está activo (systemctl --user start darkflash-lcd).",
    },
}


def current_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return "es" if v.startswith("es") else "en"
    return "en"


def t(key: str, lang: str | None = None, **kw) -> str:
    table = STRINGS.get(lang or current_lang(), STRINGS["en"])
    return table.get(key, STRINGS["en"][key]).format(**kw)
```

- [ ] **Step 4: Implement `src/darkflash_lcd/cli.py`**
```python
"""`darkflash-lcd` command line."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from . import __version__, ipc
from .config import config_path, load, save
from .device import find_hidraw
from .i18n import t
from .sensors import discover, read_all


def doctor(sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev"),
           rules_dirs=(Path("/etc/udev/rules.d"), Path("/usr/lib/udev/rules.d"))) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    node = find_hidraw(sys_root)
    if node is None:
        return [(False, t("doctor.usb_missing"))]
    checks.append((True, t("doctor.usb_ok", node=node)))
    path = str(dev_root / node)
    ok = os.access(path, os.W_OK)
    checks.append((ok, t("doctor.perm_ok" if ok else "doctor.perm_missing", path=path)))
    rule = any((d / "70-darkflash-lcd.rules").exists() for d in rules_dirs)
    checks.append((rule, t("doctor.rule_ok" if rule else "doctor.rule_missing")))
    try:
        st = ipc.request({"cmd": "status"})
        checks.append((True, t("doctor.daemon_ok", conn=t(f"status.{st['connection']}"))))
    except ConnectionError:
        checks.append((False, t("doctor.daemon_missing")))
    srcs = discover(sys_root=sys_root)
    checks.append((True, t("doctor.sensors", n=len(srcs), ids=", ".join(s.id for s in srcs[:8]))))
    return checks


def _sensors() -> list[dict]:
    try:
        return ipc.request({"cmd": "sensors"})["sensors"]
    except ConnectionError:
        srcs = discover()
        vals = read_all(srcs)
        return [{"id": s.id, "name": s.name, "kind": s.kind, "unit": s.unit, "value": vals[s.id]}
                for s in srcs]


def _send(msg: dict) -> int:
    try:
        r = ipc.request(msg)
    except ConnectionError:
        print(t("no_daemon"))
        return 1
    if not r.get("ok"):
        print(r.get("error"))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="darkflash-lcd",
                                description="darkFlash DN240D/DN360D pump LCD for Linux")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon", help="run the display service (used by systemd)")
    sub.add_parser("status")
    s = sub.add_parser("sensors")
    s.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="show fixed values for a few seconds")
    sh.add_argument("values", nargs=4, type=float, metavar=("TEMP", "LEFT", "RIGHT", "BOTTOM"))
    sh.add_argument("--seconds", type=float, default=10)
    for name in ("test", "pause", "resume", "doctor"):
        sub.add_parser(name)
    c = sub.add_parser("config")
    csub = c.add_subparsers(dest="action", required=True)
    csub.add_parser("get")
    cs = csub.add_parser("set")
    cs.add_argument("key", choices=["field0", "field1", "field2", "field3", "unit", "interval_ms"])
    cs.add_argument("value")
    a = p.parse_args(argv)

    if a.cmd == "daemon":
        from .daemon import main as daemon_main
        return daemon_main()
    if a.cmd == "status":
        try:
            print(json.dumps(ipc.request({"cmd": "status"}), indent=2, ensure_ascii=False))
            return 0
        except ConnectionError:
            print(t("no_daemon"))
            return 1
    if a.cmd == "sensors":
        data = _sensors()
        if a.json:
            print(json.dumps(data, ensure_ascii=False))
        else:
            for s in data:
                v = "—" if s["value"] is None else f"{s['value']:.1f} {s['unit']}"
                print(f"{s['id']:<32} {v:>12}  {s['name']}")
        return 0
    if a.cmd == "show":
        v = a.values
        return _send({"cmd": "preview", "values": [round(v[0] * 10), round(v[1]), round(v[2]), round(v[3])],
                      "seconds": a.seconds})
    if a.cmd in ("test", "pause", "resume"):
        return _send({"cmd": a.cmd})
    if a.cmd == "doctor":
        checks = doctor()
        for ok, text in checks:
            print(("✔ " if ok else "✘ ") + text)
        return 0 if all(ok for ok, _ in checks) else 1
    if a.cmd == "config":
        path = config_path()
        cfg, err = load(path)
        if a.action == "get":
            print(err or path.read_text() if path.exists() else f"(defaults) {cfg}")
            return 0
        if a.key.startswith("field"):
            fields = list(cfg.fields)
            fields[int(a.key[-1])] = a.value
            cfg = replace(cfg, fields=tuple(fields))
        elif a.key == "unit":
            cfg = replace(cfg, unit=a.value.upper())
        else:
            cfg = replace(cfg, interval_ms=int(a.value))
        save(path, cfg)
        try:
            ipc.request({"cmd": "reload"})
        except ConnectionError:
            pass
        return 0
    return 1
```
`show` takes the temperature in degrees (e.g. `42.5`) and converts to tenths.

- [ ] **Step 5: Run tests** — `.venv/bin/pytest -q` → all green.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: CLI with doctor, sensors, show, config"` (+ trailer).

---

### Task 8: systemd service, installer, uninstaller (+ end-to-end on the real cooler)

**Files:**
- Create: `packaging/darkflash-lcd.service`, `packaging/darkflash-lcd.desktop`, `packaging/darkflash-lcd-tray.desktop`, `packaging/darkflash-lcd.svg`, `install.sh`, `uninstall.sh`

**Interfaces:**
- Consumes: console scripts `darkflash-lcd`, `darkflash-lcd-gui`; `packaging/70-darkflash-lcd.rules` from Task 3.
- Produces: installed layout: venv `~/.local/share/darkflash-lcd/venv` (or pipx), wrappers in `~/.local/bin`, unit `~/.config/systemd/user/darkflash-lcd.service`, desktop file `~/.local/share/applications/darkflash-lcd.desktop`, icon `~/.local/share/icons/hicolor/scalable/apps/darkflash-lcd.svg`. Tray autostart file path `~/.config/autostart/darkflash-lcd-tray.desktop` (written by GUI in Task 9, template here).

- [ ] **Step 1: Unit file** — `packaging/darkflash-lcd.service`:
```ini
[Unit]
Description=darkFlash DN240D/DN360D pump LCD
After=graphical-session.target

[Service]
ExecStart=%h/.local/bin/darkflash-lcd daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Desktop files + icon**

`packaging/darkflash-lcd.desktop`:
```ini
[Desktop Entry]
Type=Application
Name=darkFlash LCD
Comment=Configure the darkFlash AIO pump display
Comment[es]=Configura la pantalla de la líquida darkFlash
Exec=darkflash-lcd-gui
Icon=darkflash-lcd
Categories=Settings;HardwareSettings;
```
`packaging/darkflash-lcd-tray.desktop`: same but `Name=darkFlash LCD (tray)`, `Exec=darkflash-lcd-gui --tray`, `X-GNOME-Autostart-enabled=true`, `NoDisplay=true`.
`packaging/darkflash-lcd.svg`: a simple 64×64 icon — dark circle, cyan ring arc, "88°" text:
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="30" fill="#14161a"/>
  <path d="M32 6a26 26 0 1 1-18.4 7.6" fill="none" stroke="#22b8f0" stroke-width="5" stroke-linecap="round"/>
  <text x="32" y="38" font-family="DejaVu Sans Mono,monospace" font-size="16" font-weight="700" fill="#e8f6ff" text-anchor="middle">88°</text>
</svg>
```

- [ ] **Step 3: `install.sh`**
```bash
#!/usr/bin/env bash
# darkflash-lcd installer — works on any systemd distro. Only the udev rule needs sudo.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10+ required"

GUI=""
if [[ "${1:-}" == "--no-gui" ]]; then GUI=""
elif [[ "${1:-}" == "--gui" ]]; then GUI="[gui]"
else
  read -r -p "Install the graphical app too (PySide6, ~200 MB)? [Y/n] " a
  [[ "${a:-y}" =~ ^[Yy]$ ]] && GUI="[gui]"
fi

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
if command -v pipx >/dev/null; then
  say "Installing with pipx"
  pipx install --force ".$GUI"
else
  VENV="$HOME/.local/share/darkflash-lcd/venv"
  say "Installing into $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q ".$GUI"
  ln -sf "$VENV/bin/darkflash-lcd" "$BIN/darkflash-lcd"
  [[ -n "$GUI" ]] && ln -sf "$VENV/bin/darkflash-lcd-gui" "$BIN/darkflash-lcd-gui"
fi

say "Installing udev rule (needs sudo)"
sudo install -m 644 packaging/70-darkflash-lcd.rules /etc/udev/rules.d/70-darkflash-lcd.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw

say "Installing user service"
install -Dm644 packaging/darkflash-lcd.service "$HOME/.config/systemd/user/darkflash-lcd.service"
systemctl --user daemon-reload
systemctl --user enable --now darkflash-lcd.service

if [[ -n "$GUI" ]]; then
  install -Dm644 packaging/darkflash-lcd.desktop "$HOME/.local/share/applications/darkflash-lcd.desktop"
  install -Dm644 packaging/darkflash-lcd.svg "$HOME/.local/share/icons/hicolor/scalable/apps/darkflash-lcd.svg"
fi

sleep 1
say "Checking setup"
"$BIN/darkflash-lcd" doctor || true
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH." ;; esac
```

- [ ] **Step 4: `uninstall.sh`**
```bash
#!/usr/bin/env bash
set -uo pipefail
systemctl --user disable --now darkflash-lcd.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/darkflash-lcd.service"
systemctl --user daemon-reload
command -v pipx >/dev/null && pipx uninstall darkflash-lcd 2>/dev/null
rm -rf "$HOME/.local/share/darkflash-lcd"
rm -f "$HOME/.local/bin/darkflash-lcd" "$HOME/.local/bin/darkflash-lcd-gui"
rm -f "$HOME/.local/share/applications/darkflash-lcd.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/darkflash-lcd.svg" \
      "$HOME/.config/autostart/darkflash-lcd-tray.desktop"
sudo rm -f /etc/udev/rules.d/70-darkflash-lcd.rules && sudo udevadm control --reload
echo "Removed. Your config stays in ~/.config/darkflash-lcd (delete it if you want)."
```
`chmod +x install.sh uninstall.sh`; `bash -n install.sh uninstall.sh` must pass.

- [ ] **Step 5: End-to-end on the real cooler (human checkpoint)**

User runs `! ./install.sh --no-gui`. Then verify:
- `darkflash-lcd doctor` → all ✔.
- `systemctl --user status darkflash-lcd` → active (running).
- User confirms the display shows live CPU temp / CPU % / RAM % / MHz, and that `darkflash-lcd show 12.3 45 67 890` changes it for 10 s, `darkflash-lcd test` cycles segments.
- After a reboot (user does it when convenient), the display resumes on its own.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: installer, uninstaller, systemd user service"` (+ trailer).

---

### Task 9: Qt GUI (window + tray)

**Files:**
- Create: `src/darkflash_lcd/gui/__init__.py`, `gui/app.py`, `gui/display_widget.py`, `gui/main_window.py`, `gui/tray.py`, `gui/strings.py`, `tests/test_gui_logic.py`

**Interfaces:**
- Consumes: `ipc.request`, `FIELD_KINDS`, `config.load/save/config_path`, `Config`.
- Produces: `gui.app.main(argv=None) -> int` (`--tray` starts minimized to tray); `gui.strings.t(key)` (reuses `i18n.current_lang()`); pure helper `gui.main_window.options_for_field(field_index: int, sensors: list[dict]) -> list[tuple[str, str]]` (id, label) filtered by `FIELD_KINDS`, testable without Qt.

- [ ] **Step 1: Failing logic test** — `tests/test_gui_logic.py`:
```python
import pytest

pytest.importorskip("PySide6")

from darkflash_lcd.gui.main_window import options_for_field  # noqa: E402

SENSORS = [
    {"id": "cpu.temp", "name": "CPU temperature", "kind": "temp", "unit": "°C", "value": 50.0},
    {"id": "cpu.usage", "name": "CPU usage", "kind": "percent", "unit": "%", "value": 3.0},
    {"id": "cpu.freq", "name": "CPU frequency", "kind": "freq", "unit": "MHz", "value": 4000.0},
    {"id": "hwmon.nct.fan2", "name": "nct CPU_FAN", "kind": "rpm", "unit": "RPM", "value": None},
]


def test_options_filtered_by_kind():
    assert [i for i, _ in options_for_field(0, SENSORS)] == ["cpu.temp"]
    assert [i for i, _ in options_for_field(1, SENSORS)] == ["cpu.temp", "cpu.usage"]
    assert [i for i, _ in options_for_field(3, SENSORS)] == ["cpu.freq", "hwmon.nct.fan2"]


def test_option_label_shows_value():
    assert "50.0 °C" in options_for_field(0, SENSORS)[0][1]
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pip install -q -e '.[dev,gui]' && .venv/bin/pytest tests/test_gui_logic.py -v` → FAIL.

- [ ] **Step 3: `gui/strings.py`**
```python
from ..i18n import current_lang

_S = {
    "en": {"title": "darkFlash LCD", "big": "Big field (°C)", "left": "Left circle",
           "right": "Right circle", "bottom": "Bottom (MHz / RPM)", "unit": "Temperature unit",
           "interval": "Refresh (ms)", "apply": "Apply", "test": "Test display",
           "start": "Start service", "help": "How do I fix this?", "pause": "Pause display",
           "resume": "Resume display", "open": "Open settings", "quit": "Quit tray",
           "autostart": "Start tray with session", "daemon_off": "Service not running",
           "connected": "Display connected", "not_found": "Cooler not found",
           "no_permission": "No permission (udev rule missing)", "error": "Display error",
           "f_note": "The display always prints °C; with °F the number is Fahrenheit.",
           "help_text": "Not found: plug the pump's USB cable into an internal USB 2.0 header.\nNo permission: run install.sh again (it installs the udev rule), then replug or reboot."},
    "es": {"title": "darkFlash LCD", "big": "Campo grande (°C)", "left": "Círculo izquierdo",
           "right": "Círculo derecho", "bottom": "Abajo (MHz / RPM)", "unit": "Unidad de temperatura",
           "interval": "Refresco (ms)", "apply": "Aplicar", "test": "Probar pantalla",
           "start": "Iniciar servicio", "help": "¿Cómo lo arreglo?", "pause": "Pausar pantalla",
           "resume": "Reanudar pantalla", "open": "Abrir configuración", "quit": "Salir de la bandeja",
           "autostart": "Iniciar bandeja con la sesión", "daemon_off": "El servicio no está activo",
           "connected": "Pantalla conectada", "not_found": "Líquida no encontrada",
           "no_permission": "Sin permisos (falta la regla udev)", "error": "Error de pantalla",
           "f_note": "La pantalla siempre muestra °C; con °F el número es en Fahrenheit.",
           "help_text": "No encontrada: conecta el cable USB de la bomba a un header USB 2.0 interno.\nSin permisos: vuelve a ejecutar install.sh (instala la regla udev) y reconecta o reinicia."},
}


def t(key: str) -> str:
    return _S.get(current_lang(), _S["en"]).get(key, _S["en"][key])
```

- [ ] **Step 4: `gui/display_widget.py`** — circular mock of the pump display:
```python
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class DisplayWidget(QWidget):
    """Draws what the pump LCD shows: 88.8°C, two round % fields, 8888MHZ, cyan ring."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(260, 260)
        self.reading = {"temp_tenths": 0, "left": 0, "right": 0, "bottom": 0}
        self.online = False

    def set_reading(self, reading: dict | None, online: bool) -> None:
        if reading:
            self.reading = reading
        self.online = online
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 10
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setBrush(QColor("#101215"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(r)
        ring = QColor("#22b8f0" if self.online else "#3a4048")
        p.setPen(QPen(ring, side * 0.035, cap=Qt.RoundCap))
        p.drawArc(r.adjusted(side * .06, side * .06, -side * .06, -side * .06), 250 * 16, 330 * 16)
        fg = QColor("#eaf6ff" if self.online else "#6b7380")
        p.setPen(fg)
        rd = self.reading
        t = rd["temp_tenths"]
        big = "EE" if t >= 1000 else f"{t // 10:>2}.{t % 10}"
        p.setFont(QFont("DejaVu Sans Mono", int(side * .14), QFont.Bold))
        p.drawText(QRectF(r.x(), r.y() + side * .18, side, side * .2), Qt.AlignCenter, f"{big}°C")
        p.setFont(QFont("DejaVu Sans Mono", int(side * .07), QFont.Bold))
        for i, key in enumerate(("left", "right")):
            cx = r.x() + side * (.33 if i == 0 else .67)
            box = QRectF(cx - side * .13, r.y() + side * .43, side * .26, side * .26)
            p.setPen(QPen(fg, 1.5))
            p.drawEllipse(box)
            p.drawText(box, Qt.AlignCenter, f"{rd[key]}%")
        p.setFont(QFont("DejaVu Sans Mono", int(side * .065)))
        p.drawText(QRectF(r.x(), r.y() + side * .72, side, side * .12), Qt.AlignCenter,
                   f"{rd['bottom']:>4}MHZ")
```

- [ ] **Step 5: `gui/main_window.py`**
```python
from __future__ import annotations

import subprocess
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import ipc
from ..config import config_path, load, save
from ..fields import FIELD_KINDS
from .display_widget import DisplayWidget
from .strings import t


def options_for_field(field_index: int, sensors: list[dict]) -> list[tuple[str, str]]:
    out = []
    for s in sensors:
        if s["kind"] in FIELD_KINDS[field_index]:
            v = "—" if s["value"] is None else f"{s['value']:.1f} {s['unit']}"
            out.append((s["id"], f"{s['name']}  ({v})"))
    return out


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(t("title"))
        self.display = DisplayWidget()
        self.status = QLabel()
        self.help_btn = QPushButton(t("help"))
        self.start_btn = QPushButton(t("start"))
        self.combos = [QComboBox() for _ in range(4)]
        self.unit = QComboBox()
        self.unit.addItems(["°C", "°F"])
        self.unit.setToolTip(t("f_note"))
        self.interval = QSpinBox()
        self.interval.setRange(100, 5000)
        self.interval.setSingleStep(100)
        apply_btn, test_btn = QPushButton(t("apply")), QPushButton(t("test"))

        form = QFormLayout()
        for key, combo in zip(("big", "left", "right", "bottom"), self.combos):
            form.addRow(t(key), combo)
        form.addRow(t("unit"), self.unit)
        form.addRow(t("interval"), self.interval)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.help_btn)
        status_row.addWidget(self.start_btn)
        buttons = QHBoxLayout()
        buttons.addWidget(test_btn)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.display, 1)
        lay.addLayout(status_row)
        lay.addLayout(form)
        lay.addLayout(buttons)

        apply_btn.clicked.connect(self.apply)
        test_btn.clicked.connect(lambda: self._send({"cmd": "test"}))
        self.help_btn.clicked.connect(lambda: QMessageBox.information(self, t("help"), t("help_text")))
        self.start_btn.clicked.connect(self.start_service)
        self.timer = QTimer(self, interval=1000, timeout=self.refresh)
        self.timer.start()
        self.load_form()
        self.refresh()

    def _send(self, msg: dict) -> dict | None:
        try:
            return ipc.request(msg)
        except ConnectionError:
            return None

    def load_form(self) -> None:
        cfg, _ = load(config_path())
        sensors = (self._send({"cmd": "sensors"}) or {}).get("sensors", [])
        for i, combo in enumerate(self.combos):
            combo.clear()
            for sid, label in options_for_field(i, sensors):
                combo.addItem(label, sid)
            idx = combo.findData(cfg.fields[i])
            if idx < 0:
                combo.addItem(cfg.fields[i], cfg.fields[i])
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        self.unit.setCurrentIndex(1 if cfg.unit == "F" else 0)
        self.interval.setValue(cfg.interval_ms)

    def apply(self) -> None:
        path = config_path()
        cfg, _ = load(path)
        cfg = replace(cfg, fields=tuple(c.currentData() for c in self.combos),
                      unit="F" if self.unit.currentIndex() == 1 else "C",
                      interval_ms=self.interval.value())
        save(path, cfg)
        self._send({"cmd": "reload"})
        self.refresh()

    def start_service(self) -> None:
        subprocess.run(["systemctl", "--user", "start", "darkflash-lcd"], check=False)
        QTimer.singleShot(1500, self.load_form)

    def refresh(self) -> None:
        st = self._send({"cmd": "status"})
        if st is None:
            self.status.setText("⚠ " + t("daemon_off"))
            self.start_btn.show()
            self.help_btn.hide()
            self.display.set_reading(None, False)
            return
        self.start_btn.hide()
        conn = st["connection"]
        self.status.setText(("✔ " if conn == "connected" else "⚠ ") + t(conn))
        self.help_btn.setVisible(conn != "connected")
        self.display.set_reading(st.get("reading"), conn == "connected" and not st.get("paused"))
```

- [ ] **Step 6: `gui/tray.py` + `gui/app.py`**

`gui/tray.py`:
```python
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import ipc
from .strings import t

AUTOSTART = Path.home() / ".config" / "autostart" / "darkflash-lcd-tray.desktop"
AUTOSTART_TEXT = """[Desktop Entry]
Type=Application
Name=darkFlash LCD (tray)
Exec=darkflash-lcd-gui --tray
Icon=darkflash-lcd
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


class Tray(QSystemTrayIcon):
    def __init__(self, open_window) -> None:
        super().__init__(QIcon.fromTheme("darkflash-lcd", QIcon.fromTheme("temperature-normal")))
        menu = QMenu()
        self.temp = menu.addAction("—")
        self.temp.setEnabled(False)
        menu.addSeparator()
        menu.addAction(t("open"), open_window)
        self.pause = menu.addAction(t("pause"), self.toggle_pause)
        auto = QAction(t("autostart"), menu, checkable=True, checked=AUTOSTART.exists())
        auto.toggled.connect(self.set_autostart)
        menu.addAction(auto)
        menu.addSeparator()
        menu.addAction(t("quit"), QApplication.quit)  # never stops the daemon
        self.setContextMenu(menu)
        self.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and open_window())
        self._menu = menu

    def update_from(self, st: dict | None) -> None:
        if not st or not st.get("reading"):
            self.temp.setText(t("daemon_off") if st is None else "—")
            return
        tt = st["reading"]["temp_tenths"]
        self.temp.setText(f"{tt / 10:.1f} °")
        self.setToolTip(f"darkFlash LCD — {tt / 10:.1f} °")
        self.pause.setText(t("resume") if st.get("paused") else t("pause"))

    def toggle_pause(self) -> None:
        try:
            st = ipc.request({"cmd": "status"})
            ipc.request({"cmd": "resume" if st.get("paused") else "pause"})
        except ConnectionError:
            pass

    @staticmethod
    def set_autostart(on: bool) -> None:
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(AUTOSTART_TEXT)
        else:
            AUTOSTART.unlink(missing_ok=True)
```

`gui/app.py`:
```python
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .. import ipc
from .main_window import MainWindow
from .tray import Tray


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("darkflash-lcd")
    app.setDesktopFileName("darkflash-lcd")
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    win = MainWindow()

    def show_window() -> None:
        win.load_form()
        win.show()
        win.raise_()
        win.activateWindow()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = Tray(show_window)
        tray.show()

        def poll() -> None:
            try:
                tray.update_from(ipc.request({"cmd": "status"}))
            except ConnectionError:
                tray.update_from(None)

        QTimer(app, interval=2000, timeout=poll).start()
        poll()
    if "--tray" not in argv or not QSystemTrayIcon.isSystemTrayAvailable():
        show_window()
    return app.exec()
```
`gui/__init__.py`: empty docstring module.

- [ ] **Step 7: Run tests** — `.venv/bin/pytest -q` → all green (GUI logic tests run because PySide6 is installed in dev).

- [ ] **Step 8: Manual GUI check (human checkpoint)** — `.venv/bin/darkflash-lcd-gui` on KDE Wayland with daemon running: window shows mock display updating every 1 s; change "Right circle" to `gpu.temp`, Apply → physical display changes; "Test display" cycles; tray icon menu shows temperature; stop the daemon (`systemctl --user stop darkflash-lcd`) → window shows "Service not running" + Start button that works. Also with `LANG=es_CR.UTF-8` strings are Spanish.

- [ ] **Step 9: Commit** — `git add -A && git commit -m "feat: Qt settings window and tray icon"` (+ trailer).

---

### Task 10: README (EN + ES), publish to GitHub, release v0.1.0

**Files:**
- Create: `README.md`, `docs/images/` (optional photo from the user)
- Modify: none

**Interfaces:**
- Consumes: everything above; `gh` CLI (authenticated as `Mumogg`).

- [ ] **Step 1: Write `README.md`** with, in this order:
  1. Title `# darkflash-lcd-linux — darkFlash DN240D / DN360D AIO LCD on Linux` and one-line description including "Nebula", "5131:2007", "Linux".
  2. **What it does / Qué hace** (EN then ES paragraphs): shows CPU temp, CPU %, RAM %, MHz (or any sensor) on the pump display; GUI + tray; no root at runtime.
  3. **Can I show images? / ¿Puedo poner imágenes?** — No: the display is a fixed-segment LCD (TM1721), no pixels. Same text in ES.
  4. **"Linux doesn't detect my cooler" / "Linux no detecta mi líquida"** — `lsusb` shows it as `5131:2007 MSR-101U Mini HID magnetic card reader`; that *is* the cooler. If it's absent, the pump's USB cable isn't on an internal USB 2.0 header.
  5. **Install / Instalación**: `git clone https://github.com/Mumogg/darkflash-lcd-linux && cd darkflash-lcd-linux && ./install.sh`; `--gui/--no-gui`; distro packages for PySide6 not needed (pip installs it).
  6. **Usage / Uso**: `darkflash-lcd doctor|sensors|show 42.5 12 34 1234|test|pause|resume|config set field2 gpu.temp`; GUI screenshot placeholder removed unless a real screenshot exists.
  7. **Display fields / Campos** table (big/left/right/bottom, allowed kinds, ranges, °F note).
  8. **Troubleshooting**: doctor output meanings; fans missing → load `nct6775`/`it87` (`sudo modprobe nct6775`, `sensors-detect`); NVIDIA needs `nvidia-smi`.
  9. **How it works / Cómo funciona**: link `docs/PROTOCOL.md`, `tools/reverse/`; "protocol port is verified byte-for-byte against the official Windows app".
  10. **Note on the USB ID**: some generic card readers share 5131:2007; the udev rule only grants the logged-in user access.
  11. **Uninstall**, **License (MIT)**, disclaimer: not affiliated with darkFlash.

- [ ] **Step 2: Final verification** — `.venv/bin/ruff check src tests && .venv/bin/pytest -q && bash -n install.sh uninstall.sh` all clean; `git status` clean after commit.

- [ ] **Step 3: Commit** — `git add -A && git commit -m "docs: bilingual README"` (+ trailer).

- [ ] **Step 4: Create the public repo and push (confirm with the user right before running)**
```bash
gh repo create Mumogg/darkflash-lcd-linux --public \
  --description "Linux app for the darkFlash DN240D / DN360D (Nebula) AIO pump LCD — USB 5131:2007. Temperature, CPU/RAM usage and MHz on the display, Qt GUI + tray." \
  --source . --remote origin --push
gh repo edit Mumogg/darkflash-lcd-linux --add-topic darkflash,dn240d,dn360d,aio,lcd,linux,liquid-cooling,hidraw,pyside6,systemd
```

- [ ] **Step 5: Verify CI and tag release**
```bash
gh run watch --exit-status
git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes "First release: daemon, CLI, Qt GUI/tray, installer. Tested on DN240D (Nobara/Fedora, KDE Wayland)."
```
Expected: CI green on 3.10/3.12/3.13; release page exists.
