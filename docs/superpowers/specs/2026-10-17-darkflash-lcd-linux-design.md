# darkflash-lcd-linux — Design

Date: 2026-10-17
Status: draft, pending review

## Goal

An open-source Linux app that drives the segment LCD on the pump head of
darkFlash Nebula DN240D / DN360D AIO coolers, replacing the Windows-only
"darkFlash DN-D" app. Anyone with the cooler should be able to install it with
one command and have the display show live system stats, configurable from a
Qt GUI, without root at runtime.

### Success criteria

- After `./install.sh` on the author's machine (Nobara/Fedora, KDE Wayland),
  the display shows real CPU temperature without `sudo` and resumes on its own
  after a reboot.
- The GUI can change which sensor is shown in each display field and the change
  is visible on the display immediately.
- The repo `Mumogg/darkflash-lcd-linux` is public with a bilingual
  (English/Spanish) README and passing CI.

### Non-goals

- **Images / GIFs.** The display is a fixed-segment LCD driven by a Titan Micro
  TM1721 controller. It has no pixels; arbitrary images are physically
  impossible. The README states this explicitly.
- Fan/pump speed control or RGB control (not part of the Windows app's USB
  protocol either).
- PyPI / AUR / COPR packaging in v1.

## Hardware facts (from reverse engineering the Windows app)

Source: `darkFlash DN-D Setup.msi` → .NET assembly `ComputereMonitor`
(class `frmMain`), uses Cypress `CyUSB.dll` for HID access.

- USB HID device `VID 0x5131`, `PID 0x2007`, USB 1.1 full speed, one
  interface (class 3), interrupt endpoints 0x82 IN / 0x02 OUT, 64-byte reports,
  no manufacturer/product strings. `lsusb`/usb.ids mislabels it as
  "MSR-101U Mini HID magnetic card reader" — this is the main reason users think
  Linux "doesn't detect" the cooler.
- Linux binds `usbhid` and exposes it as `/dev/hidrawN`, mode `0600 root` by
  default.
- Display layout (see product photo): large `88.8°C` field, two small circular
  fields labelled `CPU 188%` and `RAM 188%` (leading digit can only be blank or
  1), and a bottom `8888MHZ` field, plus a blue ring of fixed segments.

### Packet format (`SendData2`)

Every refresh writes one 64-byte HID output report (report ID prepended by the
HID layer: `write(fd, [report_id] + payload[0:64])`).

Values: `v0` (big field), `v1`, `v2` (small fields), `v3` (4-digit field).
Digits are raw values 0–9; `10` = blank digit; `14` = "E".

| bytes | content |
|---|---|
| 0 | sequence counter, increments per packet, wraps at 256 |
| 1 | 0 (15 = "app closing" packet, sent alone on exit) |
| 2 | 1 |
| 4–7 | 0, v0 hundreds, tens, units |
| 8–11 | 0, v1 hundreds, tens, units |
| 12–15 | 0, v2 hundreds, tens, units |
| 16–19 | v3 thousands, hundreds, tens, units |
| 24–39 | raw TM1721 segment RAM for chip/bank 1 (`TM1721_show1` → `lcd_buf`) |
| 40–55 | raw TM1721 segment RAM for chip/bank 2 (`TM1721_show2` → `lcd_buf`) |

Before `TM1721_show1` runs, bytes 24–39 temporarily hold a second, display-order
digit layout (v3 4 digits; v2, v1, v0 3 digits with leading zeros blanked as 10;
v0 ≥ 1000 alternates between "EE" and the value / 10 on each packet). The show
functions convert those digits to segments using this table (`TM1721_CHAR`,
nibble-swapped by `tran_num`):

```
0:0x5F 1:0x50 2:0x3D 3:0x79 4:0x72 5:0x6B 6:0x6F 7:0x51 8:0x7F 9:0x7B
10:0x80 11:0x00 12,13,other:0x00 14(E):0x2F
```

Digit code 10 is used as "blank" for leading zeros yet maps to `0x80`; whether
bit 7 is a neighbouring symbol segment (decimal point, the "1" of the 188
fields, a unit) is resolved during hardware validation.

Symbol bits (`fuhao_in_buf`): `lcd_buf[0,1,3,4] |= 0x08`, `lcd_buf[6] |= 0x8D`,
`lcd_buf[8] |= 0x80`, `lcd_buf[10] |= 0x80`.

The exact digit-to-RAM-address mapping inside `TM1721_show1..5` / `smg*`
helpers will be ported 1:1 from the IL during implementation.

**Hypotheses to validate on hardware** (first implementation task):
- `v0` is temperature × 10 (shown as `88.8`), so ≥ 1000 = ≥ 100.0 °C → "E".
- Field mapping: v0 = big temp, v1 = CPU %, v2 = RAM %, v3 = MHz.
- The closing packet (`byte[1] = 15`) blanks or puts the display in standby.
- Whether the blue ring is controllable or always on.

Windows app refreshes every 200 ms.

## Architecture

One Python package, three entry points, the daemon is the only writer to the
device.

```
darkflash-lcd-linux/
├── src/darkflash_lcd/
│   ├── protocol.py   # values -> 64-byte packet (pure, no I/O)
│   ├── device.py     # find 5131:2007 among /dev/hidraw*, open, write, reconnect
│   ├── sensors.py    # sensor sources (hwmon, psutil, nvidia-smi)
│   ├── config.py     # ~/.config/darkflash-lcd/config.toml
│   ├── daemon.py     # refresh loop + Unix socket server
│   ├── ipc.py        # JSON-lines client/server helpers
│   ├── cli.py        # `darkflash-lcd` command
│   ├── i18n.py       # en/es string tables
│   └── gui/          # PySide6 window + tray (optional extra)
├── packaging/        # udev rule, systemd user unit, .desktop, icon
├── tests/
├── install.sh / uninstall.sh
└── README.md (EN + ES)
```

### protocol.py
- `Frame(v0, v1, v2, v3)` → `bytes` (64). Holds the sequence counter in a small
  `Encoder` object. `closing_packet()` for shutdown. `test_pattern(step)` for the
  segment test.
- Clamping: v1/v2 to 0–199, v3 to 0–9999; v0 ≥ 1000 triggers the "E" blink
  exactly like the Windows app.
- No I/O, fully unit-tested.

### device.py
- Enumerate `/sys/class/hidraw/*/device` → parent USB `idVendor`/`idProduct`.
- `Device.open()` raises distinct errors: `NotFound`, `PermissionDenied`.
- `write(packet)` writes `b"\x00" + packet` (report ID 0); on `OSError`
  (unplug) closes and reports disconnected.
- No libusb, no native deps.

### sensors.py
- `Source(id, name, unit, kind, read() -> float | None)`.
- Built-ins: `cpu.temp` (k10temp Tctl/Tdie, coretemp Package), `cpu.usage`,
  `ram.usage` (psutil), `cpu.freq` (avg and max of
  `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`), `gpu.temp`
  (amdgpu edge/junction via hwmon, NVIDIA via `nvidia-smi` if present),
  `nvme.temp`.
- Generic: every `hwmon` `temp*_input` and `fan*_input` as
  `hwmon.<chip>.<label>`. Missing fans (no nct6775/it87 loaded) simply don't
  appear.
- Each display field accepts only compatible kinds: field 0 temperatures;
  fields 1–2 percentages or temperatures (≤ 199); field 3 MHz or RPM (≤ 9999).
- Fahrenheit option applies to temperature sources.
- A source that fails to read yields `None` → field is shown blank, daemon keeps
  running.

### config.py
- TOML at `$XDG_CONFIG_HOME/darkflash-lcd/config.toml`, read with `tomllib`,
  written by a tiny serializer (flat schema, no extra dependency).
- Schema: `interval_ms` (default 500, min 100), `unit` (`C`|`F`),
  `fields = [id0, id1, id2, id3]` (defaults `cpu.temp, cpu.usage, ram.usage,
  cpu.freq`).
- Missing file → defaults. Invalid file → log error, keep previous/default
  config, never crash.

### daemon.py
- Runs as systemd **user** service `darkflash-lcd.service`.
- Loop: read sources → encode → write → sleep `interval_ms`.
- Device absent / no permission: log once, retry every 2 s.
- On SIGTERM: send closing packet, exit 0.
- Unix socket `$XDG_RUNTIME_DIR/darkflash-lcd.sock`, JSON lines:
  - `{"cmd":"status"}` → connection state, current values, config.
  - `{"cmd":"reload"}` → re-read config.
  - `{"cmd":"preview","values":[..4..],"seconds":N}` → show fixed values.
  - `{"cmd":"test"}` → run segment test pattern.
  - `{"cmd":"pause"|"resume"}`.
  - `{"cmd":"sensors"}` → list of sources with current values.

### cli.py
`darkflash-lcd daemon | status | sensors | show V0 V1 V2 V3 [--seconds N] |
test | pause | resume | config get/set | doctor`.
`doctor` checks: USB device present, hidraw node, permissions, udev rule
installed, service active, sensors detected; if the USB device is absent it
suggests checking the internal USB 2.0 header cable.

### GUI (PySide6, optional extra `[gui]`)
- Main window: live circular mock of the display mirroring daemon status; four
  source pickers filtered by compatible kind; °C/°F; refresh interval; status
  line (Connected / Not found / No permission) with a "How do I fix this?"
  dialog; "Test display" button; "Apply" saves config and sends `reload`;
  "Start service" button when the daemon isn't running.
- Tray icon: menu shows current temperature, Open settings, Pause display,
  Quit tray. Quitting the tray never stops the daemon. Optional "Start tray
  with session" (autostart `.desktop`).
- en/es strings chosen from the system locale.

## Installation

- udev rule `/etc/udev/rules.d/70-darkflash-lcd.rules`:
  `SUBSYSTEM=="hidraw", ATTRS{idVendor}=="5131", ATTRS{idProduct}=="2007", TAG+="uaccess"`
  (only step needing sudo). README notes that some generic card readers share
  this ID and the rule is harmless for them.
- `install.sh`: check Python ≥ 3.10; install with `pipx` if present, else into
  `~/.local/share/darkflash-lcd/venv` with wrappers in `~/.local/bin`; ask
  whether to include the GUI; install udev rule and reload; install + enable
  the user service, `.desktop` and icon; run `doctor`.
- `uninstall.sh` reverts everything.
- Dependencies: `psutil`; optional `PySide6`. License MIT.
- GitHub Actions runs pytest + ruff on push. Release tag `v0.1.0`.
- Discoverability: README title and repo description/topics include darkFlash,
  DN240D, DN360D, Nebula, AIO, LCD, Linux, 5131:2007.

## Testing

- `protocol`: exact byte expectations derived from the Windows logic (digits,
  blanking, segment table, symbol bits, E-blink alternation, clamping, closing
  packet, sequence wrap).
- `sensors`: fake hwmon tree in `tmp_path` (k10temp, coretemp, amdgpu, no fans);
  sysfs root injectable.
- `config`: missing, valid, invalid files.
- `daemon`: fake device that records packets — loop, reload, preview, pause,
  reconnect after disconnect.
- GUI: manual testing only.

### Hardware validation (first implementation step)
1. Minimal script sends a fixed frame (e.g. 42.5 °C, 12 %, 34 %, 1234 MHz);
   the user reports what the display shows (photo if needed).
2. Discrepancies fix `protocol.py` and become regression tests.
3. Verify closing packet and test pattern / ring behaviour.
