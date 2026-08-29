# Serpent

Serpent is a fixture-driven RGB device controller for Linux. It is designed to give Linux users a single place to discover supported lighting hardware, control devices individually, run software-driven effects, synchronize multiple devices, build Scenes, and manage the runtime services that keep those effects active.

Serpent 1.0 currently supports Razer hardware through OpenRazer, but the application is deliberately structured so that Razer/OpenRazer is a backend implementation rather than the architectural identity of the project. Device anatomy, lighting regions, capabilities, input mappings, and rendering behavior are described through fixtures and generic backend contracts, leaving room for future manufacturer integrations without rewriting the higher-level effect and scene systems.

## What Serpent can do

- **Discover and control supported RGB devices** through a fixture-driven device model rather than hard-coded GUI assumptions.
- **Run per-device lighting effects**, including built-in effects and installable effect plugins.
- **Render software effects** such as gradients, spectrum patterns, waves, starlight, reactive ripple, explosions, moving bands, and other plugin effects included with the project.
- **React to input events** for effects that declare reactive capabilities, allowing lighting behavior to respond to keyboard or mouse activity where the fixture/backend supports it.
- **Synchronize multiple devices** through Serpent's Sync system while preserving each device's physical topology and logical lighting regions.
- **Create and apply Scenes** that describe coordinated device/effect state and are applied through the same ownership and runtime paths used by normal device control.
- **Manage device ownership and runtime services** so individual control, synchronized control, restore behavior, and watcher behavior do not compete for the same hardware at the same time.
- **Work from the system tray** with optional tray-only startup and desktop-session autostart managed from Serpent's Startup setting.
- **Inspect installation and runtime health** with `serpent doctor`, which checks the pieces Serpent depends on instead of relying on silent assumptions.
- **Author and test effects** using Serpent's effect development/Workshop tooling, including isolated preview/testing infrastructure for effect development.
- **Extend hardware support** by adding fixture definitions and backend/transport support instead of adding model-specific logic throughout the application.

## How Serpent is structured

A **fixture** describes what a physical device is: its identity, lighting regions, geometry/topology, controllable capabilities, and relevant input anatomy. A **backend** handles how those capabilities are actually communicated to hardware. Effects, rendering, Scenes, Sync, ownership, and the GUI operate on those generic contracts.

That separation is important. A keyboard, mouse, mousepad, or future device from another manufacturer should be able to participate in the same Serpent systems once its physical capabilities and transport are implemented. Generic effects should not need to know whether the hardware underneath them is Razer or something else.

Serpent also keeps a clear distinction between the source repository, the installed runtime under `~/.local/share/serpent`, and local experimental work. The GitHub repository is intended to stay clean and reproducible rather than becoming a dumping ground for generated files, probes, backups, or unfinished effect experiments.

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

After installation, launch the GUI with:

```bash
serpent-gui
```

or use the installed desktop entry. The command-line entry point is:

```bash
serpent
```

For a basic health check:

```bash
serpent doctor
```

## Uninstall

```bash
./uninstall.sh
```

## Development

Experimental effects and local development projects are intentionally kept outside this release repository. Production effects, fixtures, backends, runtime logic, and documentation belong here only after they meet the same architectural and release standards as the rest of Serpent.

## AI engineering manual

Developers and AI coding agents should read [`AI_MANUAL.md`](AI_MANUAL.md) before making architectural or runtime changes. It documents Serpent's subsystem boundaries, safe probing/build/install workflow, effect authoring, fixture/device integration, Sync/Scenes ownership rules, testing tiers, and release discipline.

The companion documents under [`docs/ai/`](docs/ai/) provide focused references for architecture, effects, fixtures/devices, runtime services, GUI/Scenes/Sync, testing/debugging, release packaging, and historical design context.

## Hardware extensibility

Serpent 1.0 currently supports Razer devices through OpenRazer on Linux. Serpent's fixture-driven architecture is intentionally designed so support for additional manufacturers can be added through new fixture definitions and hardware/backend integrations while keeping effects, Scenes, Sync, rendering, ownership, and other higher-level systems manufacturer-independent.

Support for a new manufacturer should strengthen the generic fixture/backend contracts rather than introduce manufacturer-specific branches throughout Serpent's core.

A useful design test is: if the same capability appeared tomorrow on hardware from a different manufacturer, would the implementation still be correct? If the answer is no, the abstraction probably belongs lower in the fixture/backend layer.

## License

Serpent is licensed under the [GNU General Public License v3.0](LICENSE). You may use, study, modify, and redistribute Serpent under the terms of GPL-3.0.
