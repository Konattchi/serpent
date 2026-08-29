#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


HOME: Final = Path.home()

SERPENT_COMMAND: Final = (
    HOME
    / ".local"
    / "bin"
    / "serpent"
)

PROFILE_PATH: Final = (
    HOME
    / ".config"
    / "serpent"
    / "profile.json"
)

MOUSE_FIXTURE_ID: Final = (
    "razer-naga-v2-pro-wireless"
)

KEYBOARD_FIXTURE_ID: Final = (
    "razer-deathstalker-v2"
)

SERVICE_NAMES: Final = (
    "openrazer-daemon.service",
    "serpent-individual.service",
    "serpent-sync.service",
    "serpent-watcher.service",
    "serpent-restore.service",
)


class StatusError(RuntimeError):
    """Raised when device or service status cannot be read."""


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    active: bool
    enabled: bool
    state: str
    healthy: bool


@dataclass(frozen=True)
class ZoneStatus:
    zone_id: str
    name: str
    effect: str
    brightness: int | None


@dataclass(frozen=True)
class MouseStatus:
    connected: bool
    sleeping: bool
    name: str
    battery: int | None
    charging: bool | None
    dpi: str
    polling_rate: str
    linked: bool
    zones: tuple[ZoneStatus, ...]


@dataclass(frozen=True)
class KeyboardStatus:
    connected: bool
    name: str
    brightness: int | None
    matrix: str
    effect: str
    saved_brightness: int | None


def run_command(
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if check and result.returncode != 0:
        output = result.stdout.strip()

        raise StatusError(
            output
            or f"Command failed: {' '.join(arguments)}"
        )

    return result


def parse_status_block(
    output: str,
) -> dict[str, str]:
    values: dict[str, str] = {}

    for line in output.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip()
        value = value.strip()

        if key:
            values[key] = value

    return values


def parse_percentage(
    value: str | None,
) -> int | None:
    if value is None:
        return None

    cleaned = value.strip().rstrip("%")

    if cleaned.lower() in {
        "",
        "unknown",
        "none",
        "n/a",
    }:
        return None

    try:
        return round(float(cleaned))
    except ValueError:
        return None


def parse_boolean(
    value: str | None,
) -> bool | None:
    if value is None:
        return None

    normalised = value.strip().lower()

    if normalised in {
        "true",
        "yes",
        "1",
        "charging",
    }:
        return True

    if normalised in {
        "false",
        "no",
        "0",
        "not charging",
        "discharging",
    }:
        return False

    return None


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {}

    try:
        return json.loads(
            PROFILE_PATH.read_text(
                encoding="utf-8"
            )
        )
    except OSError:
        return {}
    except json.JSONDecodeError:
        return {}


def integer_or_none(
    value: Any,
) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def mouse_zone_statuses(
    profile: dict[str, Any],
) -> tuple[bool, tuple[ZoneStatus, ...]]:
    mouse = profile.get("mouse", {})

    if not isinstance(mouse, dict):
        return True, ()

    zones = mouse.get("zones")

    if not isinstance(zones, dict):
        effect = str(
            mouse.get("effect", "unknown")
        )

        brightness = integer_or_none(
            mouse.get("brightness")
        )

        legacy_zone = ZoneStatus(
            zone_id="all",
            name="All Zones",
            effect=effect,
            brightness=brightness,
        )

        return True, (legacy_zone,)

    linked = bool(
        mouse.get("linked", True)
    )

    zone_names = {
        "logo": "Logo",
        "side-buttons": "Side Buttons",
    }

    result: list[ZoneStatus] = []

    for zone_id in (
        "logo",
        "side-buttons",
    ):
        settings = zones.get(zone_id, {})

        if not isinstance(settings, dict):
            settings = {}

        result.append(
            ZoneStatus(
                zone_id=zone_id,
                name=zone_names[zone_id],
                effect=str(
                    settings.get(
                        "effect",
                        "unknown",
                    )
                ),
                brightness=integer_or_none(
                    settings.get("brightness")
                ),
            )
        )

    return linked, tuple(result)


def mouse_status() -> MouseStatus:
    result = run_command(
        [
            str(SERPENT_COMMAND),
            "mouse",
            "status",
        ],
        check=False,
    )

    profile = load_profile()
    linked, zones = mouse_zone_statuses(
        profile
    )

    if result.returncode != 0:
        return MouseStatus(
            connected=False,
            sleeping=False,
            name="Razer Naga V2 Pro",
            battery=None,
            charging=None,
            dpi="Unknown",
            polling_rate="Unknown",
            linked=linked,
            zones=zones,
        )

    values = parse_status_block(
        result.stdout
    )

    battery = parse_percentage(
        values.get("Battery")
    )

    dpi = values.get(
        "DPI",
        "Unknown",
    )

    sleeping = (
        battery == 0
        and dpi.replace(" ", "") == "(0,0)"
    )

    if sleeping:
        battery = None

    return MouseStatus(
        connected=True,
        sleeping=sleeping,
        name=values.get(
            "Name",
            "Razer Naga V2 Pro",
        ),
        battery=battery,
        charging=parse_boolean(
            values.get("Charging")
        ),
        dpi=dpi,
        polling_rate=values.get(
            "Polling rate",
            "Unknown",
        ),
        linked=linked,
        zones=zones,
    )


def keyboard_status() -> KeyboardStatus:
    result = run_command(
        [
            str(SERPENT_COMMAND),
            "keyboard",
            "status",
        ],
        check=False,
    )

    if result.returncode != 0:
        return KeyboardStatus(
            connected=False,
            name="Razer DeathStalker V2",
            brightness=None,
            matrix="Unknown",
            effect="Unknown",
            saved_brightness=None,
        )

    values = parse_status_block(
        result.stdout
    )

    return KeyboardStatus(
        connected=True,
        name=values.get(
            "Name",
            "Razer DeathStalker V2",
        ),
        brightness=parse_percentage(
            values.get("Brightness")
        ),
        matrix=values.get(
            "Matrix",
            "Unknown",
        ),
        effect=values.get(
            "Saved effect",
            values.get(
                "Reported effect",
                "Unknown",
            ),
        ),
        saved_brightness=parse_percentage(
            values.get(
                "Saved brightness"
            )
        ),
    )


def lighting_owner() -> str:
    result = run_command(
        [
            str(SERPENT_COMMAND),
            "sync",
            "status",
        ],
        check=False,
    )

    if result.returncode != 0:
        return "unknown"

    for line in result.stdout.splitlines():
        if line.startswith("Owner:"):
            return line.split(":", 1)[1].strip()

    return "unknown"


def service_status(
    service_name: str,
    *,
    owner: str = "unknown",
) -> ServiceStatus:
    active_result = run_command(
        [
            "systemctl",
            "--user",
            "is-active",
            service_name,
        ],
        check=False,
    )

    state = (
        active_result.stdout.strip()
        or "unknown"
    )

    active = (
        active_result.returncode == 0
        and state == "active"
    )

    enabled_result = run_command(
        [
            "systemctl",
            "--user",
            "is-enabled",
            service_name,
        ],
        check=False,
    )

    enabled_state = (
        enabled_result.stdout.strip()
        or "unknown"
    )

    enabled = enabled_state in {
        "enabled",
        "static",
        "indirect",
    }

    if service_name == "serpent-restore.service":
        healthy = enabled and state in {
            "active",
            "inactive",
        }
    elif service_name == "serpent-individual.service":
        healthy = enabled and (
            (owner == "normal" and active)
            or (owner == "sync" and not active)
        )
    elif service_name == "serpent-sync.service":
        healthy = (
            (owner == "sync" and active)
            or (owner == "normal" and not active)
        )
    else:
        healthy = active and enabled

    if (
        service_name == "serpent-individual.service"
        and owner == "sync"
        and not active
    ):
        healthy = True
        state = "standby"

    return ServiceStatus(
        name=service_name,
        active=active,
        enabled=enabled,
        state=state,
        healthy=healthy,
    )


def all_service_statuses() -> list[ServiceStatus]:
    owner = lighting_owner()

    return [
        service_status(
            service_name,
            owner=owner,
        )
        for service_name in SERVICE_NAMES
    ]


def connected_fixture_ids() -> set[str]:
    result = run_command(
        [
            str(SERPENT_COMMAND),
            "fixtures",
            "detect",
        ],
        check=False,
    )

    if result.returncode != 0:
        return set()

    connected: set[str] = set()

    for line in result.stdout.splitlines():
        stripped = line.strip()

        if stripped.startswith("✓ "):
            fixture_id = stripped[2:].strip()

            if fixture_id:
                connected.add(fixture_id)

    return connected


def summary() -> dict[str, object]:
    return {
        "mouse": mouse_status(),
        "keyboard": keyboard_status(),
        "services": all_service_statuses(),
        "fixtures": connected_fixture_ids(),
    }


def format_percentage(
    value: int | None,
) -> str:
    if value is None:
        return "Unavailable"

    return f"{value}%"


def format_zone(
    zone: ZoneStatus,
) -> str:
    brightness = format_percentage(
        zone.brightness
    )

    return (
        f"{zone.name}: "
        f"{zone.effect}, "
        f"{brightness}"
    )


def main() -> int:
    mouse = mouse_status()
    keyboard = keyboard_status()
    services = all_service_statuses()

    print("Mouse")
    print("-----")
    print(f"Connected: {mouse.connected}")
    print(f"Sleeping: {mouse.sleeping}")
    print(f"Name: {mouse.name}")

    if mouse.sleeping:
        print("Battery: Sleeping")
    else:
        print(
            f"Battery: "
            f"{format_percentage(mouse.battery)}"
        )

    print(f"Charging: {mouse.charging}")
    print(f"DPI: {mouse.dpi}")
    print(
        f"Polling rate: "
        f"{mouse.polling_rate}"
    )
    print(f"Zones linked: {mouse.linked}")

    for zone in mouse.zones:
        print(format_zone(zone))

    print()

    print("Keyboard")
    print("--------")
    print(f"Connected: {keyboard.connected}")
    print(f"Name: {keyboard.name}")
    print(f"Effect: {keyboard.effect}")
    print(
        "Brightness: "
        + format_percentage(
            keyboard.saved_brightness
        )
    )
    print(f"Matrix: {keyboard.matrix}")
    print()

    print("Services")
    print("--------")

    for service in services:
        print(
            f"{service.name}: "
            f"active={service.active}, "
            f"enabled={service.enabled}, "
            f"state={service.state}, "
            f"healthy={service.healthy}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
