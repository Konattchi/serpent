#!/usr/bin/env python3

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from serpent_core.device import (
    DeviceModel,
    build_device_model,
)
from serpent_core.effects import (
    EffectParameters,
    EffectTarget,
    effect_ids,
    get_effect_definition,
    render_effect,
)
from serpent_core.fixtures import (
    FixtureError,
    find_fixture_by_id,
)


FIXTURE_ID = "razer-naga-v2-pro-wireless"

DEVICE_ROOT = Path("/sys/bus/hid/devices")

PROFILE_PATH = (
    Path.home()
    / ".config"
    / "serpent"
    / "profile.json"
)

FRAME_INTERVAL_SECONDS = 0.03
STATIC_REFRESH_SECONDS = 2.0
DEVICE_RETRY_SECONDS = 1.0

RUNNING = True


class DeviceUnavailableError(OSError):
    """The mouse lighting interface is temporarily unavailable."""


def stop_handler(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def load_device_model() -> DeviceModel:
    fixture = find_fixture_by_id(FIXTURE_ID)
    return build_device_model(fixture)


def device_pattern(device: DeviceModel) -> str:
    return f"*{device.usb_id.upper()}*"


def find_sysfs(device: DeviceModel) -> Path:
    for candidate in sorted(
        DEVICE_ROOT.glob(device_pattern(device))
    ):
        frame_endpoint = candidate / "matrix_custom_frame"
        custom_endpoint = candidate / "matrix_effect_custom"

        if frame_endpoint.exists() and custom_endpoint.exists():
            return candidate

    raise FileNotFoundError(
        f"{device.name} custom-matrix interface was not found."
    )


def clamp_byte(value: int | float) -> int:
    return max(0, min(255, round(float(value))))


def validate_colour(value: Any) -> tuple[int, int, int]:
    if value is None or len(value) != 3:
        raise ValueError(
            "Colour must contain exactly three RGB values."
        )

    colour = tuple(int(component) for component in value)

    if any(component < 0 or component > 255 for component in colour):
        raise ValueError(
            "RGB values must be between 0 and 255."
        )

    return colour


def validate_brightness(value: Any) -> float:
    brightness = float(value)

    if brightness < 0 or brightness > 100:
        raise ValueError(
            "Brightness must be between 0 and 100."
        )

    return brightness


def scale_colour(
    colour: tuple[int, int, int],
    brightness: float,
) -> tuple[int, int, int]:
    factor = (
        max(0.0, min(100.0, float(brightness)))
        / 100.0
    )

    return tuple(
        clamp_byte(component * factor)
        for component in colour
    )


def matrix_dimensions(
    device: DeviceModel,
) -> tuple[int, int]:
    matrix = device.capabilities.matrix

    if matrix is None:
        raise ValueError(
            f"{device.name} does not declare a lighting matrix."
        )

    if matrix.rows != 1:
        raise ValueError(
            "The current mouse renderer supports one matrix row; "
            f"the fixture declares {matrix.rows}."
        )

    return matrix.rows, matrix.columns


def validate_zone_mappings(
    device: DeviceModel,
) -> None:
    _rows, columns = matrix_dimensions(device)
    owners: dict[int, str] = {}

    for zone in device.zones:
        if zone.mapping_type != "matrix-columns":
            raise ValueError(
                f"Zone {zone.id!r} uses unsupported mapping type "
                f"{zone.mapping_type!r}."
            )

        for column in zone.columns:
            if column < 0 or column >= columns:
                raise ValueError(
                    f"Zone {zone.id!r} maps column {column}, "
                    f"outside the valid range 0–{columns - 1}."
                )

            previous = owners.get(column)

            if previous is not None:
                raise ValueError(
                    f"Matrix column {column} is assigned to both "
                    f"{previous!r} and {zone.id!r}."
                )

            owners[column] = zone.id


def write_matrix_frame(
    device: DeviceModel,
    column_colours: list[tuple[int, int, int]],
) -> bool:
    _rows, columns = matrix_dimensions(device)

    if len(column_colours) != columns:
        raise ValueError(
            f"Expected {columns} matrix-column colours, "
            f"received {len(column_colours)}."
        )

    payload_values: list[int] = [
        0,              # Row 0
        0,              # Start column
        columns - 1,    # Stop column
    ]

    for colour in column_colours:
        payload_values.extend(
            clamp_byte(component)
            for component in colour
        )

    payload = bytes(payload_values)

    try:
        sysfs_path = find_sysfs(device)

        frame_endpoint = (
            sysfs_path / "matrix_custom_frame"
        )
        custom_endpoint = (
            sysfs_path / "matrix_effect_custom"
        )

        frame_endpoint.write_bytes(payload)

        # Reassert custom mode with every frame. This restores the
        # correct mode after the wireless mouse wakes or reconnects.
        custom_endpoint.write_bytes(b"\x01")

        return True

    except (FileNotFoundError, PermissionError, OSError):
        # A wireless device can temporarily disappear while sleeping.
        # Keep the renderer alive and retry when it becomes available.
        return False


def default_zone_settings() -> dict[str, Any]:
    return {
        "effect": "static",
        "brightness": 20,
        "colour1": [0, 0, 255],
        "colour2": [0, 255, 255],
        "speed": 2,
    }


def normalise_zone_settings(
    settings: dict[str, Any],
    device: DeviceModel,
) -> dict[str, Any]:
    defaults = default_zone_settings()

    normalised = {
        key: settings.get(key, value)
        for key, value in defaults.items()
    }

    effect = str(normalised["effect"])

    try:
        device.effect_by_id(effect)
        native_effect = True
    except FixtureError:
        native_effect = False

    if effect not in effect_ids():
        raise ValueError(
            f"Software effect is not implemented: {effect}"
        )

    if not native_effect:
        from serpent_core.effects import get_effect_plugin_spec
        spec = get_effect_plugin_spec(effect)
        if "mouse" not in tuple(spec.render_targets or ()):
            raise ValueError(
                f"Software effect does not target mouse devices: {effect}"
            )

    normalised["effect"] = effect
    normalised["brightness"] = validate_brightness(
        normalised["brightness"]
    )
    normalised["colour1"] = validate_colour(
        normalised["colour1"]
    )
    normalised["colour2"] = validate_colour(
        normalised["colour2"]
    )

    speed = int(normalised.get("speed", 2))

    if speed < 1:
        raise ValueError(
            "Animation speed must be at least 1."
        )

    normalised["speed"] = speed

    direction = int(normalised.get("direction", 1))

    definition = get_effect_definition(effect)

    if (
        definition.directions
        and direction not in definition.directions
    ):
        raise ValueError(
            f"Direction {direction} is not supported "
            f"by effect {effect}."
        )

    normalised["direction"] = direction
    return normalised


def load_settings(
    device: DeviceModel,
) -> dict[str, dict[str, Any]]:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Mouse profile does not exist: {PROFILE_PATH}"
        )

    profile = json.loads(
        PROFILE_PATH.read_text(encoding="utf-8")
    )

    mouse = profile.get("mouse")

    if not isinstance(mouse, dict):
        raise ValueError(
            "Profile does not contain a valid 'mouse' section."
        )

    zones = mouse.get("zones")

    if isinstance(zones, dict):
        result: dict[str, dict[str, Any]] = {}

        for zone in device.zones:
            raw_settings = zones.get(zone.id, {})

            if not isinstance(raw_settings, dict):
                raw_settings = {}

            result[zone.id] = normalise_zone_settings(
                raw_settings,
                device,
            )

        return result

    # Backward compatibility for old flat mouse profiles.
    legacy = normalise_zone_settings(
        mouse,
        device,
    )

    return {
        zone.id: dict(legacy)
        for zone in device.zones
    }


def render_columns(
    device: DeviceModel,
    settings: dict[str, dict[str, Any]],
    elapsed: float,
) -> list[tuple[int, int, int]]:
    rows, columns = matrix_dimensions(device)

    # Unmapped, hidden, or non-controllable channels remain black.
    result = [
        (0, 0, 0)
        for _column in range(columns)
    ]

    for zone in device.controllable_zones():
        zone_settings = settings.get(zone.id)

        if zone_settings is None:
            continue

        target = EffectTarget(
            rows=rows,
            columns=columns,
            active_cells=tuple(
                (0, column)
                for column in zone.columns
            ),
        )

        frame = render_effect(
            str(zone_settings["effect"]),
            elapsed,
            EffectParameters(
                brightness=float(
                    zone_settings["brightness"]
                ),
                colour1=tuple(
                    zone_settings["colour1"]
                ),
                colour2=tuple(
                    zone_settings["colour2"]
                ),
                speed=int(zone_settings["speed"]),
            ),
            target,
        )

        for column in zone.columns:
            result[column] = frame.colour_at(
                0,
                column,
            )

    return result


def settings_are_static(
    device: DeviceModel,
    settings: dict[str, dict[str, Any]],
) -> bool:
    return all(
        not get_effect_definition(
            str(settings[zone.id]["effect"])
        ).animated
        for zone in device.controllable_zones()
    )


def sleep_interruptibly(duration: float) -> None:
    deadline = time.monotonic() + duration

    while RUNNING:
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            return

        time.sleep(min(remaining, 0.1))


def run_effects() -> None:
    device = load_device_model()
    validate_zone_mappings(device)

    controllable_zones = device.controllable_zones()

    if not controllable_zones:
        raise ValueError(
            f"{device.name} has no controllable lighting zones."
        )

    settings = load_settings(device)
    started = time.monotonic()

    static_only = settings_are_static(
        device,
        settings,
    )

    while RUNNING:
        elapsed = time.monotonic() - started

        column_colours = render_columns(
            device,
            settings,
            elapsed,
        )

        if write_matrix_frame(
            device,
            column_colours,
        ):
            delay = (
                STATIC_REFRESH_SECONDS
                if static_only
                else FRAME_INTERVAL_SECONDS
            )
        else:
            delay = DEVICE_RETRY_SECONDS

        sleep_interruptibly(delay)


def main() -> int:
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        run_effects()

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        FixtureError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"Naga effect engine error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
