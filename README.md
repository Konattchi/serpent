# Serpent

Serpent is a fixture-driven RGB device controller for Linux.

## Version
Serpent 1.0.0

## Requirements
Linux, Python 3, PySide6, systemd user services, OpenRazer's Python/daemon stack for supported Razer hardware, and `flock` from util-linux.

## Install
```bash
chmod +x install.sh uninstall.sh
./install.sh
serpent doctor
```

The installer places the application under `~/.local/share/serpent`, installs `serpent` and `serpent-gui` under `~/.local/bin`, installs the desktop entry, and installs the Serpent user-service definitions. It does not force-enable every service or force GUI autostart; Serpent's Startup setting manages tray autostart.

## Uninstall
```bash
./uninstall.sh
```

## Development
Experimental effects and local development projects are intentionally kept outside this release repository.

## AI engineering manual

Developers and AI coding agents should read [`AI_MANUAL.md`](AI_MANUAL.md) before making architectural or runtime changes. It documents Serpent's subsystem boundaries, safe probing/build/install workflow, effect authoring, fixture/device integration, Sync/Scenes ownership rules, testing tiers, and release discipline.

## Hardware extensibility

Serpent 1.0 currently supports Razer devices through OpenRazer on Linux. Serpent's fixture-driven architecture is intentionally designed so support for additional manufacturers can be added through new fixture definitions and hardware/backend integrations while keeping effects, Scenes, Sync, rendering, ownership, and other higher-level systems manufacturer-independent.

Support for a new manufacturer should strengthen the generic fixture/backend contracts rather than introduce manufacturer-specific branches throughout Serpent's core.

## License

Serpent is licensed under the [GNU General Public License v3.0](LICENSE). You may use, study, modify, and redistribute Serpent under the terms of GPL-3.0.

