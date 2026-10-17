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
