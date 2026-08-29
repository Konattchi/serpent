from __future__ import annotations

"""Public effect-author utility foundation for Serpent 0.9 development.

This module deliberately contains small, presentation-neutral helpers only.
It does not own effect discovery, reactive input, fixture loading, hardware
access, service state, lighting ownership, or render-thread lifecycle.

M9.2 rule: extract proven repetition; do not invent large abstractions.
"""

import colorsys
import math
import random

from serpent_core.effect_random import event_rng, event_seed
from serpent_core.effects.base import Cell, Colour, EffectEvent, EffectFrame, EffectTarget


def clamp_channel(value: float | int) -> int:
    """Clamp and round one RGB channel into the byte range 0..255."""
    return max(0, min(255, round(float(value))))


def clamp_colour(colour: tuple[float | int, float | int, float | int]) -> Colour:
    """Clamp an RGB triple into Serpent's Colour byte representation."""
    return (
        clamp_channel(colour[0]),
        clamp_channel(colour[1]),
        clamp_channel(colour[2]),
    )


def scale_colour(colour: Colour, factor: float) -> Colour:
    """Scale RGB channels by a non-negative multiplier."""
    amount = max(0.0, float(factor))
    return clamp_colour(
        (
            colour[0] * amount,
            colour[1] * amount,
            colour[2] * amount,
        )
    )


def mix_colour(first: Colour, second: Colour, amount: float) -> Colour:
    """Linearly interpolate from first to second using amount in 0..1."""
    t = max(0.0, min(1.0, float(amount)))
    return clamp_colour(
        (
            first[0] * (1.0 - t) + second[0] * t,
            first[1] * (1.0 - t) + second[1] * t,
            first[2] * (1.0 - t) + second[2] * t,
        )
    )


def hsv_colour(
    hue: float,
    saturation: float = 1.0,
    value: float = 1.0,
) -> Colour:
    """Convert normalized HSV values to a clamped RGB Colour."""
    red, green, blue = colorsys.hsv_to_rgb(
        float(hue) % 1.0,
        max(0.0, min(1.0, float(saturation))),
        max(0.0, min(1.0, float(value))),
    )
    return clamp_colour(
        (
            red * 255.0,
            green * 255.0,
            blue * 255.0,
        )
    )


def vivid_random_colour(
    rng: random.Random,
    *,
    minimum_saturation: float = 0.85,
    minimum_value: float = 0.90,
) -> Colour:
    """Generate a vivid random hue from a caller-owned deterministic RNG."""
    saturation_floor = max(0.0, min(1.0, float(minimum_saturation)))
    value_floor = max(0.0, min(1.0, float(minimum_value)))
    return hsv_colour(
        rng.random(),
        rng.uniform(saturation_floor, 1.0),
        rng.uniform(value_floor, 1.0),
    )


def cell_distance(first: Cell, second: Cell) -> float:
    """Return Euclidean distance between two logical effect cells."""
    return math.hypot(
        second[0] - first[0],
        second[1] - first[1],
    )


def active_cell_set(target: EffectTarget) -> frozenset[Cell]:
    """Return immutable active-cell membership for repeated render lookups."""
    target.validate()
    return frozenset(target.active_cells)


def nearest_active_cell(
    target: EffectTarget,
    row: float,
    column: float,
    *,
    maximum_distance: float | None = None,
) -> Cell | None:
    """Return the nearest controllable cell to a logical floating position."""
    target.validate()

    if not target.active_cells:
        return None

    nearest = min(
        target.active_cells,
        key=lambda cell: (
            (cell[0] - row) ** 2 + (cell[1] - column) ** 2,
            cell[0],
            cell[1],
        ),
    )

    if maximum_distance is not None:
        limit = max(0.0, float(maximum_distance))
        distance = math.hypot(
            nearest[0] - row,
            nearest[1] - column,
        )
        if distance > limit:
            return None

    return nearest


def event_vivid_colour(
    event: EffectEvent,
    *,
    serial: int = 0,
    namespace: str = "",
    minimum_saturation: float = 0.85,
    minimum_value: float = 0.90,
) -> Colour:
    """Generate one reproducible vivid colour directly from an EffectEvent."""
    rng = event_rng(
        event,
        serial=serial,
        namespace=namespace,
    )
    return vivid_random_colour(
        rng,
        minimum_saturation=minimum_saturation,
        minimum_value=minimum_value,
    )


def event_matches(
    event: EffectEvent,
    *,
    kind: str,
    source_prefix: str,
) -> bool:
    """Return whether an effect event matches a kind and source prefix."""
    return (
        event.kind == kind
        and event.source.startswith(source_prefix)
    )


def event_cell(
    event: EffectEvent,
) -> Cell | None:
    """Return an event's integer logical cell, or None if position is absent."""
    if event.row is None or event.column is None:
        return None

    return Cell((
        int(event.row),
        int(event.column),
    ))


def event_timestamp(
    event: EffectEvent,
) -> float:
    """Return an effect event timestamp as float."""
    return float(event.timestamp)

def animation_age(
    elapsed: float,
    started_at: float,
) -> float:
    """Return elapsed animation time relative to a state's start timestamp."""
    return float(elapsed) - float(started_at)


def animation_phase(
    elapsed: float,
    started_at: float,
    duration: float,
    *,
    clamp: bool = False,
) -> float:
    """Return normalized animation age.

    The denominator follows Serpent's established effect convention and never
    falls below 0.001 seconds. With clamp=False, callers can observe values
    below 0 or above 1. With clamp=True, the result is restricted to 0..1.
    """
    phase = animation_age(
        elapsed,
        started_at,
    ) / max(float(duration), 0.001)

    if clamp:
        return max(0.0, min(1.0, phase))

    return phase


def animation_alive(
    elapsed: float,
    started_at: float,
    duration: float,
) -> bool:
    """Return whether an animation state is inside its inclusive lifetime."""
    age = animation_age(
        elapsed,
        started_at,
    )

    return (
        0.0
        <= age
        <= float(duration)
    )


def prune_expired(
    states,
    elapsed: float,
    duration_of,
):
    """Return states whose inclusive animation lifetime still contains elapsed.

    ``states`` may contain any objects exposing a numeric ``started_at``
    attribute. ``duration_of(state)`` remains effect-owned so lifetimes may be
    global, per-event, target-dependent, or otherwise dynamic.

    Input order is preserved and a new list is returned.
    """
    return [
        state
        for state in states
        if animation_alive(
            elapsed,
            state.started_at,
            duration_of(state),
        )
    ]

class EffectCanvas:
    """Mutable, target-safe frame authoring surface for effect plugins.

    EffectCanvas owns only pixel storage and fixture safety:
    - active cells start with the selected background colour;
    - inactive cells are permanently black;
    - out-of-bounds access raises IndexError;
    - writes to inactive cells are ignored and report False;
    - frame() always returns a validated immutable EffectFrame.

    It intentionally does not own event lifetime, particle/sprite state,
    compositor policy, reactive input, fixture discovery, or hardware access.
    """

    def __init__(
        self,
        target: EffectTarget,
        *,
        background: Colour = (0, 0, 0),
    ) -> None:
        target.validate()
        self._target = target
        self._active = active_cell_set(target)
        self._background = clamp_colour(background)
        self._pixels: list[list[Colour]] = [
            [
                self._background if (row, column) in self._active else (0, 0, 0)
                for column in range(target.columns)
            ]
            for row in range(target.rows)
        ]

    @property
    def target(self) -> EffectTarget:
        return self._target

    @property
    def background(self) -> Colour:
        return self._background

    def _check_bounds(self, cell: Cell) -> None:
        row, column = cell
        if not (
            0 <= row < self._target.rows
            and 0 <= column < self._target.columns
        ):
            raise IndexError(
                f"Cell {cell!r} outside "
                f"{self._target.rows}x{self._target.columns} target."
            )

    def is_active(self, cell: Cell) -> bool:
        self._check_bounds(cell)
        return cell in self._active

    def get(self, cell: Cell) -> Colour:
        self._check_bounds(cell)
        row, column = cell
        return self._pixels[row][column]

    def set(self, cell: Cell, colour: Colour) -> bool:
        self._check_bounds(cell)
        if cell not in self._active:
            return False
        row, column = cell
        self._pixels[row][column] = clamp_colour(colour)
        return True

    def fill(self, colour: Colour) -> None:
        value = clamp_colour(colour)
        for row, column in self._active:
            self._pixels[row][column] = value

    def mix(
        self,
        cell: Cell,
        colour: Colour,
        amount: float,
    ) -> bool:
        self._check_bounds(cell)
        if cell not in self._active:
            return False
        row, column = cell
        self._pixels[row][column] = mix_colour(
            self._pixels[row][column],
            clamp_colour(colour),
            amount,
        )
        return True

    def frame(self) -> EffectFrame:
        frame = EffectFrame(
            rows=self._target.rows,
            columns=self._target.columns,
            pixels=tuple(tuple(row) for row in self._pixels),
        )
        frame.validate()
        return frame

__all__ = [
    "Cell",
    "Colour",
    "EffectCanvas",
    "EffectEvent",
    "EffectTarget",
    "prune_expired",
    "animation_phase",
    "animation_alive",
    "animation_age",
    "active_cell_set",
    "cell_distance",
    "clamp_channel",
    "clamp_colour",
    "event_timestamp",
    "event_matches",
    "event_cell",
    "event_rng",
    "event_seed",
    "event_vivid_colour",
    "hsv_colour",
    "mix_colour",
    "nearest_active_cell",
    "scale_colour",
    "vivid_random_colour",
]
