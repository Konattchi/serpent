#!/usr/bin/env python3
from __future__ import annotations
from serpent_core.effect_sdk import animation_age, animation_phase, prune_expired
from serpent_core.effect_sdk import EffectCanvas

from dataclasses import dataclass
import math
import random

from serpent_core.effect_random import event_seed
from serpent_core.effect_sdk import event_cell, event_matches, event_timestamp
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour = tuple[int, int, int]
Cell = tuple[int, int]


@dataclass(frozen=True)
class _SparkBurst:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseSpark:
    started_at: float
    seed: int
    serial: int


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(a: Colour, b: Colour, amount: float) -> Colour:
    t = max(0.0, min(1.0, amount))
    return tuple(_clamp(a[i] * (1.0 - t) + b[i] * t) for i in range(3))


class SparksEffect(Effect):
    """Short-lived procedural sparks fired from keyboard/mouse presses."""

    definition = EffectDefinition(
        id="sparks",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    def __init__(self) -> None:
        self._bursts: list[_SparkBurst] = []
        self._mouse_bursts: list[_MouseSpark] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.82 - (speed - 1) * 0.045

    @staticmethod
    def _mouse_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.62 - (speed - 1) * 0.032

    @staticmethod
    def _nearest_active(target: EffectTarget, row: float, column: float) -> Cell:
        return min(
            target.active_cells,
            key=lambda cell: (
                (cell[0] - row) ** 2 + (cell[1] - column) ** 2,
                cell[0],
                cell[1],
            ),
        )

    @staticmethod
    def _paths(burst: _SparkBurst) -> tuple[tuple[float, float, float], ...]:
        rng = random.Random(burst.seed)
        count = 4 + rng.randrange(4)  # 4..7 sparks
        paths = []
        for _ in range(count):
            angle = rng.random() * math.tau
            # Wider horizontal travel compensates for the shallow keyboard.
            vr = math.sin(angle) * rng.uniform(2.8, 5.0)
            vc = math.cos(angle) * rng.uniform(4.2, 7.5)
            drag = rng.uniform(0.82, 0.94)
            paths.append((vr, vc, drag))
        return tuple(paths)

    def handle_event(self, event: EffectEvent) -> None:
        if event_matches(
            event,
            kind="key-press",
            source_prefix="keyboard:",
        ):
            cell = event_cell(event)
            if cell is None:
                return
            serial = self._serial
            self._serial += 1
            self._bursts.append(
                _SparkBurst(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="sparks-keyboard",
                    ),
                    serial=serial,
                )
            )
            return

        if event_matches(
            event,
            kind="mouse-press",
            source_prefix="mouse:",
        ):
            serial = self._mouse_serial
            self._mouse_serial += 1
            self._mouse_bursts.append(
                _MouseSpark(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="sparks-mouse",
                    ),
                    serial=serial,
                )
            )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        duration = self._mouse_duration(parameters.speed)
        self._mouse_bursts = prune_expired(
            self._mouse_bursts,
            elapsed,
            lambda _state: duration,
        )

        active_cells = tuple(sorted(target.active_cells))
        active = set(active_cells)
        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )

        for row in range(target.rows):
            for column in range(target.columns):
                cell = (row, column)
                if cell not in active:
                    continue

                colour = parameters.colour1
                for burst in self._mouse_bursts:
                    age = animation_age(
                        elapsed,
                        burst.started_at,
                    )
                    phase = animation_phase(
                        elapsed,
                        burst.started_at,
                        duration,
                    )
                    if not 0.0 <= phase <= 1.0:
                        continue

                    index = active_cells.index(cell)
                    parity = (burst.seed + index) & 1

                    if phase < 0.20:
                        intensity = 1.0 if parity == 0 else 0.45
                    elif phase < 0.42:
                        intensity = 1.0 if parity == 1 else 0.55
                    else:
                        intensity = max(0.0, 1.0 - (phase - 0.42) / 0.58)

                    colour = _mix(colour, parameters.colour2, intensity)

                canvas.set(
                    (row, column),
                    colour,
                )

        return canvas.frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if len(target.active_cells) < 3 or target.rows < 2:
            return self._render_mouse(elapsed, parameters, target)

        duration = self._duration(parameters.speed)
        self._bursts = prune_expired(
            self._bursts,
            elapsed,
            lambda _state: duration,
        )

        active = set(target.active_cells)
        overlays: dict[Cell, tuple[float, float]] = {}

        for burst in self._bursts:
            age = animation_age(
                elapsed,
                burst.started_at,
            )
            if age < 0.0:
                continue
            phase = animation_phase(
                elapsed,
                burst.started_at,
                duration,
            )
            if phase > 1.0:
                continue

            # Initial impact flash.
            origin = self._nearest_active(target, burst.row, burst.column)
            overlays[origin] = max(overlays.get(origin, (0.0, 0.0)), (1.0 - phase, 0.0))

            for vr, vc, drag in self._paths(burst):
                travel = phase * (1.0 + 0.65 * phase)
                head_row = burst.row + vr * travel
                head_col = burst.column + vc * travel

                # Mild drag bends trajectories into short spark-like arcs.
                head_row = burst.row + (head_row - burst.row) * drag

                if (
                    -0.6 <= head_row <= target.rows - 0.4
                    and -0.6 <= head_col <= target.columns - 0.4
                ):
                    cell = self._nearest_active(target, head_row, head_col)
                    if math.hypot(cell[0] - head_row, cell[1] - head_col) <= 1.2:
                        intensity = max(0.0, 1.0 - phase * 0.82)
                        old = overlays.get(cell)
                        if old is None or intensity > old[0]:
                            overlays[cell] = (intensity, 0.0)

                # One dim trailing cell slightly behind the head.
                tail_phase = max(0.0, phase - 0.12)
                tail_travel = tail_phase * (1.0 + 0.65 * tail_phase)
                tail_row = burst.row + vr * tail_travel * drag
                tail_col = burst.column + vc * tail_travel

                if (
                    -0.6 <= tail_row <= target.rows - 0.4
                    and -0.6 <= tail_col <= target.columns - 0.4
                ):
                    cell = self._nearest_active(target, tail_row, tail_col)
                    if math.hypot(cell[0] - tail_row, cell[1] - tail_col) <= 1.2:
                        intensity = max(0.0, (1.0 - phase) * 0.42)
                        old = overlays.get(cell)
                        if old is None or intensity > old[0]:
                            overlays[cell] = (intensity, 1.0)

        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )
        for row in range(target.rows):
            for column in range(target.columns):
                cell = (row, column)
                if cell not in active:
                    continue

                overlay = overlays.get(cell)
                if overlay is None:
                    canvas.set(
                        (row, column),
                        parameters.colour1,
                    )
                else:
                    intensity, _tail = overlay
                    canvas.set(
                        (row, column),
                        _mix(parameters.colour1, parameters.colour2, intensity),
                    )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="sparks",
        name="Sparks",
        description=(
            "Each key press emits several short-lived spark trajectories from "
            "the impact point. Bright one-cell heads and dim trailing cells "
            "scatter in randomized deterministic directions. Mouse clicks use "
            "an isolated two-zone spark pulse."
        ),
        effect_class=SparksEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(5, 5, 10),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Spark Colour",
                kind="colour",
                default=(255, 150, 35),
            ),
            EffectParameterSpec(
                id="speed",
                label="Spark Speed",
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
