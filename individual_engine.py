#!/usr/bin/env python3
from __future__ import annotations

import colorsys
import json
import math
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from serpent_core.effects import (
    EffectFrame,
    EffectParameters,
    EffectTarget,
    get_effect_plugin_spec,
    reload_effect_plugins,
    render_effect,
)
from serpent_core.device import build_device_model
from serpent_core.discovery import detect_all_fixture_instances
from serpent_core.fixtures import find_fixture_by_id
from serpent_core.ownership import current_owner
from serpent_core.reactive_runtime import ReactiveRuntime
from serpent_core.sync import frame_payload, require_topology
from serpent_core.sync_region_compositor import compose_region_frames
from sync_engine import (
    DeviceEndpoints,
    KEYBOARD_FIXTURE_ID,
    MOUSE_FIXTURE_ID,
    build_device,
    refresh_endpoints,
    sleep_until,
    write_frame,
)

PROFILE_PATH = Path.home() / ".config" / "serpent" / "profile.json"
FRAME_INTERVAL = 0.06
OWNER_CHECK_SECONDS = 1.0
PROFILE_CHECK_SECONDS = 0.35
RUNNING = True


def stop_handler(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def load_profile() -> dict[str, object]:
    if not PROFILE_PATH.exists():
        return {}
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Serpent profile root must be an object.")
    return data


def fixture_effect_ids(fixture_id: str) -> set[str]:
    fixture = find_fixture_by_id(fixture_id)
    data = getattr(fixture, "data", None)
    if not isinstance(data, dict):
        raise TypeError(
            f"Fixture {fixture_id!r} does not expose dictionary fixture data."
        )
    raw = data.get("effects", {})
    return {str(effect_id) for effect_id in raw} if isinstance(raw, dict) else set()


def dynamic_effect(effect_id: str, device_class: str, classic: set[str]) -> bool:
    if not effect_id or effect_id in classic:
        return False
    try:
        spec = get_effect_plugin_spec(effect_id)
    except (KeyError, TypeError, ValueError):
        return False
    return device_class in spec.render_targets


def default_parameter(effect_id: str, parameter_id: str, fallback):
    try:
        spec = get_effect_plugin_spec(effect_id)
    except (KeyError, TypeError, ValueError):
        return fallback
    for parameter in spec.parameters:
        if parameter.id == parameter_id:
            return parameter.default
    return fallback


def colour_value(raw: dict[str, object], effect_id: str, key: str, fallback):
    value = raw.get(key, default_parameter(effect_id, key, fallback))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(max(0, min(255, int(component))) for component in value)
    return fallback


def parameters_for(effect_id: str, raw: dict[str, object]) -> EffectParameters:
    return EffectParameters(
        brightness=float(raw.get("brightness", 100)),
        colour1=colour_value(raw, effect_id, "colour1", (255, 255, 255)),
        colour2=colour_value(raw, effect_id, "colour2", (0, 0, 0)),
        speed=int(raw.get("speed", default_parameter(effect_id, "speed", 2))),
        direction=int(raw.get("direction", default_parameter(effect_id, "direction", 1))),
    )


def topology_target(topology, *, region_id: str | None = None) -> EffectTarget:
    if region_id is None:
        cells = tuple((cell.row, cell.column) for cell in topology.all_cells())
    else:
        region = next((candidate for candidate in topology.regions if candidate.id == region_id), None)
        cells = () if region is None else tuple((cell.row, cell.column) for cell in region.cells)
    return EffectTarget(
        rows=topology.rows,
        columns=topology.columns,
        active_cells=cells,
        device_class=topology.device_class,
    )


def _classic_active_cells(topology, region_id=None):
    if region_id is None:
        return tuple((cell.row, cell.column) for cell in topology.all_cells())

    region = next(
        (
            candidate
            for candidate in topology.regions
            if candidate.id == region_id
        ),
        None,
    )
    if region is None:
        return ()
    return tuple((cell.row, cell.column) for cell in region.cells)


def _classic_frame(topology, colours_by_cell):
    rows = [
        [(0, 0, 0) for _ in range(topology.columns)]
        for _ in range(topology.rows)
    ]
    for (row, column), colour in colours_by_cell.items():
        rows[row][column] = tuple(
            max(0, min(255, int(component)))
            for component in colour
        )
    frame = EffectFrame(
        rows=topology.rows,
        columns=topology.columns,
        pixels=tuple(tuple(row) for row in rows),
    )
    frame.validate()
    return frame


def _brightness_scale(colour, brightness):
    factor = max(0.0, min(1.0, float(brightness) / 100.0))
    return tuple(int(round(component * factor)) for component in colour)


def render_classic_software_effect(
    raw,
    elapsed,
    topology,
    *,
    region_id=None,
):
    effect_id = str(raw.get("effect", "static")).lower()
    params = parameters_for(effect_id, raw)
    cells = _classic_active_cells(topology, region_id=region_id)

    if effect_id in {"off", "none"}:
        return _classic_frame(
            topology,
            {cell: (0, 0, 0) for cell in cells},
        )

    colour1 = _brightness_scale(params.colour1, params.brightness)
    colour2 = _brightness_scale(params.colour2, params.brightness)

    if effect_id == "static":
        return _classic_frame(
            topology,
            {cell: colour1 for cell in cells},
        )

    if effect_id == "spectrum":
        speed = max(1, int(params.speed))
        count = max(1, len(cells))
        colours = {}
        for index, cell in enumerate(cells):
            hue = (
                elapsed * (0.035 * speed)
                + (index / count)
            ) % 1.0
            red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            colours[cell] = _brightness_scale(
                (
                    int(round(red * 255)),
                    int(round(green * 255)),
                    int(round(blue * 255)),
                ),
                params.brightness,
            )
        return _classic_frame(topology, colours)

    if effect_id in {"breath", "breathing", "breath-single"}:
        speed = max(1, int(params.speed))
        phase = (math.sin(elapsed * (0.75 * speed)) + 1.0) * 0.5
        pulsed = tuple(
            int(round(component * phase))
            for component in colour1
        )
        return _classic_frame(
            topology,
            {cell: pulsed for cell in cells},
        )

    if effect_id == "breath-dual":
        speed = max(1, int(params.speed))
        angle = elapsed * (0.75 * speed)
        phase = (math.sin(angle) + 1.0) * 0.5
        pulse_index = int(
            math.floor(
                (angle + (math.pi / 2.0))
                / (2.0 * math.pi)
            )
        )
        source = (
            colour1
            if (pulse_index % 2) == 0
            else colour2
        )

        pulsed = tuple(
            int(round(component * phase))
            for component in source
        )
        return _classic_frame(
            topology,
            {cell: pulsed for cell in cells},
        )

    if effect_id == "breath-random":
        speed = max(1, int(params.speed))
        breath_phase = (
            math.sin(elapsed * (0.75 * speed)) + 1.0
        ) * 0.5
        hue = (elapsed * 0.035 * speed) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(
            hue,
            1.0,
            breath_phase,
        )
        random_breath = _brightness_scale(
            (
                int(round(red * 255)),
                int(round(green * 255)),
                int(round(blue * 255)),
            ),
            params.brightness,
        )
        return _classic_frame(
            topology,
            {cell: random_breath for cell in cells},
        )

    if effect_id == "reactive":
        speed = max(1, int(params.speed))
        phase = (elapsed * speed) % 1.0
        intensity = max(0.08, 1.0 - phase)
        reactive = tuple(
            int(round(component * intensity))
            for component in colour1
        )
        return _classic_frame(
            topology,
            {cell: reactive for cell in cells},
        )

    raise ValueError(
        f"Classic software effect is not implemented: {effect_id}"
    )

def render_profile_effect(
    raw,
    elapsed,
    topology,
    *,
    region_id=None,
    classic_effects=None,
    software_classic=False,
):
    effect_id = str(raw.get("effect", "static"))
    classic_effects = set(classic_effects or ())

    if software_classic and effect_id in classic_effects:
        return render_classic_software_effect(
            raw,
            elapsed,
            topology,
            region_id=region_id,
        )

    return render_effect(
        effect_id,
        elapsed,
        parameters_for(effect_id, raw),
        topology_target(topology, region_id=region_id),
    )




def merge_mouse_frames(topology, frames_by_region):
    rows = [[(0, 0, 0) for _ in range(topology.columns)] for _ in range(topology.rows)]
    for region_id, frame in frames_by_region.items():
        region = next((candidate for candidate in topology.regions if candidate.id == region_id), None)
        if region is None:
            continue
        for cell in region.cells:
            rows[cell.row][cell.column] = frame.pixels[cell.row][cell.column]
    result = EffectFrame(
        rows=topology.rows,
        columns=topology.columns,
        pixels=tuple(tuple(row) for row in rows),
    )
    result.validate()
    return result


@dataclass
class GenericRenderDevice:
    instance_id: str
    fixture_id: str
    device: object
    topology: object
    classic_effects: set[str]
    endpoints: DeviceEndpoints | None = None


def generic_profile_entries(profile) -> dict[str, dict[str, object]]:
    raw = profile.get("fixture_devices", {})
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict[str, object]] = {}
    for instance_id, saved in raw.items():
        if not isinstance(instance_id, str) or not isinstance(saved, dict):
            continue
        fixture_id = saved.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id:
            continue

        if fixture_id in {KEYBOARD_FIXTURE_ID, MOUSE_FIXTURE_ID}:
            continue

        result[instance_id] = saved
    return result


def reconcile_generic_devices(profile, previous=None):
    previous = previous or {}
    configured = generic_profile_entries(profile)
    detected = {
        str(item.instance_id): item
        for item in detect_all_fixture_instances()
    }

    result: dict[str, GenericRenderDevice] = {}
    for instance_id, saved in configured.items():
        live = detected.get(instance_id)
        if live is None:
            continue

        fixture_id = str(saved.get("fixture_id", ""))
        if str(live.fixture.id) != fixture_id:
            continue

        old = previous.get(instance_id)
        if (
            old is not None
            and str(old.fixture_id) == fixture_id
            and getattr(old.device, "sysfs_path", None) == live.sysfs_path
        ):
            result[instance_id] = old
            continue

        device = build_device_model(
            live.fixture,
            sysfs_path=live.sysfs_path,
        )
        result[instance_id] = GenericRenderDevice(
            instance_id=instance_id,
            fixture_id=fixture_id,
            device=device,
            topology=require_topology(device),
            classic_effects=fixture_effect_ids(fixture_id),
        )

    return result


def generic_selected_settings(saved, topology):
    whole = saved.get("settings")
    if isinstance(whole, dict) and whole.get("effect"):
        return {"__device__": whole}

    zones = saved.get("zones", {})
    if not isinstance(zones, dict):
        return {}

    valid_regions = {region.id for region in topology.controllable_regions()}
    result = {}
    for region_id, settings in zones.items():
        if (
            isinstance(region_id, str)
            and region_id in valid_regions
            and isinstance(settings, dict)
            and settings.get("effect")
        ):
            result[region_id] = settings
    return result


def render_profile_effect_isolated(
    raw,
    elapsed,
    topology,
    *,
    region_id,
    classic_effects=None,
    software_classic=False,
):
    try:
        return render_profile_effect(
            raw,
            elapsed,
            topology,
            region_id=region_id,
            classic_effects=classic_effects,
            software_classic=software_classic,
        )
    except Exception:
        return _classic_frame(topology, {})

def generic_requires_software(runtime: GenericRenderDevice, saved) -> bool:
    selected = generic_selected_settings(saved, runtime.topology)
    if not selected:
        return False

    # software-rgb-sysfs is a frame transport, not a persistent hardware-effect
    # backend. Every selected personal effect for such a fixture must therefore
    # be owned by serpent-individual, including fixture-listed effects such as
    # static/spectrum/breath/reactive.
    if runtime.device.backend_type == "software-rgb-sysfs":
        return True

    for settings in selected.values():
        effect_id = str(settings.get("effect", ""))
        if dynamic_effect(
            effect_id,
            runtime.device.device_class,
            runtime.classic_effects,
        ):
            return True
    return False


def generic_active_effects(runtime: GenericRenderDevice, saved) -> set[str]:
    if not generic_requires_software(runtime, saved):
        return set()

    result = set()
    for settings in generic_selected_settings(
        saved,
        runtime.topology,
    ).values():
        if not isinstance(settings, dict):
            continue
        effect_id = str(settings.get("effect", ""))
        if dynamic_effect(
            effect_id,
            runtime.device.device_class,
            runtime.classic_effects,
        ):
            result.add(effect_id)
    return result




def render_generic_device(runtime: GenericRenderDevice, saved, elapsed):
    selected = generic_selected_settings(saved, runtime.topology)
    whole = selected.get("__device__")
    if isinstance(whole, dict):
        return render_profile_effect(
            whole,
            elapsed,
            runtime.topology,
            classic_effects=runtime.classic_effects,
            software_classic=(
                runtime.device.backend_type == "software-rgb-sysfs"
            ),
        )

    frames = {}
    for region_id, settings in selected.items():
        if region_id == "__device__" or not isinstance(settings, dict):
            continue
        frames[region_id] = render_profile_effect(
            settings,
            elapsed,
            runtime.topology,
            region_id=region_id,
            classic_effects=runtime.classic_effects,
            software_classic=(
                runtime.device.backend_type == "software-rgb-sysfs"
            ),
        )

    if not frames:
        return None

    return compose_region_frames(runtime.topology, frames)


def reconcile_generic_reactive_runtimes(
    runtimes,
    generic_devices,
    profile,
):
    wanted = {}
    configured = generic_profile_entries(profile)

    for instance_id, runtime in generic_devices.items():
        saved = configured.get(instance_id, {})
        for effect_id in generic_active_effects(runtime, saved):
            wanted[(instance_id, effect_id)] = runtime

    for key in tuple(runtimes):
        if key not in wanted:
            runtimes.pop(key).close()

    for key, runtime in wanted.items():
        if key not in runtimes:
            reactive = ReactiveRuntime()
            reactive.reconcile(key[1], force=True)
            runtimes[key] = reactive

    return wanted



def render_linked_mouse_effect(
    raw,
    elapsed,
    topology,
    *,
    classic_effects=None,
    software_classic=False,
):
    effect_id = str(raw.get("effect", "static"))

    if software_classic and effect_id == "spectrum":
        params = parameters_for(effect_id, raw)
        speed = max(1, int(params.speed))
        hue = (elapsed * (0.035 * speed)) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        colour = _brightness_scale(
            (
                int(round(red * 255)),
                int(round(green * 255)),
                int(round(blue * 255)),
            ),
            params.brightness,
        )
        return _classic_frame(
            topology,
            {
                (cell.row, cell.column): colour
                for cell in topology.all_cells()
            },
        )

    return render_profile_effect(
        raw,
        elapsed,
        topology,
        classic_effects=classic_effects,
        software_classic=software_classic,
    )

def profile_state(
    profile,
    keyboard_classic,
    mouse_classic,
    *,
    keyboard_software=False,
    mouse_software=False,
):
    keyboard_raw = profile.get("keyboard", {})
    if not isinstance(keyboard_raw, dict):
        keyboard_raw = {}
    keyboard_effect = str(keyboard_raw.get("effect", "static"))
    keyboard_dynamic = (
        keyboard_software
        or dynamic_effect(
            keyboard_effect,
            "keyboard",
            keyboard_classic,
        )
    )

    mouse = profile.get("mouse", {})
    if not isinstance(mouse, dict):
        mouse = {}
    linked = bool(mouse.get("linked", True))
    zones = mouse.get("zones", {})
    if not isinstance(zones, dict):
        zones = {}
    logo = zones.get("logo", {})
    side = zones.get("side-buttons", {})
    if not isinstance(logo, dict):
        logo = {}
    if not isinstance(side, dict):
        side = {}

    logo_effect = str(logo.get("effect", "static"))
    side_effect = str(side.get("effect", logo_effect if linked else "static"))
    mouse_dynamic = (
        mouse_software
        or dynamic_effect(
            logo_effect,
            "mouse",
            mouse_classic,
        )
        or (
            not linked
            and dynamic_effect(
                side_effect,
                "mouse",
                mouse_classic,
            )
        )
    )
    return keyboard_raw, keyboard_dynamic, linked, logo, side, mouse_dynamic


def run() -> None:
    reload_effect_plugins()

    keyboard = build_device(KEYBOARD_FIXTURE_ID)
    mouse = build_device(MOUSE_FIXTURE_ID)
    keyboard_topology = require_topology(keyboard)
    mouse_topology = require_topology(mouse)

    keyboard_classic = fixture_effect_ids(KEYBOARD_FIXTURE_ID)
    mouse_classic = fixture_effect_ids(MOUSE_FIXTURE_ID)
    keyboard_software = keyboard.backend_type == "software-rgb-sysfs"
    mouse_software = mouse.backend_type == "software-rgb-sysfs"

    keyboard_endpoints: DeviceEndpoints | None = None
    mouse_endpoints: DeviceEndpoints | None = None
    runtimes: dict[str, ReactiveRuntime] = {}
    generic_reactive: dict[tuple[str, str], ReactiveRuntime] = {}

    profile = load_profile()
    generic_devices = reconcile_generic_devices(profile)
    profile_stamp = PROFILE_PATH.stat().st_mtime_ns if PROFILE_PATH.exists() else 0
    started = time.monotonic()
    next_frame = started
    next_owner_check = started
    next_profile_check = started

    try:
        while RUNNING:
            now = time.monotonic()

            if now >= next_owner_check:
                if current_owner() != "normal":
                    return
                next_owner_check = now + OWNER_CHECK_SECONDS

            if now >= next_profile_check:
                stamp = PROFILE_PATH.stat().st_mtime_ns if PROFILE_PATH.exists() else 0
                if stamp != profile_stamp:
                    profile = load_profile()
                    profile_stamp = stamp
                    started = now

                generic_devices = reconcile_generic_devices(
                    profile,
                    generic_devices,
                )
                next_profile_check = now + PROFILE_CHECK_SECONDS

            keyboard_raw, keyboard_dynamic, linked, logo_raw, side_raw, mouse_dynamic = profile_state(
                profile,
                keyboard_classic,
                mouse_classic,
                keyboard_software=keyboard_software,
                mouse_software=mouse_software,
            )

            pass
            active_effects = set()
            keyboard_effect_id = str(
                keyboard_raw.get("effect", "static")
            )
            logo_effect_id = str(
                logo_raw.get("effect", "static")
            )
            side_effect_id = str(
                side_raw.get("effect", "static")
            )

            if dynamic_effect(
                keyboard_effect_id,
                "keyboard",
                keyboard_classic,
            ):
                active_effects.add(keyboard_effect_id)

            if dynamic_effect(
                logo_effect_id,
                "mouse",
                mouse_classic,
            ):
                active_effects.add(logo_effect_id)

            if (
                not linked
                and dynamic_effect(
                    side_effect_id,
                    "mouse",
                    mouse_classic,
                )
            ):
                active_effects.add(side_effect_id)

            for effect_id in tuple(runtimes):
                if effect_id not in active_effects:
                    runtimes.pop(effect_id).close()
            for effect_id in active_effects:
                if effect_id not in runtimes:
                    runtime = ReactiveRuntime()
                    runtime.reconcile(effect_id, force=True)
                    runtimes[effect_id] = runtime

            generic_targets = reconcile_generic_reactive_runtimes(
                generic_reactive,
                generic_devices,
                profile,
            )

            elapsed = now - started

            for effect_id, runtime in runtimes.items():
                runtime.drain(
                    effect_id,
                    elapsed=elapsed,
                    rows=keyboard_topology.rows,
                    columns=keyboard_topology.columns,
                )

            for key, runtime in generic_reactive.items():
                target = generic_targets.get(key)
                if target is None:
                    continue
                runtime.drain(
                    key[1],
                    elapsed=elapsed,
                    rows=target.topology.rows,
                    columns=target.topology.columns,
                )

            if keyboard_dynamic:
                keyboard_endpoints = refresh_endpoints(keyboard_endpoints, keyboard)
                if keyboard_endpoints is not None:
                    frame = render_profile_effect(
                        keyboard_raw,
                        elapsed,
                        keyboard_topology,
                        classic_effects=keyboard_classic,
                        software_classic=keyboard_software,
                    )
                    if not write_frame(keyboard_endpoints, frame_payload(frame)):
                        keyboard_endpoints = None

            if mouse_dynamic:
                mouse_endpoints = refresh_endpoints(mouse_endpoints, mouse)
                if mouse_endpoints is not None:
                    if linked:
                        frame = render_linked_mouse_effect(
                            logo_raw,
                            elapsed,
                            mouse_topology,
                            classic_effects=mouse_classic,
                            software_classic=mouse_software,
                        )
                    else:
                        frame = merge_mouse_frames(
                            mouse_topology,
                            {
                                "logo": render_profile_effect_isolated(
                                    logo_raw,
                                    elapsed,
                                    mouse_topology,
                                    region_id="logo",
                                    classic_effects=mouse_classic,
                                    software_classic=mouse_software,
                                ),
                                "side-buttons": render_profile_effect_isolated(
                                    side_raw,
                                    elapsed,
                                    mouse_topology,
                                    region_id="side-buttons",
                                    classic_effects=mouse_classic,
                                    software_classic=mouse_software,
                                ),
                            },
                        )
                    if not write_frame(mouse_endpoints, frame_payload(frame)):
                        mouse_endpoints = None

            configured = generic_profile_entries(profile)
            for instance_id, runtime in generic_devices.items():
                saved = configured.get(instance_id, {})
                if not generic_requires_software(runtime, saved):
                    runtime.endpoints = None
                    continue

                runtime.endpoints = refresh_endpoints(
                    runtime.endpoints,
                    runtime.device,
                )
                if runtime.endpoints is None:
                    continue

                frame = render_generic_device(runtime, saved, elapsed)
                if frame is None:
                    continue

                if not write_frame(runtime.endpoints, frame_payload(frame)):
                    runtime.endpoints = None

            next_frame += FRAME_INTERVAL
            if next_frame <= time.monotonic():
                next_frame = time.monotonic()
            else:
                sleep_until(next_frame)
    finally:
        for runtime in runtimes.values():
            runtime.close()
        for runtime in generic_reactive.values():
            runtime.close()
        try:
            if current_owner() == "normal":
                pass
        except Exception:
            pass




def main() -> int:
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        run()
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Serpent individual renderer error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
