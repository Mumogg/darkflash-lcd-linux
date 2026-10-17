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


MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 60000


def validate(cfg: Config) -> str | None:
    """Return an error message, or None if the config is usable."""
    i = cfg.interval_ms
    if not isinstance(i, int) or isinstance(i, bool) or not MIN_INTERVAL_MS <= i <= MAX_INTERVAL_MS:
        return f"interval_ms must be an integer between {MIN_INTERVAL_MS} and {MAX_INTERVAL_MS}"
    if cfg.unit not in ("C", "F"):
        return 'unit must be "C" or "F"'
    f = cfg.fields
    if not (isinstance(f, tuple) and len(f) == 4 and all(isinstance(x, str) and x for x in f)):
        return "fields must be a list of 4 sensor ids"
    return None


def load(path: Path) -> tuple[Config, str | None]:
    if not path.exists():
        return Config(), None
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return Config(), f"{path}: {e}"
    fields = data.get("fields", list(DEFAULT_FIELDS))
    cfg = Config(
        data.get("interval_ms", 500),
        data.get("unit", "C"),
        tuple(fields) if isinstance(fields, list) else fields,
    )
    err = validate(cfg)
    if err:
        return Config(), f"{path}: {err}"
    return cfg, None


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
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
