#!/usr/bin/env python3

from __future__ import annotations

import json
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from serpent_core.device import (
    DeviceModel,
    build_device_model,
)
from serpent_core.fixtures import (
    FixtureError,
    find_fixture_by_id,
)
from serpent_core.effects import (
    EffectPluginError,
    reload_effect_plugins,
    reset_effect_instance,
)
from serpent_core.ownership import current_owner
from serpent_core.reactive_runtime import ReactiveRuntime
from serpent_core.live_preview import resolve_preview_settings
from serpent_core.discovery import detect_all_fixture_instances
from serpent_core.sync_groups import validate_groups
from serpent_core.sync_group_runtime import build_group_runtime_plans, group_member_brightness, group_to_sync_settings
from serpent_core.sync import (
    apply_member_brightness,
    frame_payload,
    load_sync_settings,
    render_effect_frame,
    require_topology,
)
from serpent_core.sync_region_compositor import compose_region_frames
from serpent_core.region_ownership import personal_region_settings


PROFILE_PATH = (
    Path.home()
    / ".config"
    / "serpent"
    / "profile.json"
)

DEVICE_ROOT = Path("/sys/bus/hid/devices")

KEYBOARD_FIXTURE_ID = "razer-deathstalker-v2"
MOUSE_FIXTURE_ID = "razer-naga-v2-pro-wireless"

RETRY_SECONDS = 1.0
OWNER_CHECK_SECONDS = 1.0

RUNNING = True
RELOAD_REQUESTED = False


@dataclass
class DeviceEndpoints:
    device: DeviceModel
    frame: Path
    custom: Path
    custom_active: bool = False


@dataclass
class SyncRuntimeDevice:
    device: DeviceModel
    topology: object
    endpoints: DeviceEndpoints | None = None


def stop_handler(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def reload_handler(_signum, _frame) -> None:
    global RELOAD_REQUESTED
    RELOAD_REQUESTED = True


def load_profile() -> dict[str, object]:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Serpent profile does not exist: {PROFILE_PATH}"
        )

    data = json.loads(
        PROFILE_PATH.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise ValueError(
            "Serpent profile root must be an object."
        )

    return data


def reload_settings_transactionally(
    current_settings,
    current_member_ids: tuple[str, ...],
):
    """Reload sync settings without sacrificing the active renderer.

    A bad or newly-unsupported profile must not terminate the daemon.
    The previous validated settings remain active until a future reload
    succeeds.
    """

    try:
        profile = load_profile()
        base_candidate = load_sync_settings(profile)
        candidate_member_ids = sync_member_ids_from_profile(profile)
        candidate, preview_request, preview_warning = (
            resolve_preview_settings(base_candidate)
        )
        if preview_warning:
            print(
                "Serpent live preview: " + preview_warning + ".",
                file=sys.stderr,
                flush=True,
            )
        elif preview_request is not None:
            print(
                "Serpent live preview active: "
                f"{preview_request.effect}.",
                file=sys.stderr,
                flush=True,
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        FixtureError,
        json.JSONDecodeError,
    ) as exc:
        print(
            "Serpent synchronization reload rejected; "
            f"keeping previous settings: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return current_settings, current_member_ids, False

    print(
        "Serpent synchronization settings reloaded.",
        file=sys.stderr,
        flush=True,
    )
    return candidate, candidate_member_ids, True


def build_device(fixture_id: str) -> DeviceModel:
    fixture = find_fixture_by_id(fixture_id)
    return build_device_model(fixture)


def sync_runtime_fixture_ids(
    sync_settings: dict[str, object],
) -> tuple[str, ...]:
    # Return unique fixture ids referenced by sync.members, in profile order.
    raw_members = sync_settings.get("members", ())
    if not isinstance(raw_members, (list, tuple)):
        raise ValueError("Synchronization members must be a list.")

    fixture_ids: list[str] = []
    for member in raw_members:
        if not isinstance(member, str) or ":" not in member:
            raise ValueError(f"Invalid synchronization member: {member!r}")
        fixture_id, region_id = member.split(":", 1)
        if not fixture_id or not region_id:
            raise ValueError(f"Invalid synchronization member: {member!r}")
        if fixture_id not in fixture_ids:
            fixture_ids.append(fixture_id)
    return tuple(fixture_ids)


def sync_runtime_devices(
    sync_settings: dict[str, object],
) -> tuple[DeviceModel, ...]:
    return tuple(
        build_device(fixture_id)
        for fixture_id in sync_runtime_fixture_ids(sync_settings)
    )


def sync_member_ids_from_profile(
    profile: dict[str, object],
) -> tuple[str, ...]:
    sync = profile.get("sync")
    if not isinstance(sync, dict):
        raise ValueError("Synchronization profile must be an object.")

    raw_members = sync.get("members", ())
    if not isinstance(raw_members, (list, tuple)):
        raise ValueError("Synchronization members must be a list.")

    # Reuse the M13 member syntax/fixture-id validation.
    sync_runtime_fixture_ids({"members": raw_members})
    return tuple(str(member) for member in raw_members)


def legacy_default_brightness(
    device: DeviceModel,
    settings,
) -> float:
    if device.device_class == "keyboard":
        return settings.keyboard_brightness
    if device.device_class == "mouse":
        return settings.mouse_brightness
    return 100.0


def device_pattern(device: DeviceModel) -> str:
    return f"*{device.usb_id.upper()}*"


def find_endpoints(
    device: DeviceModel,
) -> DeviceEndpoints:
    if device.sysfs_path is not None:
        candidate = Path(device.sysfs_path)
        frame = candidate / "matrix_custom_frame"
        custom = candidate / "matrix_effect_custom"

        if frame.exists() and custom.exists():
            return DeviceEndpoints(
                device=device,
                frame=frame,
                custom=custom,
            )

        raise FileNotFoundError(
            f"{device.name} custom-frame endpoints were not found at "
            f"physical instance {device.instance_id}."
        )

    for candidate in sorted(
        DEVICE_ROOT.glob(device_pattern(device))
    ):
        frame = candidate / "matrix_custom_frame"
        custom = candidate / "matrix_effect_custom"

        if frame.exists() and custom.exists():
            return DeviceEndpoints(
                device=device,
                frame=frame,
                custom=custom,
            )

    raise FileNotFoundError(
        f"{device.name} custom-frame endpoints were not found."
    )




def ensure_custom_mode(
    endpoints: DeviceEndpoints,
) -> None:
    if endpoints.custom_active:
        return

    endpoints.custom.write_bytes(b"\x01")
    endpoints.custom_active = True


def write_frame(
    endpoints: DeviceEndpoints,
    payload: bytes,
) -> bool:
    try:
        ensure_custom_mode(endpoints)
        endpoints.frame.write_bytes(payload)
        return True
    except (FileNotFoundError, PermissionError, OSError):
        endpoints.custom_active = False
        return False


def refresh_endpoints(
    endpoints: DeviceEndpoints | None,
    device: DeviceModel,
) -> DeviceEndpoints | None:
    if endpoints is not None:
        return endpoints

    try:
        return find_endpoints(device)
    except FileNotFoundError:
        return None


def sleep_until(deadline: float) -> None:
    while RUNNING:
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            return

        time.sleep(min(remaining, 0.1))


def sync_groups_from_profile(profile):
    sync = profile.get("sync")
    if not isinstance(sync, dict):
        raise ValueError("Synchronization profile must be an object.")
    if "groups" not in sync:
        raise ValueError("Synchronization profile has not been migrated to physical sync groups.")
    return validate_groups(sync["groups"])


def build_group_runtime_map(groups, previous=None, profile=None):
    """Build exactly one runtime/output owner per connected physical device.

    Group members establish normal Sync participants. When Sync owns lighting,
    connected fixture_devices with saved personal lighting must also have a
    runtime even when none of their regions belongs to a Sync group.
    """
    previous = previous or {}
    detected = detect_all_fixture_instances()
    plans = build_group_runtime_plans(groups, detected)
    result = {}

    detected_by_instance = {
        str(item.instance_id): item
        for item in detected
    }

    for plan in plans:
        for resolved in plan.active_members:
            instance_id = resolved.device.instance_id
            old = previous.get(instance_id)
            result[instance_id] = old or SyncRuntimeDevice(
                device=resolved.device,
                topology=require_topology(resolved.device),
            )

    if isinstance(profile, dict):
        configured = profile.get("fixture_devices", {})
        if isinstance(configured, dict):
            for instance_id, saved in configured.items():
                if (
                    not isinstance(instance_id, str)
                    or not isinstance(saved, dict)
                    or instance_id in result
                ):
                    continue

                fixture_id = saved.get("fixture_id")
                if not isinstance(fixture_id, str) or not fixture_id:
                    continue

                settings = saved.get("settings")
                zones = saved.get("zones")
                has_whole = (
                    isinstance(settings, dict)
                    and isinstance(settings.get("effect"), str)
                    and bool(settings.get("effect"))
                )
                has_zone = (
                    isinstance(zones, dict)
                    and any(
                        isinstance(value, dict)
                        and isinstance(value.get("effect"), str)
                        and bool(value.get("effect"))
                        for value in zones.values()
                    )
                )
                if not (has_whole or has_zone):
                    continue

                live = detected_by_instance.get(instance_id)
                if live is None or str(live.fixture.id) != fixture_id:
                    continue

                old = previous.get(instance_id)
                if (
                    old is not None
                    and getattr(old.device, "instance_id", None) == instance_id
                ):
                    result[instance_id] = old
                    continue

                device = build_device_model(
                    live.fixture,
                    sysfs_path=live.sysfs_path,
                )
                result[instance_id] = SyncRuntimeDevice(
                    device=device,
                    topology=require_topology(device),
                )

    return plans, result




def group_for_runtime_key(plans, runtime_key):
    for plan in plans:
        for resolved in plan.active_members:
            if resolved.key == runtime_key:
                return plan.group
    raise KeyError(runtime_key)


def apply_group_member_brightness(frame, topology, *, group, instance_id, default_brightness):
    frame.validate()
    cell_brightness = {}
    for region in topology.regions:
        brightness = group_member_brightness(group, instance_id, region.id, default=default_brightness)
        for cell in region.cells:
            cell_brightness[(cell.row, cell.column)] = brightness
    pixels = []
    for r, row in enumerate(frame.pixels):
        rendered = []
        for c, colour in enumerate(row):
            brightness = cell_brightness.get((r, c), default_brightness)
            rendered.append(tuple(max(0, min(255, round(ch * brightness / 100.0))) for ch in colour))
        pixels.append(tuple(rendered))
    return type(frame)(rows=frame.rows, columns=frame.columns, pixels=tuple(pixels))


def build_runtime_map(member_ids, previous=None):
    previous = previous or {}
    result = {}
    for device in sync_runtime_devices({"members": list(member_ids)}):
        old = previous.get(device.fixture.id)
        result[device.fixture.id] = old or SyncRuntimeDevice(
            device=device,
            topology=require_topology(device),
        )
    return result


def _legacy_personal_region_settings(profile, instance_id, region_id):
    if not instance_id.startswith("razer-naga-v2-pro-wireless@"):
        return None
    mouse = profile.get("mouse", {})
    zones = mouse.get("zones", {}) if isinstance(mouse, dict) else {}
    value = zones.get(region_id) if isinstance(zones, dict) else None
    return dict(value) if isinstance(value, dict) and value.get("effect") else None


def personal_settings_for_region(profile, instance_id, region_id):
    settings = personal_region_settings(
        profile, instance_id=instance_id, region_id=region_id,
    )
    if settings is not None:
        return settings
    return _legacy_personal_region_settings(profile, instance_id, region_id)


def personal_render_settings(settings):
    return load_sync_settings({
        "sync": {
            "effect": settings.get("effect", "static"),
            "speed": settings.get("speed", 2),
            "colour1": settings.get("colour1", [0, 0, 255]),
            "colour2": settings.get("colour2", [0, 255, 255]),
            "direction": settings.get("direction", 1),
            "keyboard_brightness": 100,
            "mouse_brightness": 100,
            "member_brightness": {},
            "frame_interval": 0.06,
        }
    })


def grouped_region_keys(plans):
    result = set()
    for plan in plans:
        for resolved in plan.active_members:
            prefix = f"{resolved.device.instance_id}:"
            if resolved.key.startswith(prefix):
                result.add((resolved.device.instance_id, resolved.key[len(prefix):]))
    return result


def personal_effect_ids(profile, runtimes, plans):
    grouped = grouped_region_keys(plans)
    result = set()
    for instance_id, runtime in runtimes.items():
        for region in runtime.topology.controllable_regions():
            if (instance_id, region.id) in grouped:
                continue
            settings = personal_settings_for_region(profile, instance_id, region.id)
            if isinstance(settings, dict):
                effect = settings.get("effect")
                if isinstance(effect, str) and effect:
                    result.add(effect)
    return result


def reactive_canvas(runtimes):
    for runtime in runtimes.values():
        if runtime.device.device_class == "keyboard":
            return runtime.topology
    return next(iter(runtimes.values())).topology if runtimes else None


def run() -> None:
    if current_owner() != "sync":
        raise RuntimeError("Synchronization engine started without sync ownership.")

    global RELOAD_REQUESTED
    profile = load_profile()
    groups = sync_groups_from_profile(profile)
    plans, runtimes = build_group_runtime_map(groups, profile=profile)

    active_effects = {
        plan.group.effect
        for plan in plans
        if plan.active_members
    }
    active_effects.update(
        personal_effect_ids(profile, runtimes, plans)
    )
    reactive_inputs: dict[str, ReactiveRuntime] = {}
    for effect_id in sorted(active_effects):
        input_runtime = ReactiveRuntime()
        input_runtime.reconcile(effect_id)
        reactive_inputs[effect_id] = input_runtime

    started = time.monotonic()
    next_frame = started
    next_owner_check = started

    while RUNNING:
        now = time.monotonic()

        if RELOAD_REQUESTED:
            try:
                candidate_profile = load_profile()
                candidate_groups = sync_groups_from_profile(candidate_profile)
                candidate_plans, candidate_runtimes = build_group_runtime_map(
                    candidate_groups,
                    runtimes,
                    profile=candidate_profile,
                )
            except (OSError, ValueError, KeyError, TypeError, FixtureError, json.JSONDecodeError) as exc:
                print("Serpent synchronization group reload rejected; keeping previous groups: " + str(exc), file=sys.stderr, flush=True)
            else:
                profile, groups, plans, runtimes = (
                    candidate_profile,
                    candidate_groups,
                    candidate_plans,
                    candidate_runtimes,
                )
                started = now
                next_frame = now

                active_effects = {
                    plan.group.effect
                    for plan in plans
                    if plan.active_members
                }
                active_effects.update(
                    personal_effect_ids(profile, runtimes, plans)
                )

                for effect_id in active_effects:
                    reset_effect_instance(effect_id)

                for effect_id in list(reactive_inputs):
                    if effect_id not in active_effects:
                        reactive_inputs.pop(effect_id).close()

                for effect_id in sorted(active_effects):
                    input_runtime = reactive_inputs.get(effect_id)
                    if input_runtime is None:
                        input_runtime = ReactiveRuntime()
                        reactive_inputs[effect_id] = input_runtime
                    input_runtime.reconcile(
                        effect_id,
                        force=True,
                    )

                print("Serpent synchronization groups reloaded.", file=sys.stderr, flush=True)
            RELOAD_REQUESTED = False

        if now >= next_owner_check:
            if current_owner() != "sync":
                for input_runtime in reactive_inputs.values():
                    input_runtime.close()
                return
            next_owner_check = now + OWNER_CHECK_SECONDS

        elapsed = now - started

        canvas = reactive_canvas(runtimes)
        if canvas is not None:
            for effect_id, input_runtime in reactive_inputs.items():
                input_runtime.drain(
                    effect_id,
                    elapsed=elapsed,
                    rows=canvas.rows,
                    columns=canvas.columns,
                )

        any_ok = False
        intervals = []

        contributions_by_instance = {}
        rendered_by_group_device = {}

        for plan in plans:
            if not plan.active_members:
                continue

            group = plan.group
            settings = group_to_sync_settings(group)
            intervals.append(settings.frame_interval)

            for resolved in plan.active_members:
                instance_id = resolved.device.instance_id
                runtime = runtimes.get(instance_id)
                if runtime is None:
                    continue

                member_key = resolved.key
                prefix = f"{instance_id}:"
                if not member_key.startswith(prefix):
                    raise ValueError(
                        f"Resolved member key {member_key!r} does not match "
                        f"physical instance {instance_id!r}."
                    )
                region_id = member_key[len(prefix):]

                render_key = (group.id, instance_id)
                frame = rendered_by_group_device.get(render_key)
                if frame is None:
                    frame = render_effect_frame(
                        settings,
                        elapsed,
                        runtime.topology,
                        brightness=100.0,
                        controllable_only=(
                            runtime.device.device_class != "keyboard"
                        ),
                    )
                    frame = apply_group_member_brightness(
                        frame,
                        runtime.topology,
                        group=group,
                        instance_id=instance_id,
                        default_brightness=100.0,
                    )
                    rendered_by_group_device[render_key] = frame

                contributions_by_instance.setdefault(
                    instance_id,
                    {},
                )[region_id] = frame

        # Group contributions win. Fill only missing controllable regions
        # from the saved personal profile before the single physical write.
        for instance_id, runtime in runtimes.items():
            existing = contributions_by_instance.setdefault(instance_id, {})
            for region in runtime.topology.controllable_regions():
                if region.id in existing:
                    continue

                personal = personal_settings_for_region(
                    profile, instance_id, region.id,
                )
                if not isinstance(personal, dict):
                    continue

                try:
                    personal_settings = personal_render_settings(personal)
                    brightness = float(personal.get("brightness", 100))
                except (ValueError, TypeError, KeyError):
                    continue

                frame = render_effect_frame(
                    personal_settings,
                    elapsed,
                    runtime.topology,
                    brightness=brightness,
                    controllable_only=(
                        runtime.device.device_class != "keyboard"
                    ),
                )
                existing[region.id] = frame
                intervals.append(personal_settings.frame_interval)

        for instance_id, runtime in runtimes.items():
            runtime.endpoints = refresh_endpoints(
                runtime.endpoints,
                runtime.device,
            )
            if runtime.endpoints is None:
                continue

            frame = compose_region_frames(
                runtime.topology,
                contributions_by_instance.get(instance_id, {}),
            )
            payload = frame_payload(frame)
            ok = write_frame(runtime.endpoints, payload)
            if ok:
                any_ok = True
            else:
                runtime.endpoints = None

        if not any_ok:
            time.sleep(RETRY_SECONDS)
            next_frame = time.monotonic()
            continue

        next_frame += min(intervals) if intervals else 0.03
        if next_frame <= time.monotonic():
            next_frame = time.monotonic()
        else:
            sleep_until(next_frame)

    for input_runtime in reactive_inputs.values():
        input_runtime.close()



def main() -> int:
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGHUP, reload_handler)

    try:
        run()
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        FixtureError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"Serpent synchronization error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
