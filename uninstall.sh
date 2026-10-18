#!/usr/bin/env bash
set -uo pipefail
systemctl --user disable --now darkflash-lcd.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/darkflash-lcd.service"
systemctl --user daemon-reload
command -v pipx >/dev/null && pipx uninstall darkflash-lcd 2>/dev/null
rm -rf "$HOME/.local/share/darkflash-lcd"
rm -f "$HOME/.local/bin/darkflash-lcd" "$HOME/.local/bin/darkflash-lcd-gui"
rm -f "$HOME/.local/share/applications/darkflash-lcd.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/darkflash-lcd.svg" \
      "$HOME/.config/autostart/darkflash-lcd-tray.desktop"
sudo rm -f /etc/udev/rules.d/70-darkflash-lcd.rules && sudo udevadm control --reload
echo "Removed. Your config stays in ~/.config/darkflash-lcd (delete it if you want)."
