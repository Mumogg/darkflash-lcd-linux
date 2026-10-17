from __future__ import annotations

import subprocess
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import ipc
from ..config import config_path, load, save
from ..fields import FIELD_KINDS
from .display_widget import DisplayWidget
from .strings import t


def options_for_field(field_index: int, sensors: list[dict]) -> list[tuple[str, str]]:
    out = []
    for s in sensors:
        if s["kind"] in FIELD_KINDS[field_index]:
            v = "—" if s["value"] is None else f"{s['value']:.1f} {s['unit']}"
            out.append((s["id"], f"{s['name']}  ({v})"))
    return out


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(t("title"))
        self.display = DisplayWidget()
        self.status = QLabel()
        self.help_btn = QPushButton(t("help"))
        self.start_btn = QPushButton(t("start"))
        self.combos = [QComboBox() for _ in range(4)]
        self.unit = QComboBox()
        self.unit.addItems(["°C", "°F"])
        self.unit.setToolTip(t("f_note"))
        self.interval = QSpinBox()
        self.interval.setRange(100, 5000)
        self.interval.setSingleStep(100)
        apply_btn, test_btn = QPushButton(t("apply")), QPushButton(t("test"))

        form = QFormLayout()
        for key, combo in zip(("big", "left", "right", "bottom"), self.combos):
            form.addRow(t(key), combo)
        form.addRow(t("unit"), self.unit)
        form.addRow(t("interval"), self.interval)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.help_btn)
        status_row.addWidget(self.start_btn)
        buttons = QHBoxLayout()
        buttons.addWidget(test_btn)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.display, 1)
        lay.addLayout(status_row)
        lay.addLayout(form)
        lay.addLayout(buttons)

        apply_btn.clicked.connect(self.apply)
        test_btn.clicked.connect(lambda: self._send({"cmd": "test"}))
        self.help_btn.clicked.connect(lambda: QMessageBox.information(self, t("help"), t("help_text")))
        self.start_btn.clicked.connect(self.start_service)
        self.timer = QTimer(self, interval=1000, timeout=self.refresh)
        self.timer.start()
        self.load_form()
        self.refresh()

    def _send(self, msg: dict) -> dict | None:
        try:
            return ipc.request(msg)
        except ConnectionError:
            return None

    def load_form(self) -> None:
        cfg, _ = load(config_path())
        sensors = (self._send({"cmd": "sensors"}) or {}).get("sensors", [])
        for i, combo in enumerate(self.combos):
            combo.clear()
            for sid, label in options_for_field(i, sensors):
                combo.addItem(label, sid)
            idx = combo.findData(cfg.fields[i])
            if idx < 0:
                combo.addItem(cfg.fields[i], cfg.fields[i])
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        self.unit.setCurrentIndex(1 if cfg.unit == "F" else 0)
        self.interval.setValue(cfg.interval_ms)

    def apply(self) -> None:
        path = config_path()
        cfg, _ = load(path)
        cfg = replace(cfg, fields=tuple(c.currentData() for c in self.combos),
                      unit="F" if self.unit.currentIndex() == 1 else "C",
                      interval_ms=self.interval.value())
        save(path, cfg)
        self._send({"cmd": "reload"})
        self.refresh()

    def start_service(self) -> None:
        subprocess.run(["systemctl", "--user", "start", "darkflash-lcd"], check=False)
        QTimer.singleShot(1500, self.load_form)

    def refresh(self) -> None:
        st = self._send({"cmd": "status"})
        if st is None:
            self.status.setText("⚠ " + t("daemon_off"))
            self.start_btn.show()
            self.help_btn.hide()
            self.display.set_reading(None, False)
            return
        self.start_btn.hide()
        conn = st["connection"]
        self.status.setText(("✔ " if conn == "connected" else "⚠ ") + t(conn))
        self.help_btn.setVisible(conn != "connected")
        self.display.set_reading(st.get("reading"), conn == "connected" and not st.get("paused"))
