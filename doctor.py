#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import openrazer.client


HOME = Path.home()
SERPENT_DIR = HOME / ".local" / "share" / "serpent"
SERPENT_CORE = SERPENT_DIR / "serpent.py"

sys.path.insert(0, str(SERPENT_DIR))

from serpent_core.discovery import detect_fixture  # noqa: E402
from serpent_core.fixtures import (  # noqa: E402
    Fixture,
    FixtureError,
    load_all_fixtures,
)
from serpent_core.identity import (  # noqa: E402
    MatchConfidence,
    match_fixture_identity,
)
from serpent_core.ownership import current_owner  # noqa: E402
from serpent_core.rendering import (  # noqa: E402
    sync_rendering_reports,
)
from serpent_core.reactive_diagnostics import (  # noqa: E402
    INPUT_ACCESS_MODE,
    explicit_reactive_effects,
    input_source_reports,
)


SERPENT_PROFILE = (
    HOME / ".config" / "serpent" / "profile.json"
)
OPENRAZER_CONFIG = (
    HOME / ".config" / "openrazer" / "razer.conf"
)

USER_SERVICES = (
    "openrazer-daemon.service",
    "serpent-individual.service",
    "serpent-sync.service",
    "serpent-restore.service",
    "serpent-watcher.service",
)

PROBLEMS = 0
WARNINGS = 0


def success(message: str) -> None:
    print(f"✓ {message}")


def warning(message: str) -> None:
    global WARNINGS
    WARNINGS += 1
    print(f"! {message}")


def failure(message: str) -> None:
    global PROBLEMS
    PROBLEMS += 1
    print(f"✗ {message}")


def command_output(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    return result.returncode, result.stdout.strip()


def get_core_version() -> str:
    if not SERPENT_CORE.exists():
        return "unknown"

    code, output = command_output(
        [str(SERPENT_CORE), "--version"]
    )

    if code != 0 or not output:
        return "unknown"

    return output


def check_file(
    path: Path,
    *,
    executable: bool = False,
) -> None:
    if not path.exists():
        failure(f"Missing file: {path}")
        return

    if not path.is_file():
        failure(f"Expected a regular file: {path}")
        return

    if executable and not os.access(path, os.X_OK):
        failure(f"File is not executable: {path}")
        return

    success(f"File available: {path}")


def load_serpent_profile() -> dict[str, Any] | None:
    if not SERPENT_PROFILE.exists():
        failure(
            f"Serpent profile is missing: {SERPENT_PROFILE}"
        )
        return None

    try:
        data = json.loads(
            SERPENT_PROFILE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        failure(f"Serpent profile is unreadable: {exc}")
        return None

    if not isinstance(data, dict):
        failure("Serpent profile root must be a JSON object.")
        return None

    return data


def valid_brightness(
    value: Any,
    *,
    context: str,
) -> bool:
    try:
        brightness = int(value)
    except (TypeError, ValueError):
        failure(f"{context} brightness is not numeric.")
        return False

    if brightness < 0 or brightness > 100:
        failure(
            f"{context} brightness must be between 0 and 100."
        )
        return False

    return True


def valid_colour(
    value: Any,
    *,
    context: str,
) -> bool:
    if (
        not isinstance(value, list)
        or len(value) != 3
    ):
        failure(
            f"{context} colour must contain exactly "
            "three RGB values."
        )
        return False

    try:
        components = [
            int(component)
            for component in value
        ]
    except (TypeError, ValueError):
        failure(f"{context} colour contains a non-integer value.")
        return False

    if any(
        component < 0 or component > 255
        for component in components
    ):
        failure(
            f"{context} RGB values must be between 0 and 255."
        )
        return False

    return True


def check_effect_settings(
    fixture: Fixture,
    settings: dict[str, Any],
    *,
    context: str,
) -> bool:
    valid = True
    effect = settings.get("effect")

    if not isinstance(effect, str):
        failure(f"{context} effect is missing or invalid.")
        return False

    from serpent_core.effect_capability import effect_parameter_contract

    definition = effect_parameter_contract(fixture, effect)

    if not isinstance(definition, dict):
        failure(
            f"{context} uses unsupported effect {effect!r}."
        )
        return False

    if not valid_brightness(
        settings.get("brightness"),
        context=context,
    ):
        valid = False

    colour_count = int(definition.get("colours", 0))

    if colour_count >= 1:
        if not valid_colour(
            settings.get("colour1"),
            context=f"{context} primary",
        ):
            valid = False

    if colour_count >= 2:
        if not valid_colour(
            settings.get("colour2"),
            context=f"{context} secondary",
        ):
            valid = False

    if (
        definition.get("speed")
        or definition.get("speeds")
    ):
        try:
            speed = int(settings.get("speed"))
        except (TypeError, ValueError):
            failure(f"{context} speed is missing or invalid.")
            valid = False
        else:
            allowed = definition.get("speeds")

            if allowed and speed not in allowed:
                failure(
                    f"{context} speed {speed} is not supported."
                )
                valid = False
            elif speed < 1:
                failure(
                    f"{context} speed must be at least 1."
                )
                valid = False

    if definition.get("directions"):
        try:
            direction = int(settings.get("direction"))
        except (TypeError, ValueError):
            failure(
                f"{context} direction is missing or invalid."
            )
            valid = False
        else:
            if direction not in definition["directions"]:
                failure(
                    f"{context} direction {direction} "
                    "is not supported."
                )
                valid = False

    return valid


def check_mouse_profile(
    profile: dict[str, Any],
    fixture: Fixture,
) -> None:
    mouse = profile.get("mouse")

    if not isinstance(mouse, dict):
        failure(
            "Mouse profile section is missing or is not an object."
        )
        return

    zones = mouse.get("zones")

    if not isinstance(zones, dict):
        # Legacy flat profile support.
        if check_effect_settings(
            fixture,
            mouse,
            context="Mouse",
        ):
            success(
                "Mouse legacy profile loaded: "
                f"{mouse.get('effect')}, "
                f"{mouse.get('brightness')}%"
            )

        return

    linked = bool(mouse.get("linked", True))
    visible_zones = fixture.visible_zones()

    success(
        "Mouse profile loaded: "
        f"linked={linked}, "
        f"visible zones={len(visible_zones)}"
    )

    declared_ids = {
        zone.id
        for zone in fixture.lighting_zones
    }

    for zone in visible_zones:
        settings = zones.get(zone.id)

        if not isinstance(settings, dict):
            failure(
                f"Mouse profile is missing visible zone "
                f"{zone.name} ({zone.id})."
            )
            continue

        if check_effect_settings(
            fixture,
            settings,
            context=f"Mouse zone {zone.name}",
        ):
            success(
                f"Mouse zone {zone.name}: "
                f"{settings.get('effect')}, "
                f"{settings.get('brightness')}%"
            )

    for zone_id, settings in zones.items():
        if zone_id in declared_ids:
            continue

        if not isinstance(settings, dict):
            warning(
                f"Mouse profile contains unknown malformed zone "
                f"{zone_id!r}."
            )
        else:
            warning(
                f"Mouse profile contains undeclared zone "
                f"{zone_id!r}; settings were preserved."
            )


def check_keyboard_profile(
    profile: dict[str, Any],
    fixture: Fixture,
) -> None:
    keyboard = profile.get("keyboard")

    if not isinstance(keyboard, dict):
        failure(
            "Keyboard profile section is missing or "
            "is not an object."
        )
        return

    if check_effect_settings(
        fixture,
        keyboard,
        context="Keyboard",
    ):
        success(
            "Keyboard profile loaded: "
            f"effect={keyboard.get('effect')}, "
            f"brightness={keyboard.get('brightness')}%"
        )


def check_profiles(
    fixtures: list[Fixture],
) -> None:
    profile = load_serpent_profile()

    if profile is None:
        return

    by_class = {
        fixture.device_class: fixture
        for fixture in fixtures
    }

    mouse_fixture = by_class.get("mouse")

    if mouse_fixture is None:
        warning(
            "No mouse fixture is available for profile validation."
        )
    else:
        check_mouse_profile(
            profile,
            mouse_fixture,
        )

    keyboard_fixture = by_class.get("keyboard")

    if keyboard_fixture is None:
        warning(
            "No keyboard fixture is available for profile validation."
        )
    else:
        check_keyboard_profile(
            profile,
            keyboard_fixture,
        )



def check_sync_membership() -> None:
    profile = load_serpent_profile()
    if profile is None: return
    sync = profile.get('sync')
    if not isinstance(sync, dict): success('Synchronization profile is not configured.'); return
    groups = sync.get('groups')
    if not isinstance(groups, list): success('Synchronization profile is legacy flat format; M28 migration has not run yet.'); return
    if not groups: success('Synchronization has no configured groups.'); return
    seen_group_ids=set(); seen_members=set()
    for group in groups:
        if not isinstance(group, dict): failure('Synchronization group is not an object.'); continue
        group_id=str(group.get('id','')).strip(); name=str(group.get('name',group_id)).strip()
        if not group_id: failure('Synchronization group has no id.'); continue
        if group_id in seen_group_ids: failure(f'Duplicate synchronization group id {group_id!r}.'); continue
        seen_group_ids.add(group_id); success(f"Sync group {name} ({group_id}): effect={group.get('effect','spectrum')}")
        members=group.get('members',[])
        if not isinstance(members,list): failure(f'Sync group {group_id} members must be a list.'); continue
        for member in members:
            if not isinstance(member,dict): failure(f'Sync group {group_id} contains malformed member.'); continue
            instance_id=str(member.get('instance_id','')); zone_id=str(member.get('zone_id','')); key=f'{instance_id}:{zone_id}'
            if not instance_id or '@' not in instance_id or not zone_id: failure(f'Sync group {group_id} contains malformed physical member {member!r}.'); continue
            if key in seen_members: failure(f'Sync physical member {key} belongs to more than one group.'); continue
            seen_members.add(key); brightness=member.get('brightness',100)
            if isinstance(brightness,bool) or not isinstance(brightness,(int,float)): failure(f'Sync member {key} has invalid brightness {brightness!r}.'); continue
            if brightness<0 or brightness>100: failure(f'Sync member {key} brightness {brightness!r}% is outside 0-100.'); continue
            success(f'  {name} -> {instance_id} -> {zone_id}: brightness={brightness}%')


def check_sync_rendering() -> None:
    profile = load_serpent_profile()

    if profile is None:
        return

    sync = profile.get("sync")

    if not isinstance(sync, dict):
        success(
            "Synchronization profile is not configured."
        )
        return

    try:
        reports = sync_rendering_reports(sync)
    except Exception as exc:
        failure(
            f"Synchronization rendering analysis failed: {exc}"
        )
        return

    for report in reports:
        if not report.uses_fallback:
            success(
                f"{report.device_name}: "
                f"{report.result}"
            )
            continue

        success(
            f"{report.device_name}: "
            f"{report.result} "
            f"(capability={report.capability}, "
            f"policy={report.policy})"
        )


def service_state(
    service: str,
) -> tuple[str, str, int, int]:
    enabled_code, enabled_output = command_output(
        [
            "systemctl",
            "--user",
            "is-enabled",
            service,
        ]
    )

    active_code, active_output = command_output(
        [
            "systemctl",
            "--user",
            "is-active",
            service,
        ]
    )

    return (
        enabled_output or "unknown",
        active_output or "unknown",
        enabled_code,
        active_code,
    )


def check_service(
    service: str,
    *,
    owner: str,
) -> None:
    enabled_state, active_state, enabled_code, active_code = (
        service_state(service)
    )

    installed = enabled_state not in {
        "not-found",
        "unknown",
    }

    if service == "serpent-sync.service":
        if not installed:
            failure(
                "serpent-sync.service is not installed."
            )
            return

        if owner == "sync":
            if active_code == 0 and active_state == "active":
                success(
                    "serpent-sync.service active "
                    "and owns synchronized lighting"
                )
            else:
                failure(
                    "Lighting owner is sync, but "
                    "serpent-sync.service is not active "
                    f"({active_state})."
                )
        else:
            if active_state == "inactive":
                success(
                    "serpent-sync.service inactive "
                    f"while owner is {owner}"
                )
            elif active_state == "failed":
                failure(
                    "serpent-sync.service is failed while "
                    f"owner is {owner}."
                )
            else:
                warning(
                    "serpent-sync.service is active while "
                    f"lighting owner is {owner}."
                )

        return

    if service == "serpent-individual.service":
        if not installed:
            failure(f"{service} is not installed.")
            return

        success(
            f"{service} installed "
            f"(unit state: {enabled_state})"
        )

        if owner == "normal":
            if active_code == 0 and active_state == "active":
                success(f"{service} active in normal mode")
            else:
                failure(
                    f"{service} should be active in normal mode "
                    f"({active_state})"
                )
        else:
            if active_state == "inactive":
                success(
                    f"{service} correctly inactive while "
                    f"owner is {owner}"
                )
            else:
                failure(
                    f"{service} must be inactive while "
                    f"owner is {owner} ({active_state})"
                )

        return

    if enabled_code == 0:
        success(f"{service} enabled")
    else:
        failure(
            f"{service} is not enabled "
            f"({enabled_state})"
        )

    if service == "serpent-restore.service":
        result_code, result_output = command_output(
            [
                "systemctl",
                "--user",
                "show",
                service,
                "--property=Result",
                "--value",
            ]
        )

        if result_code == 0 and result_output == "success":
            success(
                f"{service} last run completed successfully"
            )
        else:
            failure(
                f"{service} last result: "
                f"{result_output or 'unknown'}"
            )

        return

    if active_code == 0:
        success(f"{service} active")
    else:
        failure(
            f"{service} is not active "
            f"({active_state})"
        )


def load_openrazer_devices() -> list[Any]:
    try:
        manager = openrazer.client.DeviceManager()
        return list(manager.devices)
    except Exception as exc:
        failure(f"Could not query OpenRazer: {exc}")
        return []


def fixture_required_endpoints(fixture: Fixture) -> set[str]:
    endpoints: set[str] = set()

    backend = fixture.data.get("backend", {})
    required = backend.get("sysfs_required_endpoint")

    if required:
        endpoints.add(str(required))

    capabilities = fixture.data.get("capabilities", {})

    if capabilities.get("brightness"):
        endpoints.add("matrix_brightness")

    for effect in fixture.data.get("effects", {}).values():
        if not isinstance(effect, dict):
            continue

        endpoint = effect.get("endpoint")

        if endpoint:
            endpoints.add(str(endpoint))

    return endpoints


def check_fixture_definition(fixture: Fixture) -> None:
    success(
        f"Fixture valid: {fixture.id} "
        f"({fixture.display_name})"
    )

    backend = fixture.data.get("backend", {}).get(
        "type",
        "unknown",
    )

    success(
        f"{fixture.id} backend declared: {backend}"
    )

    effects = fixture.data.get("effects", {})

    success(
        f"{fixture.id} declares "
        f"{len(effects)} effect(s)"
    )


def check_fixture_detection(
    fixture: Fixture,
    openrazer_devices: list[Any],
) -> None:
    detected = detect_fixture(fixture)

    if detected is None:
        failure(
            f"{fixture.display_name} was not detected "
            f"through fixture {fixture.id}."
        )
        return

    success(
        f"{fixture.display_name} detected: "
        f"{detected.sysfs_path}"
    )

    identity = match_fixture_identity(
        fixture,
        openrazer_devices,
    )
    openrazer_device = identity.device

    detection = fixture.data.get("detection", {})

    if detection and not identity.matched:
        failure(
            f"OpenRazer did not match fixture "
            f"{fixture.id}: {identity.reason}"
        )
    elif openrazer_device is not None:
        name = getattr(
            openrazer_device,
            "name",
            "Unknown device",
        )

        if identity.confidence == MatchConfidence.FALLBACK:
            serial = identity.actual_serial or "<missing>"
            warning(
                f"OpenRazer matched {fixture.id} by USB ID "
                f"and model because the device currently "
                f"reports generated serial {serial}."
            )
        elif identity.confidence == MatchConfidence.NAME_ONLY:
            warning(
                f"OpenRazer matched {fixture.id} by model name; "
                "the fixture ignores serial identity."
            )
        else:
            success(
                f"OpenRazer matched {fixture.id}: {name}"
            )

        legacy_battery = bool(
            fixture.data.get("capabilities", {}).get("battery", False)
        )
        telemetry = fixture.data.get("telemetry")
        if isinstance(telemetry, dict):
            battery_supported = bool(telemetry.get("battery", legacy_battery))
            charging_supported = bool(telemetry.get("charging", battery_supported))
        else:
            battery_supported = legacy_battery
            charging_supported = legacy_battery

        if battery_supported:
            battery = getattr(openrazer_device, "battery_level", "unknown")
            if callable(battery):
                battery = battery()
            success(f"{fixture.id} battery readable: {battery}%")

        if charging_supported:
            charging = getattr(openrazer_device, "is_charging", None)
            if callable(charging):
                charging = charging()
            if charging is None:
                warning(f"{fixture.id} charging state unavailable.")
            else:
                success(
                    f"{fixture.id} charging readable: "
                    + ("yes" if bool(charging) else "no")
                )

    for endpoint_name in sorted(
        fixture_required_endpoints(fixture)
    ):
        endpoint = detected.sysfs_path / endpoint_name

        if not endpoint.exists():
            failure(
                f"{fixture.id} endpoint missing: "
                f"{endpoint_name}"
            )
            continue

        if not os.access(endpoint, os.W_OK):
            failure(
                f"{fixture.id} endpoint not writable: "
                f"{endpoint}"
            )
            continue

        success(
            f"{fixture.id} endpoint writable: "
            f"{endpoint_name}"
        )


def extract_config_section(
    text: str,
    section_name: str,
) -> str | None:
    header = f"[{section_name}]"
    start = text.find(header)

    if start == -1:
        return None

    remainder = text[start:]
    next_section = remainder.find("\n[", 1)

    if next_section != -1:
        remainder = remainder[:next_section]

    return remainder


def check_fixture_safety(fixture: Fixture) -> None:
    safety = fixture.data.get("safety", {})

    if not safety:
        success(
            f"{fixture.id} has no special safety requirements"
        )
        return

    preserve_driver_mode = safety.get(
        "preserve_driver_mode",
        False,
    )

    if not preserve_driver_mode:
        success(
            f"{fixture.id} requires no driver-mode override"
        )
        return

    required_mode = safety.get("required_driver_mode")
    serial = fixture.data.get(
        "detection",
        {},
    ).get("serial")

    if serial is None:
        failure(
            f"{fixture.id} requires driver-mode safety "
            "but has no detection.serial value."
        )
        return

    if not OPENRAZER_CONFIG.exists():
        failure(
            f"OpenRazer configuration is missing: "
            f"{OPENRAZER_CONFIG}"
        )
        return

    try:
        text = OPENRAZER_CONFIG.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        failure(
            f"Could not read OpenRazer configuration: "
            f"{exc}"
        )
        return

    section = extract_config_section(
        text,
        f"Device:{serial}",
    )

    if section is None:
        failure(
            f"{fixture.id} device section is missing "
            "from razer.conf."
        )
        return

    expected_line = (
        f"driver_mode = {required_mode}"
    )

    if expected_line in section:
        success(
            f"{fixture.id} safety requirement satisfied: "
            f"{expected_line}"
        )
    else:
        failure(
            f"{fixture.id} requires '{expected_line}'."
        )


def check_fixtures() -> list[Fixture]:
    try:
        fixtures = load_all_fixtures()
    except FixtureError as exc:
        failure(f"Fixture loading failed: {exc}")
        return []

    if not fixtures:
        failure("No Serpent fixtures are installed.")
        return []

    success(
        f"Loaded {len(fixtures)} valid fixture(s)"
    )

    for fixture in fixtures:
        check_fixture_definition(fixture)

    return fixtures


def check_reactive_input() -> None:
    success(
        "Reactive event monitor access is "
        f"{INPUT_ACCESS_MODE}"
    )

    reports = input_source_reports()
    if not reports:
        warning("No fixture-defined reactive input sources are installed.")
    else:
        for report in reports:
            label = f"{report.capability} source {report.source_id}"
            if report.available:
                success(
                    f"{label}: "
                    f"{len(report.readable_paths)}/"
                    f"{len(report.event_paths)} configured interface(s) readable"
                )
            else:
                warning(
                    f"{label}: no configured interface is readable"
                )

            if report.details:
                success(
                    f"{report.source_id} input mapping: "
                    + ", ".join(report.details)
                )

            for path in report.event_paths:
                if path in report.readable_paths:
                    success(f"{report.source_id} input readable: {path}")
                elif path in report.existing_paths:
                    warning(
                        f"{report.source_id} input exists but is not readable: "
                        f"{path}"
                    )
                else:
                    warning(
                        f"{report.source_id} configured input missing: {path}"
                    )

    reactive = explicit_reactive_effects()
    if reactive:
        for effect_id, capabilities in reactive:
            success(
                f"Reactive effect {effect_id}: "
                + ", ".join(capabilities)
            )
    else:
        warning("No effects explicitly declare reactive input capabilities.")


def main() -> int:
    core_version = get_core_version()

    print(f"{core_version} Doctor")
    print("=" * 42)
    print()

    print("Installation")
    print("------------")

    check_file(
        SERPENT_CORE,
        executable=True,
    )

    check_file(
        SERPENT_DIR / "doctor.py",
        executable=True,
    )

    check_file(
        SERPENT_DIR / "fixtures_cli.py",
        executable=True,
    )

    check_file(
        SERPENT_DIR / "fixture_usb_ids.py",
        executable=True,
    )

    check_file(
        SERPENT_DIR / "serpent-restore.sh",
        executable=True,
    )

    check_file(
        SERPENT_DIR / "serpent-watcher.sh",
        executable=True,
    )

    check_file(
        SERPENT_DIR / "serpent-trigger-restore.sh",
        executable=True,
    )

    # RC2-D3: Doctor release-policy correction
    # serpent-individual.service invokes this module through /usr/bin/python3,
    # so executable permission on the .py file is not required.
    check_file(
        SERPENT_DIR / "individual_engine.py",
        executable=False,
    )

    if core_version == "unknown":
        failure("Serpent core version could not be read.")
    else:
        success(f"Serpent core responds: {core_version}")

    print()
    print("Fixtures")
    print("--------")

    fixtures = check_fixtures()

    print()
    print("Profiles")
    print("--------")

    check_profiles(fixtures)

    print()
    print("Sync Membership")
    print("---------------")
    check_sync_membership()
    print()

    print("Rendering")
    print("---------")

    check_sync_rendering()

    print()
    print("Services")
    print("--------")

    try:
        owner = current_owner()
    except Exception as exc:
        failure(
            f"Could not read lighting ownership: {exc}"
        )
        owner = "unknown"
    else:
        success(f"Lighting owner: {owner}")

    for service in USER_SERVICES:
        check_service(
            service,
            owner=owner,
        )

    print()
    print("Devices")
    print("-------")

    openrazer_devices = load_openrazer_devices()

    for fixture in fixtures:
        check_fixture_detection(
            fixture,
            openrazer_devices,
        )

    print()
    print("Reactive Input")
    print("--------------")

    check_reactive_input()

    print()
    print("Safety")
    print("------")

    for fixture in fixtures:
        check_fixture_safety(fixture)

    print()
    print("Summary")
    print("-------")

    if PROBLEMS == 0 and WARNINGS == 0:
        success("Serpent installation is healthy.")
        return 0

    if PROBLEMS == 0:
        print(
            f"! Serpent is operational with "
            f"{WARNINGS} warning(s)."
        )
        return 0

    print(
        f"✗ Serpent found {PROBLEMS} problem(s) "
        f"and {WARNINGS} warning(s)."
    )

    print()
    print(
        "Paste this complete output into a support "
        "conversation for diagnosis."
    )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
