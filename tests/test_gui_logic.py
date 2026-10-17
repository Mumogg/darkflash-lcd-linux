import pytest

pytest.importorskip("PySide6")

from darkflash_lcd.gui.main_window import options_for_field

SENSORS = [
    {"id": "cpu.temp", "name": "CPU temperature", "kind": "temp", "unit": "°C", "value": 50.0},
    {"id": "cpu.usage", "name": "CPU usage", "kind": "percent", "unit": "%", "value": 3.0},
    {"id": "cpu.freq", "name": "CPU frequency", "kind": "freq", "unit": "MHz", "value": 4000.0},
    {"id": "hwmon.nct.fan2", "name": "nct CPU_FAN", "kind": "rpm", "unit": "RPM", "value": None},
]


def test_options_filtered_by_kind():
    assert [i for i, _ in options_for_field(0, SENSORS)] == ["cpu.temp"]
    assert [i for i, _ in options_for_field(1, SENSORS)] == ["cpu.temp", "cpu.usage"]
    assert [i for i, _ in options_for_field(3, SENSORS)] == ["cpu.freq", "hwmon.nct.fan2"]


def test_option_label_shows_value():
    assert "50.0 °C" in options_for_field(0, SENSORS)[0][1]


def test_display_widget_paints_offscreen(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from darkflash_lcd.gui.display_widget import DisplayWidget

    app = QApplication.instance() or QApplication([])
    w = DisplayWidget()
    w.resize(300, 300)
    for reading, online in ((None, False), ({"temp_tenths": 1234, "left": 5, "right": 199, "bottom": 42}, True)):
        w.set_reading(reading, online)
        assert not w.grab().isNull()
    app.processEvents()
