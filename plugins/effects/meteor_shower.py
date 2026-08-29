#!/usr/bin/env python3
from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas

import colorsys
import hashlib
import math
import random

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour = tuple[int, int, int]


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(a: Colour, b: Colour, amount: float) -> Colour:
    t = max(0.0, min(1.0, amount))
    return tuple(
        _clamp(a[i] * (1.0 - t) + b[i] * t)
        for i in range(3)
    )


def _vivid_colour(rng: random.Random) -> Colour:
    hue = rng.random()
    saturation = rng.uniform(0.82, 1.0)
    value = rng.uniform(0.90, 1.0)
    red, green, blue = colorsys.hsv_to_rgb(
        hue,
        saturation,
        value,
    )
    return (
        _clamp(red * 255),
        _clamp(green * 255),
        _clamp(blue * 255),
    )


class MeteorShowerEffect(Effect):
    """Autonomous vivid diagonal meteors with irregular timing."""

    definition = EffectDefinition(
        id="meteor-shower",
        colours=1,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=10,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    BASE_SEED = "serpent-e10-meteor-shower-v1"

    @classmethod
    def _rng(cls, index: int, namespace: str) -> random.Random:
        digest = hashlib.sha256(
            f"{cls.BASE_SEED}:{namespace}:{index}".encode("utf-8")
        ).digest()
        return random.Random(
            int.from_bytes(digest[:8], "big")
        )

    @staticmethod
    def _base_gap(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return max(
            0.52,
            1.12 - (speed - 1) * 0.055,
        )

    @classmethod
    def _gap_after(cls, index: int, speed: int) -> float:
        rng = cls._rng(index, "gap")

        # Intentionally wide range so the shower does not read like a
        # metronome. Some meteors arrive in loose pairs, others leave a pause.
        multiplier = rng.uniform(0.48, 1.72)

        if rng.random() < 0.16:
            multiplier *= 0.58

        return max(
            0.24,
            cls._base_gap(speed) * multiplier,
        )

    @classmethod
    def _start_time(cls, index: int, speed: int) -> float:
        if index <= 0:
            return 0.0

        total = 0.0

        for previous in range(index):
            total += cls._gap_after(
                previous,
                speed,
            )

        return total

    @staticmethod
    def _flight_duration(
        speed: int,
        speed_scale: float,
    ) -> float:
        speed = max(1, min(10, int(speed)))

        base = max(
            0.52,
            1.18 - (speed - 1) * 0.055,
        )

        return base / max(
            0.72,
            speed_scale,
        )

    @classmethod
    def _meteor(
        cls,
        index: int,
        target: EffectTarget,
    ) -> dict[str, object]:
        rng = cls._rng(index, "meteor")

        columns = max(
            1,
            target.columns,
        )

        start_column = rng.randrange(columns)

        direction = rng.choice(
            (-1, 1)
        )

        horizontal_span = rng.uniform(
            max(2.0, target.columns * 0.22),
            max(3.0, target.columns * 0.52),
        )

        end_column = (
            start_column
            + direction * horizontal_span
        )

        return {
            "start_column": start_column,
            "end_column": end_column,
            "colour": _vivid_colour(rng),
            "speed_scale": rng.uniform(
                0.84,
                1.18,
            ),
            "tail_length": rng.choice(
                (2, 2, 3),
            ),
        }

    @classmethod
    def _relevant_indices(
        cls,
        elapsed: float,
        parameters: EffectParameters,
    ) -> tuple[int, ...]:
        # Irregular start times prevent simple slot arithmetic.
        # Walk only far enough to cover current time and a small future margin.
        indices: list[int] = []
        index = 0

        while index < 512:
            started = cls._start_time(
                index,
                parameters.speed,
            )

            if started > elapsed + 0.25:
                break

            # Keep the current and recent meteors.
            if elapsed - started <= 2.2:
                indices.append(index)

            index += 1

        return tuple(indices)

    @staticmethod
    def _is_mouse(
        target: EffectTarget,
    ) -> bool:
        return (
            target.rows <= 1
            or len(target.active_cells) <= 3
        )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        active_cells = tuple(
            sorted(
                target.active_cells
            )
        )
        active = set(
            active_cells
        )

        # Use canonical spatial dimensions only to derive the same autonomous
        # meteor identity/colour. No device model or hardcoded fixture anatomy.
        canonical = EffectTarget.full(
            6,
            22,
        )

        chosen_colour: Colour | None = None
        chosen_phase = 0.0
        newest_start = -1.0

        for index in self._relevant_indices(
            elapsed,
            parameters,
        ):
            started = self._start_time(
                index,
                parameters.speed,
            )
            meteor = self._meteor(
                index,
                canonical,
            )
            duration = self._flight_duration(
                parameters.speed,
                float(
                    meteor["speed_scale"]
                ),
            )

            age = elapsed - started

            if not (
                0.0 <= age <= duration
            ):
                continue

            # Only a minority of keyboard meteors visually cross the tiny
            # mouse companion area. Deterministic selection keeps it sparse.
            selector = self._rng(
                index,
                "mouse-selection",
            )

            if selector.random() > 0.34:
                continue

            if started < newest_start:
                continue

            chosen_colour = meteor[
                "colour"
            ]
            assert isinstance(
                chosen_colour,
                tuple,
            )

            chosen_phase = age / max(
                duration,
                0.001,
            )
            newest_start = started

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        if (
            chosen_colour is not None
            and active_cells
        ):
            center = (
                chosen_phase
                * (
                    len(active_cells)
                    + 0.70
                )
            )

            for index, cell in enumerate(
                active_cells
            ):
                # Tiny streak: first LED -> second LED -> fade.
                distance = abs(
                    index - center
                )

                intensity = max(
                    0.0,
                    1.0
                    - distance / 0.78,
                )

                fade = max(
                    0.0,
                    1.0
                    - max(
                        0.0,
                        chosen_phase - 0.72,
                    )
                    / 0.28,
                )

                intensity *= fade

                if intensity > 0.0:
                    canvas.set(
                        cell,
                        _mix(
                            parameters.colour1,
                            chosen_colour,
                            intensity,
                        ),
                    )

        return canvas.frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if self._is_mouse(
            target
        ):
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        active = set(
            target.active_cells
        )

        overlays: dict[
            tuple[int, int],
            tuple[
                float,
                Colour,
            ],
        ] = {}

        def paint(
            row: int,
            column: int,
            intensity: float,
            colour: Colour,
        ) -> None:
            cell = (
                row,
                column,
            )

            if (
                cell not in active
                or intensity <= 0.0
            ):
                return

            old = overlays.get(
                cell
            )

            # Strongest meteor wins at intersections instead of additive
            # colour mixing that would wash overlapping hues toward white.
            if (
                old is None
                or intensity >= old[0]
            ):
                overlays[
                    cell
                ] = (
                    intensity,
                    colour,
                )

        for index in self._relevant_indices(
            elapsed,
            parameters,
        ):
            started = self._start_time(
                index,
                parameters.speed,
            )

            meteor = self._meteor(
                index,
                target,
            )

            duration = self._flight_duration(
                parameters.speed,
                float(
                    meteor[
                        "speed_scale"
                    ]
                ),
            )

            age = elapsed - started

            if not (
                0.0 <= age <= duration
            ):
                continue

            phase = age / max(
                duration,
                0.001,
            )

            colour = meteor[
                "colour"
            ]
            assert isinstance(
                colour,
                tuple,
            )

            start_column = float(
                meteor[
                    "start_column"
                ]
            )
            end_column = float(
                meteor[
                    "end_column"
                ]
            )

            # Begin slightly above the top edge and leave slightly below the
            # bottom so the streak visibly enters/exits the fixture.
            head_row = (
                -0.65
                + phase
                * (
                    target.rows
                    + 1.30
                )
            )

            head_column = (
                start_column
                + (
                    end_column
                    - start_column
                )
                * phase
            )

            tail_length = int(
                meteor[
                    "tail_length"
                ]
            )

            for trail in range(
                tail_length + 1
            ):
                trail_phase = max(
                    0.0,
                    phase
                    - trail
                    * 0.085,
                )

                row_position = (
                    -0.65
                    + trail_phase
                    * (
                        target.rows
                        + 1.30
                    )
                )

                column_position = (
                    start_column
                    + (
                        end_column
                        - start_column
                    )
                    * trail_phase
                )

                row = round(
                    row_position
                )
                column = round(
                    column_position
                )

                if not (
                    0 <= row < target.rows
                    and 0
                    <= column
                    < target.columns
                ):
                    continue

                intensity = (
                    1.0
                    if trail == 0
                    else max(
                        0.18,
                        0.62
                        - trail
                        * 0.17,
                    )
                )

                # Slight fade as meteor approaches the bottom.
                if phase > 0.84:
                    intensity *= max(
                        0.0,
                        1.0
                        - (
                            phase
                            - 0.84
                        )
                        / 0.16,
                    )

                paint(
                    row,
                    column,
                    intensity,
                    colour,
                )

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell, overlay in overlays.items():
            intensity, colour = overlay
            canvas.set(
                cell,
                _mix(
                    parameters.colour1,
                    colour,
                    intensity,
                ),
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="meteor-shower",
        name="Meteor Shower",
        description=(
            "Autonomous vivid meteors enter from random top-edge positions, "
            "travel diagonally across the matrix with random direction, speed "
            "and 2-3 LED tails, then leave without exploding. Launch gaps are "
            "deliberately irregular. Low-resolution mouse targets occasionally "
            "receive a matching procedural-colour streak."
        ),
        effect_class=MeteorShowerEffect,
        input_capabilities=(),
        render_targets=(
            "keyboard",
            "mouse",
        ),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(
                    3,
                    4,
                    10,
                ),
            ),
            EffectParameterSpec(
                id="speed",
                label="Meteor Speed",
                kind="integer",
                default=5,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
