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
