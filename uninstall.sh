#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/serpent"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
for unit in serpent-watcher.service serpent-sync.service serpent-restore.service serpent-individual.service; do
  systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_DIR/$unit"
done
systemctl --user daemon-reload
rm -f "$BIN_DIR/serpent-gui" "$BIN_DIR/serpent" "$DESKTOP_DIR/serpent.desktop" "$AUTOSTART_DIR/serpent.desktop"
rm -rf "$APP_DIR"
printf 'Serpent user installation removed.\n'
