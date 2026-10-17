from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import ipc
from .strings import t

AUTOSTART = Path.home() / ".config" / "autostart" / "darkflash-lcd-tray.desktop"
AUTOSTART_TEXT = """[Desktop Entry]
Type=Application
Name=darkFlash LCD (tray)
Exec=darkflash-lcd-gui --tray
Icon=darkflash-lcd
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


class Tray(QSystemTrayIcon):
    def __init__(self, open_window) -> None:
        super().__init__(QIcon.fromTheme("darkflash-lcd", QIcon.fromTheme("temperature-normal")))
        menu = QMenu()
        self.temp = menu.addAction("—")
        self.temp.setEnabled(False)
        menu.addSeparator()
        menu.addAction(t("open"), open_window)
        self.pause = menu.addAction(t("pause"), self.toggle_pause)
        auto = QAction(t("autostart"), menu, checkable=True, checked=AUTOSTART.exists())
        auto.toggled.connect(self.set_autostart)
        menu.addAction(auto)
        menu.addSeparator()
        menu.addAction(t("quit"), QApplication.quit)  # never stops the daemon
        self.setContextMenu(menu)
        self.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and open_window())
        self._menu = menu

    def update_from(self, st: dict | None) -> None:
        if not st or not st.get("reading"):
            self.temp.setText(t("daemon_off") if st is None else "—")
            return
        tt = st["reading"]["temp_tenths"]
        self.temp.setText(f"{tt / 10:.1f} °")
        self.setToolTip(f"darkFlash LCD — {tt / 10:.1f} °")
        self.pause.setText(t("resume") if st.get("paused") else t("pause"))

    def toggle_pause(self) -> None:
        try:
            st = ipc.request({"cmd": "status"})
            ipc.request({"cmd": "resume" if st.get("paused") else "pause"})
        except ConnectionError:
            pass

    @staticmethod
    def set_autostart(on: bool) -> None:
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(AUTOSTART_TEXT)
        else:
            AUTOSTART.unlink(missing_ok=True)
