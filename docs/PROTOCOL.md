# darkFlash DN240D / DN360D display protocol

Reverse-engineered from the official Windows app (`frmMain.SendData2`,
`TM1721_show1`, `TM1721_show2`). The Linux encoder in
`src/darkflash_lcd/protocol.py` is verified byte-for-byte against the original
code (see `tools/reverse/` and `tests/fixtures/windows_golden.json`).

## Device

- USB HID `5131:2007`, full speed, no strings. `lsusb` mislabels it as
  "MSR-101U Mini HID magnetic card reader".
- Report descriptor: vendor page `0xFF00`, 64-byte input and 64-byte output,
  **no report ID**. On Linux write `b"\x00" + payload[64]` to `/dev/hidrawN`.
- The display is a fixed-segment LCD driven by a Titan Micro TM1721. It cannot
  show images.

## Packet (64 bytes, sent every refresh; Windows uses 200 ms)

Values: `v0` big field (temperature × 10), `v1` left round field, `v2` right
round field, `v3` bottom 4-digit field.

| bytes | content |
|---|---|
| 0 | sequence counter (wraps at 256) |
| 1 | 0; the app sends a lone packet with `byte[1] = 15` when it exits |
| 2 | 1 |
| 5–7 | v0 hundreds, tens, units (raw digits) |
| 9–11 | v1 digits |
| 13–15 | v2 digits |
| 16–19 | v3 digits |
| 24–39 | TM1721 segment RAM, bank 1 (the visible fields) |
| 40–55 | TM1721 segment RAM, bank 2 |

### Bank 1 rules

- Bottom field: one-byte glyphs, units..thousands in bank bytes 0..3; up to 3
  leading zeros are blanked.
- Right round field: tens byte 5, units byte 4 (one-byte glyphs); hundreds is a
  single "1" segment (byte 6 bit `0x02`, lit for any non-zero hundreds digit);
  tens is blanked only when hundreds and tens are both 0.
- Left round field: split glyphs (high nibble byte n, low nibble byte n+1), tens
  at 7/8, units at 6/7; hundreds "1" = byte 7 bit `0x80`; same blanking rule.
- Big field: split glyphs, hundreds 10/11, tens 9/10, units 8/9; hundreds
  blanked when 0; decimal point byte 9 bit `0x80`.
- v0 ≥ 1000 (≥ 100.0 °C): every packet alternates between "EE" (no point) and
  `v0 // 10` without decimal point.
- Values above 199 in the round fields render garbage in the original app; the
  Linux port clamps them to 199.

### Bank 2

Carries a 2-digit integer temperature (`v0 // 10`, ≥ 100 shows a fixed pattern)
and two 12-step bar graphs driven by `v2` and `0` (that is exactly what the
Windows app sends). Probably for another display variant; harmless here.

### Ring

Code for a 60-segment ring exists (`smg88_60`, `TM1721_show3..5`) but is never
called for this device.

## Hardware-validated (2026-10-17, DN240D, Linux 7.2 / Nobara)

Frames sent with `scripts/hw_smoke.py` and checked on the real pump display:

| frame | sent (v0, v1, v2, v3) | observed |
|---|---|---|
| a | 425, 12, 34, 1234 | `42.5°C`, CPU `12%`, RAM `34%`, `1234MHz`; blue ring lit |
| b | 999, 188, 199, 9999 | `99.9°C`, CPU `188%`, RAM `199%`, `9999MHz` |
| c | 5, 1, 7, 8 | `0.5°C`, `1%`, `7%`, `8MHz` — no leading zeros |
| e | 1234, 100, 100, 1000 | big field blinks `EE` / `123` (no point), `100%` both, `1000MHz` |
| close | closing packet | whole display goes completely black |

Field mapping confirmed: `left` (v1) = circle labelled CPU, `right` (v2) = circle
labelled RAM. The blue ring is lit whenever the display shows data and is not
controlled by the packet.
