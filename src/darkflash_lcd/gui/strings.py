from ..i18n import current_lang

_S = {
    "en": {"title": "darkFlash LCD", "big": "Big field (°C)", "left": "Left circle (CPU label)",
           "right": "Right circle (RAM label)", "bottom": "Bottom (MHz / RPM)", "unit": "Temperature unit",
           "interval": "Refresh (ms)", "apply": "Apply", "test": "Test display",
           "start": "Start service", "help": "How do I fix this?", "pause": "Pause display",
           "resume": "Resume display", "open": "Open settings", "quit": "Quit tray",
           "autostart": "Start tray with session", "daemon_off": "Service not running",
           "connected": "Display connected", "not_found": "Cooler not found",
           "no_permission": "No permission (udev rule missing)", "error": "Display error",
           "f_note": "The display always prints °C; with °F the number is Fahrenheit.",
           "help_text": "Not found: plug the pump's USB cable into an internal USB 2.0 header.\nNo permission: run install.sh again (it installs the udev rule), then replug or reboot."},
    "es": {"title": "darkFlash LCD", "big": "Campo grande (°C)", "left": "Círculo izquierdo (dice CPU)",
           "right": "Círculo derecho (dice RAM)", "bottom": "Abajo (MHz / RPM)", "unit": "Unidad de temperatura",
           "interval": "Refresco (ms)", "apply": "Aplicar", "test": "Probar pantalla",
           "start": "Iniciar servicio", "help": "¿Cómo lo arreglo?", "pause": "Pausar pantalla",
           "resume": "Reanudar pantalla", "open": "Abrir configuración", "quit": "Salir de la bandeja",
           "autostart": "Iniciar bandeja con la sesión", "daemon_off": "El servicio no está activo",
           "connected": "Pantalla conectada", "not_found": "Líquida no encontrada",
           "no_permission": "Sin permisos (falta la regla udev)", "error": "Error de pantalla",
           "f_note": "La pantalla siempre muestra °C; con °F el número es en Fahrenheit.",
           "help_text": "No encontrada: conecta el cable USB de la bomba a un header USB 2.0 interno.\nSin permisos: vuelve a ejecutar install.sh (instala la regla udev) y reconecta o reinicia."},
}


def t(key: str) -> str:
    return _S.get(current_lang(), _S["en"]).get(key, _S["en"][key])
