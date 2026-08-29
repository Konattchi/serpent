#!/usr/bin/env bash
set -euo pipefail
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/serpent"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$SYSTEMD_DIR"
(cd "$SRC_DIR" && tar --exclude='./.git' --exclude='./packaging' --exclude='./bin' --exclude='./install.sh' --exclude='./uninstall.sh' -cf - .) | (cd "$APP_DIR" && tar -xf -)
install -m 0755 "$SRC_DIR/bin/serpent-gui" "$BIN_DIR/serpent-gui"
install -m 0755 "$SRC_DIR/bin/serpent" "$BIN_DIR/serpent"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
sed "s|^Icon=.*$|Icon=$APP_DIR/resources/visual_identity/icons/app/serpent_256.png|" "$SRC_DIR/packaging/applications/serpent.desktop" > "$tmp"
install -m 0644 "$tmp" "$DESKTOP_DIR/serpent.desktop"
for unit in "$SRC_DIR"/packaging/systemd/user/*.service; do install -m 0644 "$unit" "$SYSTEMD_DIR/$(basename "$unit")"; done
systemctl --user daemon-reload
printf 'Serpent installed. Run: serpent doctor\n'
printf 'Service enablement is not forced; Startup/tray autostart remains a user preference.\n'
