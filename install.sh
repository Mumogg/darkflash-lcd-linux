#!/usr/bin/env bash
# darkflash-lcd installer — works on any systemd distro. Only the udev rule needs sudo.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10+ required"

GUI=""
if [[ "${1:-}" == "--no-gui" ]]; then GUI=""
elif [[ "${1:-}" == "--gui" ]]; then GUI="[gui]"
else
  read -r -p "Install the graphical app too (PySide6, ~200 MB)? [Y/n] " a || a=""
  [[ -z "$a" || "$a" =~ ^[YySs] ]] && GUI="[gui]"
fi

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
if command -v pipx >/dev/null; then
  say "Installing with pipx"
  pipx install --force ".$GUI"
else
  VENV="$HOME/.local/share/darkflash-lcd/venv"
  say "Installing into $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q ".$GUI"
  ln -sf "$VENV/bin/darkflash-lcd" "$BIN/darkflash-lcd"
  [[ -n "$GUI" ]] && ln -sf "$VENV/bin/darkflash-lcd-gui" "$BIN/darkflash-lcd-gui"
fi

RULE=/etc/udev/rules.d/70-darkflash-lcd.rules
if cmp -s packaging/70-darkflash-lcd.rules "$RULE"; then
  say "udev rule already installed"
else
  say "Installing udev rule (needs sudo)"
  sudo install -m 644 packaging/70-darkflash-lcd.rules "$RULE"
  sudo udevadm control --reload
  sudo udevadm trigger --subsystem-match=hidraw
fi

say "Installing user service"
install -Dm644 packaging/darkflash-lcd.service "$HOME/.config/systemd/user/darkflash-lcd.service"
systemctl --user daemon-reload
systemctl --user enable darkflash-lcd.service
systemctl --user restart darkflash-lcd.service  # also picks up new code when updating

if [[ -n "$GUI" ]]; then
  GUI_EXE="$(command -v darkflash-lcd-gui || echo "$BIN/darkflash-lcd-gui")"
  mkdir -p "$HOME/.local/share/applications"
  # absolute Exec path: ~/.local/bin is not on the desktop session's PATH everywhere
  sed "s|^Exec=darkflash-lcd-gui|Exec=$GUI_EXE|" packaging/darkflash-lcd.desktop \
    > "$HOME/.local/share/applications/darkflash-lcd.desktop"
  install -Dm644 packaging/darkflash-lcd.svg "$HOME/.local/share/icons/hicolor/scalable/apps/darkflash-lcd.svg"
fi

sleep 1
say "Checking setup"
"$BIN/darkflash-lcd" doctor || true
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH." ;; esac
