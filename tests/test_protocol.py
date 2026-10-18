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
