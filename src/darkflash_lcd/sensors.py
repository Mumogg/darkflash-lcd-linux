"""System sensor sources (hwmon, cpufreq, psutil, nvidia-smi)."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str  # "temp" | "percent" | "freq" | "rpm"
    unit: str
    read: Callable[[], float | None]


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
        except Exception:  # noqa: BLE001 — a broken sensor must never stop the display loop
            vals[s.id] = None
    return vals
