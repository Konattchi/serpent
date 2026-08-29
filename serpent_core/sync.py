#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from serpent_core.device import DeviceModel
from serpent_core.effects import (
    EffectFrame,
    EffectParameters,
    EffectTarget,
    effect_ids,
    get_effect_definition,
    render_effect as render_unified_effect,
)
from serpent_core.fixtures import FixtureError
from serpent_core.topology import (
    LightingTopology,
    MatrixCell,
    build_lighting_topology,
)


Colour = tuple[int, int, int]


@dataclass(frozen=True)
class SyncSettings:
    effect: str
    speed: int
    colour1: Colour
    colour2: Colour
    keyboard_brightness: float
    mouse_brightness: float
    member_brightness: dict[str, float]
    frame_interval: float
    direction: int


def supported_effects() -> set[str]:
    # User effect plugins may be transactionally refreshed in-process.
    # Resolve the registry at validation time instead of freezing an
    # import-time snapshot.
    return set(effect_ids())


def clamp_byte(value: int | float) -> int:
    return max(0, min(255, round(float(value))))


def validate_colour(value: object) -> Colour:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(
            "A synchronization colour requires three RGB values."
        )

    result = tuple(int(component) for component in value)

    if any(component < 0 or component > 255 for component in result):
        raise ValueError(
            "Synchronization RGB values must be between 0 and 255."
        )

    return result[0], result[1], result[2]


def validate_brightness(value: object) -> float:
    brightness = float(value)

    if brightness < 0 or brightness > 100:
        raise ValueError(
            "Synchronization brightness must be between 0 and 100."
        )

    return brightness


def validate_member_brightness(
    value: object,
) -> dict[str, float]:
    if value is None:
        return {}

    if not isinstance(value, dict):
        raise ValueError(
            "Synchronization member_brightness must be an object."
        )

    result: dict[str, float] = {}

    for member, brightness in value.items():
        if not isinstance(member, str) or ":" not in member:
            raise ValueError(
                f"Invalid synchronization member brightness key: {member!r}"
            )

        result[member] = validate_brightness(brightness)

    return result


def load_sync_settings(profile: dict[str, object]) -> SyncSettings:
    raw = profile.get("sync", {})

    if not isinstance(raw, dict):
        raise ValueError("Profile sync section must be an object.")

    effect = str(raw.get("effect", "spectrum"))

    if effect not in supported_effects():
        raise ValueError(
            f"Synchronization effect is not implemented: {effect}"
        )

    speed = int(raw.get("speed", 2))

    if speed < 1:
        raise ValueError("Synchronization speed must be at least 1.")

    direction = int(raw.get("direction", 1))

    definition = get_effect_definition(effect)

    if (
        definition.directions
        and direction not in definition.directions
    ):
        raise ValueError(
            f"Synchronization direction {direction} "
            f"is not supported by {effect}."
        )

    frame_interval = float(raw.get("frame_interval", 0.06))

    if frame_interval < 0.02 or frame_interval > 1.0:
        raise ValueError(
            "Synchronization frame_interval must be between "
            "0.02 and 1.0 seconds."
        )

    return SyncSettings(
        effect=effect,
        speed=speed,
        colour1=validate_colour(
            raw.get("colour1", [255, 0, 255])
        ),
        colour2=validate_colour(
            raw.get("colour2", [0, 255, 255])
        ),
        keyboard_brightness=validate_brightness(
            raw.get("keyboard_brightness", 35)
        ),
        mouse_brightness=validate_brightness(
            raw.get("mouse_brightness", 35)
        ),
        member_brightness=validate_member_brightness(
            raw.get("member_brightness", {})
        ),
        frame_interval=frame_interval,
        direction=direction,
    )


def scale_colour(
    colour: Colour,
    brightness: float,
) -> Colour:
    factor = brightness / 100.0

    return tuple(
        clamp_byte(component * factor)
        for component in colour
    )  # type: ignore[return-value]


def topology_target(
    topology: LightingTopology,
    *,
    controllable_only: bool,
) -> EffectTarget:
    if controllable_only:
        cells = tuple(
            (cell.row, cell.column)
            for region in topology.controllable_regions()
            for cell in region.cells
        )
    else:
        cells = tuple(
            (cell.row, cell.column)
            for cell in topology.all_cells()
        )

    return EffectTarget(
        rows=topology.rows,
        columns=topology.columns,
        active_cells=cells,
        device_class=topology.device_class,
    )


def render_effect_frame(
    settings: SyncSettings,
    elapsed: float,
    topology: LightingTopology,
    *,
    brightness: float,
    controllable_only: bool,
) -> EffectFrame:
    return render_unified_effect(
        settings.effect,
        elapsed,
        EffectParameters(
            brightness=brightness,
            colour1=settings.colour1,
            colour2=settings.colour2,
            speed=settings.speed,
            direction=settings.direction,
        ),
        topology_target(
            topology,
            controllable_only=controllable_only,
        ),
    )


def member_brightness_value(
    settings: SyncSettings,
    member: str,
    *,
    default: float,
) -> float:
    return settings.member_brightness.get(
        member,
        default,
    )


def apply_member_brightness(
    frame: EffectFrame,
    topology: LightingTopology,
    *,
    fixture_id: str,
    settings: SyncSettings,
    default_brightness: float,
) -> EffectFrame:
    """Scale an already-rendered frame per synchronized topology member.

    Spatial/temporal effects are rendered once at full brightness first.
    Brightness is applied afterwards so differing zone intensity never
    changes an effect's spatial phase or degradation behavior.
    """

    frame.validate()

    cell_brightness: dict[tuple[int, int], float] = {}

    for region in topology.regions:
        member = f"{fixture_id}:{region.id}"
        brightness = member_brightness_value(
            settings,
            member,
            default=default_brightness,
        )

        for cell in region.cells:
            cell_brightness[(cell.row, cell.column)] = brightness

    pixels: list[tuple[Colour, ...]] = []

    for row_index, row in enumerate(frame.pixels):
        rendered_row: list[Colour] = []

        for column_index, colour in enumerate(row):
            brightness = cell_brightness.get(
                (row_index, column_index),
                default_brightness,
            )
            rendered_row.append(
                scale_colour(
                    colour,
                    brightness,
                )
            )

        pixels.append(tuple(rendered_row))

    result = EffectFrame(
        rows=frame.rows,
        columns=frame.columns,
        pixels=tuple(pixels),
    )
    result.validate()
    return result


def require_topology(
    device: DeviceModel,
) -> LightingTopology:
    topology = build_lighting_topology(device)

    if topology is None:
        raise FixtureError(
            f"{device.name} does not expose a lighting topology."
        )

    topology.validate()
    return topology


def frame_payload(
    frame: EffectFrame,
) -> bytes:
    frame.validate()
    packets: list[bytes] = []

    for row_index, row in enumerate(frame.pixels):
        packet = bytearray(
            (row_index, 0, frame.columns - 1)
        )

        for colour in row:
            packet.extend(colour)

        packets.append(bytes(packet))

    return b"".join(packets)
