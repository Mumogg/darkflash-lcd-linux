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
