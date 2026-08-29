#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import openrazer.client


SERPENT_DIR = Path.home() / ".local" / "share" / "serpent"
sys.path.insert(0, str(SERPENT_DIR))

from serpent_core.version import VERSION  # noqa: E402

from serpent_core.backends.base import BackendError  # noqa: E402
from serpent_core.backends.registry import create_backend  # noqa: E402
from serpent_core.discovery import detect_fixture  # noqa: E402
from serpent_core.fixtures import (  # noqa: E402
    Fixture,
    FixtureError,
    find_fixture_by_id,
)
from serpent_core.identity import (  # noqa: E402
    MatchConfidence,
    match_fixture_identity,
)
from serpent_core.ownership import (  # noqa: E402
    current_owner,
    set_owner,
)
from serpent_core.effect_cli import (
    add_sync_effect_arguments,
    effect_directory_text,
    effect_list_text,
    effect_show_text,
    validate_sync_effect_arguments,
)
from serpent_core.effects import (  # noqa: E402
    effect_ids,
    reload_effect_plugins,
)
from serpent_core.live_preview import (  # noqa: E402
    clear_preview_request,
    preview_path,
    read_preview_request,
    write_preview_request,
)
from serpent_core.rendering import (  # noqa: E402
    sync_rendering_reports,
)
from serpent_core.reactive_diagnostics import (  # noqa: E402
    format_input_status,
    probe_input,
)
from serpent_core.scene_application import (  # noqa: E402
    SceneApplicationError,
    apply_scene,
)
from serpent_core.scene_repository import (  # noqa: E402
    DEFAULT_SCENE_DIR,
    SceneRepository,
    SceneRepositoryError,
)
from serpent_core.scene_runtime import (  # noqa: E402
    SerpentSceneRuntime,
)
from serpent_core.scenes import scene_to_dict  # noqa: E402


MOUSE_FIXTURE_ID = "razer-naga-v2-pro-wireless"
KEYBOARD_FIXTURE_ID = "razer-deathstalker-v2"

CONFIG_DIR = Path.home() / ".config" / "serpent"
PROFILE_PATH = CONFIG_DIR / "profile.json"

NAGA_PROFILE_PATH = PROFILE_PATH


class SerpentError(RuntimeError):
    """An error that can be shown directly to the user."""


def default_profile() -> dict[str, Any]:
    return {
        "version": VERSION,
        "keyboard": {
            "effect": "spectrum",
            "brightness": 76,
            "colour1": [0, 0, 255],
            "colour2": [0, 255, 255],
            "speed": 2,
            "direction": 2,
        },
    }


def save_profile(profile: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing_groups = None
    existing_version = None
    if PROFILE_PATH.exists():
        try:
            existing = json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
            existing_sync = existing.get('sync', {}) if isinstance(existing, dict) else {}
            if isinstance(existing_sync, dict):
                existing_groups = existing_sync.get('groups')
                existing_version = existing_sync.get('group_schema_version')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    sync = profile.get('sync')
    if isinstance(sync, dict) and 'groups' not in sync and existing_groups is not None:
        sync['groups'] = existing_groups
        if existing_version is not None: sync['group_schema_version'] = existing_version
    temp_path = PROFILE_PATH.with_name(PROFILE_PATH.name + '.tmp')
    temp_path.write_text(json.dumps(profile, indent=4) + '\n', encoding='utf-8')
    temp_path.replace(PROFILE_PATH)



def load_profile() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not PROFILE_PATH.exists():
        profile = default_profile()
        save_profile(profile)
        return profile

    profile = json.loads(
        PROFILE_PATH.read_text(encoding="utf-8")
    )

    if "keyboard" not in profile:
        profile["keyboard"] = default_profile()["keyboard"]

    defaults = default_profile()["keyboard"]

    for key, value in defaults.items():
        profile["keyboard"].setdefault(key, value)

    profile["version"] = VERSION
    return profile


def load_openrazer_devices() -> list[Any]:
    manager = openrazer.client.DeviceManager()
    return list(manager.devices)


def find_openrazer_device(
    fixture: Fixture,
    devices: list[Any] | None = None,
) -> Any:
    """Resolve a fixture through Serpent's shared identity policy."""

    if devices is None:
        devices = load_openrazer_devices()

    match = match_fixture_identity(
        fixture,
        devices,
    )

    if not match.matched or match.device is None:
        raise SerpentError(
            f"OpenRazer could not match fixture "
            f"{fixture.id!r}: {match.reason} "
            "Check that the device is connected and "
            "openrazer-daemon.service is running."
        )

    return match.device


def fixture_identity_note(
    fixture: Fixture,
    device: Any,
) -> str | None:
    """Return a human-readable note when fallback identity was used."""

    match = match_fixture_identity(
        fixture,
        [device],
    )

    if match.confidence == MatchConfidence.FALLBACK:
        serial = match.actual_serial or "<missing>"
        return (
            "Generated serial fallback "
            f"({serial})"
        )

    if match.confidence == MatchConfidence.NAME_ONLY:
        return "Matched by model name"

    return None


def validate_colour(
    colour: list[int] | tuple[int, ...] | None,
) -> tuple[int, int, int]:
    if colour is None or len(colour) != 3:
        raise SerpentError(
            "A colour requires exactly three values: R G B."
        )

    values = tuple(int(value) for value in colour)

    if any(value < 0 or value > 255 for value in values):
        raise SerpentError(
            "RGB values must be between 0 and 255."
        )

    return values[0], values[1], values[2]


def validate_brightness(value: int) -> int:
    brightness = int(value)

    if brightness < 0 or brightness > 100:
        raise SerpentError(
            "Brightness must be between 0 and 100."
        )

    return brightness


def run_command(command: list[str]) -> None:
    result = subprocess.run(command, check=False)

    if result.returncode != 0:
        raise SerpentError(
            f"Command failed with exit status "
            f"{result.returncode}: "
            + " ".join(command)
        )


# ---------------------------------------------------------------------------
# Mouse backend
# ---------------------------------------------------------------------------

def load_mouse_profile() -> dict[str, Any]:
    if not NAGA_PROFILE_PATH.exists():
        return {}

    try:
        data = json.loads(
            NAGA_PROFILE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}

    return data.get("mouse", {})


def mouse_status() -> None:
    fixture = find_fixture_by_id(MOUSE_FIXTURE_ID)
    mouse = find_openrazer_device(fixture)
    profile = load_mouse_profile()
    detected = detect_fixture(fixture)

    print("Mouse")
    print("-----")
    print(f"Fixture: {fixture.id}")
    print(f"Name: {mouse.name}")
    print(f"Serial: {mouse.serial}")

    identity_note = fixture_identity_note(
        fixture,
        mouse,
    )

    if identity_note is not None:
        print(f"Identity: {identity_note}")

    print(f"Battery: {mouse.battery_level}%")
    print(f"Charging: {mouse.is_charging}")
    print(f"DPI: {mouse.dpi}")
    print(f"Polling rate: {mouse.poll_rate} Hz")
    print(f"Saved effect: {profile.get('effect', 'unknown')}")
    print(
        "Saved brightness: "
        f"{profile.get('brightness', 'unknown')}%"
    )

    if detected is not None:
        print(f"Sysfs device: {detected.sysfs_path}")


def set_mouse(args: argparse.Namespace) -> None:
    fixture = find_fixture_by_id(MOUSE_FIXTURE_ID)
    detected = detect_fixture(fixture)

    if detected is None:
        raise SerpentError(
            f"Fixture device is not connected: {fixture.id}"
        )

    openrazer_device = find_openrazer_device(fixture)

    backend = create_backend(
        fixture,
        detected.sysfs_path,
        openrazer_device=openrazer_device,
    )

    settings: dict[str, Any] = {
        "effect": args.effect,
    }

    if args.brightness is not None:
        settings["brightness"] = validate_brightness(
            args.brightness
        )

    if args.colour1 is not None:
        settings["colour1"] = list(
            validate_colour(args.colour1)
        )

    if args.colour2 is not None:
        settings["colour2"] = list(
            validate_colour(args.colour2)
        )

    if args.speed is not None:
        settings["speed"] = int(args.speed)

    backend.apply(args.effect, settings)

    print(
        f"Applied {args.effect} through the "
        f"fixture-selected backend and saved it to "
        f"{PROFILE_PATH}."
    )

# ---------------------------------------------------------------------------
# Fixture-selected keyboard backend
# ---------------------------------------------------------------------------

def get_keyboard_runtime() -> tuple[
    Fixture,
    Any,
    Any,
]:
    fixture = find_fixture_by_id(KEYBOARD_FIXTURE_ID)
    detected = detect_fixture(fixture)

    if detected is None:
        raise SerpentError(
            f"Fixture device is not connected: {fixture.id}"
        )

    openrazer_device = find_openrazer_device(fixture)

    backend = create_backend(
        fixture,
        detected.sysfs_path,
        openrazer_device=openrazer_device,
    )

    return fixture, detected, backend


def keyboard_status() -> None:
    fixture, detected, backend = get_keyboard_runtime()
    keyboard = backend.openrazer_device
    settings = load_profile()["keyboard"]

    print("Keyboard")
    print("--------")
    print(f"Fixture: {fixture.id}")
    print(f"Name: {keyboard.name}")
    print(f"Serial: {keyboard.serial}")

    identity_note = fixture_identity_note(
        fixture,
        keyboard,
    )

    if identity_note is not None:
        print(f"Identity: {identity_note}")

    print(f"Backend: {backend.backend_type}")
    print(f"Brightness: {keyboard.brightness}%")

    advanced = getattr(
        getattr(keyboard, "fx", None),
        "advanced",
        None,
    )

    if advanced is not None:
        print(
            f"Matrix: {advanced.rows} × {advanced.cols}"
        )

    print(f"Saved effect: {settings['effect']}")
    print(
        f"Saved brightness: "
        f"{settings['brightness']}%"
    )
    print(f"Sysfs device: {detected.sysfs_path}")


def apply_keyboard_settings(
    settings: dict[str, Any],
) -> None:
    from serpent_core.effect_capability import effect_support_mode

    fixture, _detected, backend = get_keyboard_runtime()
    effect = str(settings["effect"])
    mode = effect_support_mode(fixture, effect)

    if mode is None:
        raise SerpentError(
            f"{fixture.display_name} does not support "
            f"the effect {effect!r}."
        )

    if mode == "native":
        backend.apply(effect, settings)
        return

    # Dynamic/software effects are rendered by serpent-individual.service
    # from the saved profile. Do not send them to the native backend.
    return


def set_keyboard(args: argparse.Namespace) -> None:
    profile = load_profile()
    settings = profile["keyboard"]

    settings["effect"] = args.effect

    if args.brightness is not None:
        settings["brightness"] = validate_brightness(
            args.brightness
        )

    if args.colour1 is not None:
        settings["colour1"] = list(
            validate_colour(args.colour1)
        )

    if args.colour2 is not None:
        settings["colour2"] = list(
            validate_colour(args.colour2)
        )

    if args.speed is not None:
        settings["speed"] = int(args.speed)

    if args.direction is not None:
        settings["direction"] = int(args.direction)

    apply_keyboard_settings(settings)
    save_profile(profile)

    print(
        f"Applied {settings['effect']} through the "
        f"fixture-selected backend and saved it to "
        f"{PROFILE_PATH}."
    )


def apply_keyboard_profile() -> None:
    profile = load_profile()
    apply_keyboard_settings(profile["keyboard"])

    print(
        "Applied the saved DeathStalker profile through "
        "the fixture-selected backend."
    )


# ---------------------------------------------------------------------------
# Synchronization
# ---------------------------------------------------------------------------

SYNC_SERVICE = "serpent-sync.service"

def sync_effect_ids() -> tuple[str, ...]:
    # Keep CLI effect choices aligned with the live plugin registry.
    return effect_ids()


def effect_reload() -> None:
    active_sync = (
        current_owner() == 'sync'
        and unit_state(SYNC_SERVICE) == 'active'
    )
    required_effect = None

    if active_sync:
        profile = load_profile()
        sync = load_sync_profile(profile)
        value = sync.get('effect')
        if isinstance(value, str) and value:
            required_effect = value

    try:
        result = reload_effect_plugins(
            required_effect_id=required_effect,
        )
    except ValueError as exc:
        raise SerpentError(str(exc)) from exc

    print(
        'Validated fresh user effect registry: '
        f'added={len(result.added)}, '
        f'removed={len(result.removed)}, '
        f'reloaded={len(result.reloaded)}.'
    )

    if not active_sync:
        print(
            'No active synchronization engine needed signaling; '
            'new Serpent processes will use the refreshed files.'
        )
        return

    signal_result = systemctl_user(
        'kill',
        SYNC_SERVICE,
        '--kill-who=main',
        '--signal=HUP',
    )
    if signal_result.returncode != 0:
        raise SerpentError(
            signal_result.stdout.strip()
            or 'Could not signal the synchronization engine.'
        )

    print(
        'Signaled the active synchronization engine to reload '
        'plugins in-process without releasing lighting ownership.'
    )



def _preview_parameter_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("colour1", "colour2", "speed", "direction"):
        value = getattr(args, key, None)
        if value is None:
            continue
        if key in {"colour1", "colour2"}:
            payload[key] = list(validate_colour(value))
        elif key in {"speed", "direction"}:
            payload[key] = int(value)
    return payload


def _signal_sync_hup() -> None:
    result = systemctl_user(
        "kill",
        SYNC_SERVICE,
        "--kill-who=main",
        "--signal=HUP",
    )
    if result.returncode != 0:
        raise SerpentError(
            result.stdout.strip()
            or "Could not signal the synchronization engine."
        )


def sync_preview_start(args: argparse.Namespace) -> None:
    if current_owner() != "sync" or unit_state(SYNC_SERVICE) != "active":
        raise SerpentError(
            "Live preview requires an active synchronized lighting engine."
        )

    try:
        validate_sync_effect_arguments(args)
    except ValueError as exc:
        raise SerpentError(str(exc)) from exc

    parameters = _preview_parameter_payload(args)
    owner_pid = (
        int(args.owner_pid)
        if getattr(args, "owner_pid", None) is not None
        else os.getppid()
    )

    previous = None
    try:
        previous = read_preview_request()
    except Exception:
        clear_preview_request()

    write_preview_request(
        args.effect,
        parameters,
        owner_pid=owner_pid,
    )

    try:
        _signal_sync_hup()
    except Exception:
        clear_preview_request()
        if previous is not None:
            write_preview_request(
                previous.effect,
                previous.parameters,
                owner_pid=previous.owner_pid,
            )
        raise

    print(
        f"Started temporary live preview of {args.effect}. "
        "The saved Serpent profile was not modified."
    )


def sync_preview_stop() -> None:
    previous = None
    try:
        previous = read_preview_request()
    except Exception:
        pass

    clear_preview_request()

    if current_owner() == "sync" and unit_state(SYNC_SERVICE) == "active":
        try:
            _signal_sync_hup()
        except Exception:
            if previous is not None:
                write_preview_request(
                    previous.effect,
                    previous.parameters,
                    owner_pid=previous.owner_pid,
                )
            raise

    print(
        "Stopped temporary live preview. "
        "Saved synchronization settings are active again."
    )


def sync_preview_status() -> None:
    try:
        request = read_preview_request()
    except Exception as exc:
        print("Live preview: invalid")
        print(f"Error: {type(exc).__name__}: {exc}")
        return

    if request is None:
        print("Live preview: inactive")
        return

    print("Live preview: active")
    print(f"Effect: {request.effect}")
    print(f"Owner PID: {request.owner_pid if request.owner_pid else 'unbound'}")
    print("Parameters: " + json.dumps(request.parameters, sort_keys=True))
    print(f"Runtime request: {preview_path()}")

def default_sync_profile() -> dict[str, Any]:
    return {
        "enabled": False,
        "effect": "spectrum",
        "speed": 2,
        "colour1": [255, 0, 255],
        "colour2": [0, 255, 255],
        "keyboard_brightness": 35,
        "mouse_brightness": 35,
        "member_brightness": {
            "razer-deathstalker-v2:matrix": 35,
            "razer-naga-v2-pro-wireless:logo": 35,
            "razer-naga-v2-pro-wireless:side-buttons": 35,
        },
        "frame_interval": 0.06,
        "direction": 1,
        "members": [
            "razer-deathstalker-v2:matrix",
            "razer-naga-v2-pro-wireless:logo",
            "razer-naga-v2-pro-wireless:side-buttons",
        ],
    }


def load_sync_profile(
    profile: dict[str, Any],
) -> dict[str, Any]:
    sync = profile.get("sync")

    if not isinstance(sync, dict):
        sync = default_sync_profile()
        profile["sync"] = sync

    defaults = default_sync_profile()

    for key, value in defaults.items():
        sync.setdefault(key, value)

    members = sync.get("members", [])
    member_brightness = sync.get("member_brightness")

    if not isinstance(member_brightness, dict):
        member_brightness = {}
        sync["member_brightness"] = member_brightness

    if isinstance(members, list):
        for member in members:
            if not isinstance(member, str):
                continue

            if member in member_brightness:
                continue

            if member.startswith("razer-deathstalker-v2:"):
                fallback = sync.get("keyboard_brightness", 35)
            elif member.startswith("razer-naga-v2-pro-wireless:"):
                fallback = sync.get("mouse_brightness", 35)
            else:
                fallback = 35

            member_brightness[member] = validate_brightness(
                fallback
            )

    return sync


def systemctl_user(
    action: str,
    service: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "systemctl",
            "--user",
            action,
            *extra,
            service,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def sync_enable(args: argparse.Namespace) -> None:
    try:
        validate_sync_effect_arguments(args)
    except ValueError as exc:
        raise SerpentError(str(exc)) from exc

    profile = load_profile()
    sync = load_sync_profile(profile)

    sync["enabled"] = True
    sync["effect"] = args.effect

    if args.speed is not None:
        speed = int(args.speed)

        if speed < 1:
            raise SerpentError(
                "Synchronization speed must be at least 1."
            )

        sync["speed"] = speed

    if args.colour1 is not None:
        sync["colour1"] = list(
            validate_colour(args.colour1)
        )

    if args.colour2 is not None:
        sync["colour2"] = list(
            validate_colour(args.colour2)
        )

    member_brightness = sync.setdefault(
        "member_brightness",
        {},
    )

    if not isinstance(member_brightness, dict):
        member_brightness = {}
        sync["member_brightness"] = member_brightness

    if args.keyboard_brightness is not None:
        value = validate_brightness(
            args.keyboard_brightness
        )
        sync["keyboard_brightness"] = value

        for member in sync.get("members", []):
            if (
                isinstance(member, str)
                and member.startswith("razer-deathstalker-v2:")
            ):
                member_brightness[member] = value

    if args.mouse_brightness is not None:
        value = validate_brightness(
            args.mouse_brightness
        )
        sync["mouse_brightness"] = value

        for member in sync.get("members", []):
            if (
                isinstance(member, str)
                and member.startswith("razer-naga-v2-pro-wireless:")
            ):
                member_brightness[member] = value

    if args.member_brightness:
        valid_members = {
            member
            for member in sync.get("members", [])
            if isinstance(member, str)
        }

        for member, raw_brightness in args.member_brightness:
            if member not in valid_members:
                raise SerpentError(
                    "Member is not part of the synchronization group: "
                    f"{member}"
                )

            member_brightness[member] = validate_brightness(
                raw_brightness
            )

    if args.direction is not None:
        sync["direction"] = int(args.direction)

    if args.frame_interval is not None:
        interval = float(args.frame_interval)

        if interval < 0.02 or interval > 1.0:
            raise SerpentError(
                "Frame interval must be between "
                "0.02 and 1.0 seconds."
            )

        sync["frame_interval"] = interval

    save_profile(profile)

    service_state = unit_state(SYNC_SERVICE)

    if (
        service_state == "active"
        and current_owner() == "sync"
    ):
        result = systemctl_user(
            "kill",
            SYNC_SERVICE,
            "--kill-who=main",
            "--signal=HUP",
        )
    else:
        result = systemctl_user(
            "start",
            SYNC_SERVICE,
        )

    if result.returncode != 0:
        # Do not claim that synchronization is enabled when systemd
        # could not start or reload the owner.
        sync["enabled"] = False
        save_profile(profile)

        raise SerpentError(
            result.stdout.strip()
            or "Could not start or reload serpent-sync.service."
        )

    print(
        f"Enabled synchronized {sync['effect']} lighting "
        f"through {SYNC_SERVICE}."
    )


def sync_reload_marker() -> Path:
    runtime_root = Path(
        os.environ.get(
            "XDG_RUNTIME_DIR",
            f"/run/user/{os.getuid()}",
        )
    )

    return runtime_root / "serpent-sync-engine-reload"


def sync_disable_marker() -> Path:
    # Mark an intentional transition from sync ownership to normal.
    runtime_root = Path(
        os.environ.get(
            "XDG_RUNTIME_DIR",
            f"/run/user/{os.getuid()}",
        )
    )

    return runtime_root / "serpent-sync-disable"


def recover_normal_lighting_after_reload_failure() -> None:
    marker = sync_reload_marker()
    marker.unlink(missing_ok=True)

    try:
        set_owner("normal")
    except Exception:
        pass

    systemctl_user(
        "start",
        "serpent-individual.service",
    )

    try:
        apply_keyboard_profile()
    except Exception:
        pass


def sync_reload_engine() -> None:
    owner = current_owner()
    state = unit_state(SYNC_SERVICE)

    if owner != "sync" or state != "active":
        raise SerpentError(
            "Synchronization is not currently active. "
            "Enable a synchronized effect before reloading "
            "the engine."
        )

    marker = sync_reload_marker()
    marker.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    marker.write_text(
        "reload\n",
        encoding="ascii",
    )

    result = systemctl_user(
        "restart",
        SYNC_SERVICE,
    )

    if result.returncode != 0:
        recover_normal_lighting_after_reload_failure()

        raise SerpentError(
            result.stdout.strip()
            or "Could not reload the synchronization engine."
        )

    marker.unlink(missing_ok=True)

    if (
        current_owner() != "sync"
        or unit_state(SYNC_SERVICE) != "active"
        or unit_state("serpent-individual.service") != "inactive"
    ):
        recover_normal_lighting_after_reload_failure()

        raise SerpentError(
            "Synchronization engine reload finished in an "
            "inconsistent ownership/service state. "
            "Normal lighting was restored for safety."
        )

    print(
        "Reloaded the synchronization engine without "
        "releasing lighting ownership."
    )


def sync_disable() -> None:
    profile = load_profile()
    sync = load_sync_profile(profile)
    sync["enabled"] = False
    save_profile(profile)

    marker = sync_disable_marker()
    marker.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    marker.write_text(
        "disable\n",
        encoding="ascii",
    )

    result = systemctl_user(
        "stop",
        SYNC_SERVICE,
    )

    if result.returncode != 0:
        marker.unlink(missing_ok=True)

        raise SerpentError(
            result.stdout.strip()
            or "Could not stop serpent-sync.service."
        )

    marker.unlink(missing_ok=True)

    print(
        "Disabled synchronized lighting and restored "
        "the normal device profiles."
    )


def unit_state(service: str) -> str:
    result = systemctl_user(
        "is-active",
        service,
    )

    return result.stdout.strip() or "unknown"


def sync_status() -> None:
    profile = load_profile()
    sync = load_sync_profile(profile)

    owner = current_owner()
    sync_state = unit_state(SYNC_SERVICE)
    mouse_state = unit_state(
        "serpent-individual.service"
    )

    print("Synchronization")
    print("---------------")
    print(f"Configured: {bool(sync.get('enabled', False))}")
    print(f"Owner: {owner}")
    print(f"Service: {sync_state}")
    print(f"Individual renderer: {mouse_state}")
    print(f"Effect: {sync.get('effect', 'unknown')}")
    print(f"Speed: {sync.get('speed', 'unknown')}")
    print(
        "Keyboard brightness: "
        f"{sync.get('keyboard_brightness', 'unknown')}%"
    )
    print(
        "Mouse brightness: "
        f"{sync.get('mouse_brightness', 'unknown')}%"
    )

    member_brightness = sync.get(
        "member_brightness",
        {},
    )

    if isinstance(member_brightness, dict):
        print("Member brightness:")

        for member in sync.get("members", []):
            if not isinstance(member, str):
                continue

            value = member_brightness.get(
                member,
                "unknown",
            )
            print(f"  - {member}: {value}%")

    print(
        "Frame interval: "
        f"{sync.get('frame_interval', 'unknown')} s"
    )
    print(
        "Direction: "
        f"{sync.get('direction', 1)}"
    )

    members = sync.get("members", [])

    if isinstance(members, list):
        print("Members:")

        for member in members:
            print(f"  - {member}")

    print()
    print("Rendering")
    print("---------")

    try:
        reports = sync_rendering_reports(sync)
    except Exception as exc:
        print(f"Unavailable: {exc}")
    else:
        for report in reports:
            print(f"{report.device_name}:")
            print(
                f"  Capability: {report.capability}"
            )
            print(
                f"  Policy: {report.policy}"
            )
            print(
                f"  Result: {report.result}"
            )

    healthy = (
        owner == "sync"
        and sync_state == "active"
        and mouse_state == "inactive"
    )

    if healthy:
        print("State: synchronized")
    elif (
        owner == "normal"
        and sync_state == "inactive"
        and mouse_state == "active"
    ):
        print("State: normal")
    else:
        print("State: inconsistent")


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def scene_repository() -> SceneRepository:
    configured = os.environ.get("SERPENT_SCENE_DIR")

    if configured:
        return SceneRepository(
            Path(configured).expanduser()
        )

    return SceneRepository(DEFAULT_SCENE_DIR)


def scene_list() -> None:
    repository = scene_repository()
    scenes = repository.list_scenes()
    invalid = repository.invalid_files()

    print("Scenes")
    print("------")

    if not scenes:
        print("No saved scenes.")
    else:
        for scene in scenes:
            print(
                f"{scene.id}: {scene.name} "
                f"({scene.mode})"
            )

    if invalid:
        print()
        print("Invalid scene files")
        print("-------------------")

        for path, reason in invalid:
            print(f"{path.name}: {reason}")


def scene_show(scene_id: str) -> None:
    scene = scene_repository().load(scene_id)
    print(
        json.dumps(
            scene_to_dict(scene),
            indent=2,
            ensure_ascii=False,
        )
    )


def scene_apply(scene_id: str) -> None:
    scene = scene_repository().load(scene_id)
    plan = apply_scene(
        scene,
        SerpentSceneRuntime(),
    )

    print(
        f"Applied scene {plan.scene_name!r} "
        f"({plan.scene_id}) in {plan.mode} mode."
    )


def scene_delete(
    scene_id: str,
    *,
    confirmed: bool,
) -> None:
    if not confirmed:
        raise SerpentError(
            "Scene deletion requires --yes."
        )

    scene = scene_repository().load(scene_id)
    scene_repository().delete(scene_id)

    print(
        f"Deleted scene {scene.name!r} "
        f"({scene.id})."
    )


# ---------------------------------------------------------------------------
# Unified commands
# ---------------------------------------------------------------------------

def run_doctor() -> int:
    result = subprocess.run(
        [str(SERPENT_DIR / "doctor.py")],
        check=False,
    )
    return int(result.returncode)


def input_status() -> None:
    print(format_input_status())


def input_probe(args: argparse.Namespace) -> None:
    probe_input(
        args.capability,
        seconds=args.seconds,
        max_events=args.max_events,
    )


def show_status() -> None:
    print(f"Serpent {VERSION}")
    print("=" * 32)
    print()

    try:
        mouse_status()
    except Exception as exc:
        print("Mouse")
        print("-----")
        print(f"Unavailable: {exc}")

    print()

    try:
        keyboard_status()
    except Exception as exc:
        print("Keyboard")
        print("--------")
        print(f"Unavailable: {exc}")


def set_all_static(args: argparse.Namespace) -> None:
    colour = validate_colour(args.colour1)
    brightness = validate_brightness(args.brightness)

    mouse_args = argparse.Namespace(
        effect="static",
        colour1=list(colour),
        colour2=None,
        brightness=brightness,
        speed=None,
    )

    set_mouse(mouse_args)

    keyboard_args = argparse.Namespace(
        effect="static",
        colour1=list(colour),
        colour2=None,
        brightness=brightness,
        speed=None,
        direction=None,
    )

    set_keyboard(keyboard_args)

    print(
        "Applied matching Static lighting to both devices."
    )


def add_common_effect_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--colour1",
        nargs=3,
        type=int,
        metavar=("R", "G", "B"),
    )

    parser.add_argument(
        "--colour2",
        nargs=3,
        type=int,
        metavar=("R", "G", "B"),
    )

    parser.add_argument(
        "--brightness",
        type=int,
    )

    parser.add_argument(
        "--speed",
        type=int,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serpent",
        description=(
            "Unified fixture-driven lighting controller "
            "for supported Razer devices."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"Serpent {VERSION}",
    )

    root = parser.add_subparsers(
        dest="root_command",
        required=True,
    )

    root.add_parser("status")
    root.add_parser(
        "doctor",
        help="Run Serpent installation and reactive-input diagnostics.",
    )

    input_parser = root.add_parser(
        "input",
        help="Inspect or non-exclusively probe reactive input sources.",
    )
    input_commands = input_parser.add_subparsers(
        dest="input_command",
        required=True,
    )
    input_commands.add_parser("status")
    input_probe_parser = input_commands.add_parser(
        "probe",
        help="Temporarily observe translated reactive input events.",
    )
    input_probe_parser.add_argument(
        "capability",
        choices=("keyboard", "mouse"),
    )
    input_probe_parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
    )
    input_probe_parser.add_argument(
        "--max-events",
        type=int,
        default=20,
    )

    mouse = root.add_parser("mouse")
    mouse_commands = mouse.add_subparsers(
        dest="mouse_command",
        required=True,
    )

    mouse_commands.add_parser("status")

    mouse_set = mouse_commands.add_parser("set")
    mouse_set.add_argument(
        "effect",
        choices=(
            "off",
            "static",
            "spectrum",
            "breath-single",
            "breath-dual",
        ),
    )

    add_common_effect_arguments(mouse_set)

    keyboard = root.add_parser("keyboard")
    keyboard_commands = keyboard.add_subparsers(
        dest="keyboard_command",
        required=True,
    )

    keyboard_commands.add_parser("status")
    keyboard_commands.add_parser("apply-profile")

    keyboard_set = keyboard_commands.add_parser("set")
    keyboard_set.add_argument(
        "effect",
        choices=(
            "off",
            "static",
            "spectrum",
            "wave",
            "reactive",
            "breath-random",
            "breath-single",
            "breath-dual",
            "starlight-random",
            "starlight-single",
            "starlight-dual",
        ),
    )

    add_common_effect_arguments(keyboard_set)

    keyboard_set.add_argument(
        "--direction",
        type=int,
        choices=(1, 2),
    )

    effect_parser = root.add_parser(
        "effect",
        help="Inspect dynamically discovered effect plugins.",
    )
    effect_commands = effect_parser.add_subparsers(
        dest="effect_command",
        required=True,
    )
    effect_commands.add_parser("list")
    effect_commands.add_parser("directory")
    effect_commands.add_parser(
        "reload",
        help="Validate and hot-reload installed user effect plugins.",
    )
    effect_show = effect_commands.add_parser("show")
    effect_show.add_argument(
        "effect",
        choices=sync_effect_ids(),
    )

    sync = root.add_parser("sync")
    sync_commands = sync.add_subparsers(
        dest="sync_command",
        required=True,
    )

    sync_enable_parser = sync_commands.add_parser("enable")
    sync_enable_parser.add_argument(
        "effect",
        choices=sync_effect_ids(),
    )
    add_sync_effect_arguments(sync_enable_parser)
    sync_enable_parser.add_argument(
        "--keyboard-brightness",
        type=int,
    )
    sync_enable_parser.add_argument(
        "--mouse-brightness",
        type=int,
    )
    sync_enable_parser.add_argument(
        "--member-brightness",
        nargs=2,
        action="append",
        default=[],
        metavar=("MEMBER", "PERCENT"),
        help=(
            "Set brightness for one synchronized member. "
            "May be supplied more than once."
        ),
    )
    sync_enable_parser.add_argument(
        "--frame-interval",
        type=float,
    )

    sync_commands.add_parser("disable")
    sync_commands.add_parser("reload-engine")
    sync_commands.add_parser("status")

    preview_start = sync_commands.add_parser("preview-start")
    preview_start.add_argument(
        "effect",
        choices=sync_effect_ids(),
    )
    add_sync_effect_arguments(preview_start)
    preview_start.add_argument(
        "--owner-pid",
        type=int,
        help=argparse.SUPPRESS,
    )
    sync_commands.add_parser("preview-stop")
    sync_commands.add_parser("preview-status")

    scene = root.add_parser("scene")
    scene_commands = scene.add_subparsers(
        dest="scene_command",
        required=True,
    )

    scene_commands.add_parser("list")

    scene_show_parser = scene_commands.add_parser("show")
    scene_show_parser.add_argument("scene_id")

    scene_apply_parser = scene_commands.add_parser("apply")
    scene_apply_parser.add_argument("scene_id")

    scene_delete_parser = scene_commands.add_parser("delete")
    scene_delete_parser.add_argument("scene_id")
    scene_delete_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm permanent deletion.",
    )

    all_parser = root.add_parser("all")
    all_commands = all_parser.add_subparsers(
        dest="all_command",
        required=True,
    )

    all_static = all_commands.add_parser("static")

    all_static.add_argument(
        "--colour1",
        nargs=3,
        type=int,
        required=True,
        metavar=("R", "G", "B"),
    )

    all_static.add_argument(
        "--brightness",
        type=int,
        default=20,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.root_command == "status":
            show_status()

        elif args.root_command == "doctor":
            return run_doctor()

        elif args.root_command == "input":
            if args.input_command == "status":
                input_status()
            elif args.input_command == "probe":
                input_probe(args)

        elif args.root_command == "mouse":
            if args.mouse_command == "status":
                mouse_status()
            elif args.mouse_command == "set":
                set_mouse(args)

        elif args.root_command == "keyboard":
            if args.keyboard_command == "status":
                keyboard_status()
            elif args.keyboard_command == "set":
                set_keyboard(args)
            elif args.keyboard_command == "apply-profile":
                apply_keyboard_profile()

        elif args.root_command == "effect":
            if args.effect_command == "list":
                print(effect_list_text())
            elif args.effect_command == "directory":
                print(effect_directory_text())
            elif args.effect_command == "show":
                print(effect_show_text(args.effect))
            elif args.effect_command == "reload":
                effect_reload()

        elif args.root_command == "sync":
            if args.sync_command == "enable":
                sync_enable(args)
            elif args.sync_command == "disable":
                sync_disable()
            elif args.sync_command == "reload-engine":
                sync_reload_engine()
            elif args.sync_command == "status":
                sync_status()
            elif args.sync_command == "preview-start":
                sync_preview_start(args)
            elif args.sync_command == "preview-stop":
                sync_preview_stop()
            elif args.sync_command == "preview-status":
                sync_preview_status()

        elif args.root_command == "scene":
            if args.scene_command == "list":
                scene_list()
            elif args.scene_command == "show":
                scene_show(args.scene_id)
            elif args.scene_command == "apply":
                scene_apply(args.scene_id)
            elif args.scene_command == "delete":
                scene_delete(
                    args.scene_id,
                    confirmed=args.yes,
                )

        elif args.root_command == "all":
            if args.all_command == "static":
                set_all_static(args)

    except (
        SerpentError,
        SceneApplicationError,
        SceneRepositoryError,
        BackendError,
        FixtureError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"Serpent error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
