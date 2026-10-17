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
