"""Tiny en/es string table. Add a language by adding a dict."""

from __future__ import annotations

import os

STRINGS = {
    "en": {
        "doctor.usb_ok": "USB device 5131:2007 found ({node})",
        "doctor.usb_missing": "Cooler not found on USB. Check that the pump's USB cable is plugged into an internal USB 2.0 header on the motherboard.",
        "doctor.perm_ok": "Write access to {path}",
        "doctor.perm_missing": "No permission on {path}. Install the udev rule: sudo cp packaging/70-darkflash-lcd.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger",
        "doctor.rule_ok": "udev rule installed",
        "doctor.rule_missing": "udev rule not installed (70-darkflash-lcd.rules)",
        "doctor.daemon_ok": "Daemon running, display {conn}",
        "doctor.daemon_missing": "Daemon not running. Start it: systemctl --user enable --now darkflash-lcd",
        "doctor.sensors": "Sensors detected: {n} ({ids})",
        "status.connected": "connected", "status.not_found": "not found",
        "status.no_permission": "no permission", "status.error": "error",
        "no_daemon": "The darkflash-lcd daemon is not running (systemctl --user start darkflash-lcd).",
    },
    "es": {
        "doctor.usb_ok": "Dispositivo USB 5131:2007 encontrado ({node})",
        "doctor.usb_missing": "No se encontró la líquida por USB. Revisa que el cable USB de la bomba esté conectado a un header USB 2.0 interno de la placa madre.",
        "doctor.perm_ok": "Acceso de escritura a {path}",
        "doctor.perm_missing": "Sin permisos en {path}. Instala la regla udev: sudo cp packaging/70-darkflash-lcd.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger",
        "doctor.rule_ok": "Regla udev instalada",
        "doctor.rule_missing": "Regla udev no instalada (70-darkflash-lcd.rules)",
        "doctor.daemon_ok": "Servicio activo, pantalla {conn}",
        "doctor.daemon_missing": "El servicio no está activo. Inícialo: systemctl --user enable --now darkflash-lcd",
        "doctor.sensors": "Sensores detectados: {n} ({ids})",
        "status.connected": "conectada", "status.not_found": "no encontrada",
        "status.no_permission": "sin permisos", "status.error": "error",
        "no_daemon": "El servicio darkflash-lcd no está activo (systemctl --user start darkflash-lcd).",
    },
}


def current_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return "es" if v.startswith("es") else "en"
    return "en"


def t(key: str, lang: str | None = None, **kw) -> str:
    table = STRINGS.get(lang or current_lang(), STRINGS["en"])
    return table.get(key, STRINGS["en"][key]).format(**kw)
