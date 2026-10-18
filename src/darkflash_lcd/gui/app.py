from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .. import ipc
from .main_window import MainWindow
from .tray import Tray


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("darkflash-lcd")
    app.setDesktopFileName("darkflash-lcd")
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    win = MainWindow()

    def show_window() -> None:
        win.load_form()
        win.show()
        win.raise_()
        win.activateWindow()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = Tray(show_window)
        tray.show()

        def poll() -> None:
            try:
                tray.update_from(ipc.request({"cmd": "status"}))
            except ConnectionError:
                tray.update_from(None)

        QTimer(app, interval=2000, timeout=poll).start()
        poll()
    if "--tray" not in argv or not QSystemTrayIcon.isSystemTrayAvailable():
        show_window()
    return app.exec()
