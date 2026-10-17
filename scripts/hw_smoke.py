"""Send fixed frames to the cooler so a human can confirm what the display shows."""

import sys
import time

sys.path.insert(0, "src")
from darkflash_lcd.device import Device
from darkflash_lcd.protocol import Encoder, Reading, closing_packet

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
