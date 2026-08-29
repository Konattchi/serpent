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
class _Arc:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseArc:
    started_at: float
    seed: int
    serial: int


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _scale(colour: Colour, amount: float) -> Colour:
    amount = max(0.0, float(amount))
    return tuple(_clamp(channel * amount) for channel in colour)


def _add(a: Colour, b: Colour) -> Colour:
    return tuple(_clamp(x + y) for x, y in zip(a, b))


class TeslaLightningEffect(Effect):
    """Visible key-originating electrical arcs over a readable background."""

    definition = EffectDefinition(
        id="tesla-lightning",
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
        self._arcs: list[_Arc] = []
        self._mouse_arcs: list[_MouseArc] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 1.30 - (speed - 1) * 0.085

    @staticmethod
    def _growth_fraction(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.56 - (speed - 1) * 0.018

    @staticmethod
    def _mouse_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.90 - (speed - 1) * 0.050

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
            self._arcs.append(
                _Arc(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="tesla-lightning-keyboard",
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
            self._mouse_arcs.append(
                _MouseArc(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="tesla-lightning-mouse",
                    ),
                    serial=serial,
                )
            )

    @staticmethod
    def _nearest_active(
        target: EffectTarget,
        row: float,
        column: float,
    ) -> Cell:
        return min(
            target.active_cells,
            key=lambda cell: (
                (cell[0] - row) ** 2 + (cell[1] - column) ** 2,
                cell[0],
                cell[1],
            ),
        )

    @classmethod
    def _arc_geometry(
        cls,
        arc: _Arc,
        target: EffectTarget,
    ) -> tuple[tuple[Cell, int, int], ...]:
        """Return a main Tesla arc with readable secondary/tertiary forks."""
        if not target.active_cells:
            return ()

        active = set(target.active_cells)
        origin = cls._nearest_active(target, arc.row, arc.column)

        rng = random.Random(
            arc.seed
            ^ (target.rows << 15)
            ^ (target.columns << 5)
            ^ len(active)
        )

        directions = [
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        ]

        # One dominant trunk.
        main_direction = directions[rng.randrange(len(directions))]
        max_length = max(
            4,
            min(11, round(math.sqrt(max(1, len(active))) * 0.90)),
        )

        # Cell metadata: growth step, branch depth.
        results: dict[Cell, tuple[int, int]] = {origin: (0, 0)}

        # Each pending branch stores:
        # current row/column, heading, start step, depth, remaining length.
        queue: list[
            tuple[int, int, int, int, int, int, int, int]
        ] = [
            (
                origin[0],
                origin[1],
                main_direction[0],
                main_direction[1],
                0,
                0,
                max_length,
                0,
            )
        ]

        branch_budget = 5
        branches_created = 0

        while queue:
            (
                row,
                column,
                heading_row,
                heading_column,
                start_step,
                depth,
                remaining,
                branch_serial,
            ) = queue.pop(0)

            for local_step in range(1, remaining + 1):
                absolute_step = start_step + local_step

                # Frequent small kinks give a crooked electrical shape.
                if rng.random() < (0.34 if depth == 0 else 0.42):
                    if rng.random() < 0.5:
                        heading_row = max(
                            -1,
                            min(
                                1,
                                heading_row + rng.choice((-1, 1)),
                            ),
                        )
                    else:
                        heading_column = max(
                            -1,
                            min(
                                1,
                                heading_column + rng.choice((-1, 1)),
                            ),
                        )

                    if heading_row == 0 and heading_column == 0:
                        heading_column = rng.choice((-1, 1))

                row += heading_row
                column += heading_column

                if not (
                    0 <= row < target.rows
                    and 0 <= column < target.columns
                ):
                    break

                cell = cls._nearest_active(target, row, column)

                if math.hypot(cell[0] - row, cell[1] - column) > 1.5:
                    break

                old = results.get(cell)
                candidate = (absolute_step, depth)

                # Keep the earliest/strongest path if branches collide.
                if (
                    old is None
                    or depth < old[1]
                    or (
                        depth == old[1]
                        and absolute_step < old[0]
                    )
                ):
                    results[cell] = candidate

                # Fork only after the trunk has visibly developed.
                if (
                    branches_created < branch_budget
                    and depth < 2
                    and local_step >= 2
                ):
                    probability = (
                        0.30 if depth == 0 else 0.18
                    )

                    if rng.random() < probability:
                        turn = rng.choice((-1, 1))

                        # Rotate heading into a clearly diverging fork.
                        fork_row = heading_row + turn * heading_column
                        fork_column = heading_column - turn * heading_row

                        fork_row = max(-1, min(1, fork_row))
                        fork_column = max(-1, min(1, fork_column))

                        if fork_row == 0 and fork_column == 0:
                            fork_column = turn

                        fork_length = max(
                            2,
                            round(
                                remaining
                                * (
                                    0.52
                                    if depth == 0
                                    else 0.38
                                )
                            ),
                        )

                        queue.append(
                            (
                                cell[0],
                                cell[1],
                                fork_row,
                                fork_column,
                                absolute_step,
                                depth + 1,
                                fork_length,
                                branches_created + 1,
                            )
                        )
                        branches_created += 1

        return tuple(
            (
                cell,
                metadata[0],
                metadata[1],
            )
            for cell, metadata in sorted(
                results.items(),
                key=lambda item: (
                    item[1][0],
                    item[1][1],
                    item[0][0],
                    item[0][1],
                ),
            )
        )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        duration = self._mouse_duration(parameters.speed)
        self._mouse_arcs = prune_expired(
            self._mouse_arcs,
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

                for arc in self._mouse_arcs:
                    age = animation_age(
                        elapsed,
                        arc.started_at,
                    )
                    phase = animation_phase(
                        elapsed,
                        arc.started_at,
                        duration,
                    )
                    if not 0.0 <= phase <= 1.0:
                        continue

                    order = (
                        active_cells
                        if (arc.seed & 1) == 0
                        else tuple(reversed(active_cells))
                    )
                    index = order.index(cell)
                    threshold = index / max(1, len(order))

                    if phase < 0.42:
                        growth = phase / 0.42
                        intensity = 1.0 if growth >= threshold else 0.0
                    elif phase < 0.62:
                        # Brief whole-mouse electrical hold.
                        intensity = 1.0
                    else:
                        intensity = max(0.0, 1.0 - (phase - 0.62) / 0.38)

                    colour = _add(
                        colour,
                        _scale(parameters.colour2, intensity),
                    )

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
        growth_fraction = self._growth_fraction(parameters.speed)

        self._arcs = prune_expired(
            self._arcs,
            elapsed,
            lambda _state: duration,
        )

        active = set(target.active_cells)
        geometries = [
            (arc, self._arc_geometry(arc, target))
            for arc in self._arcs
        ]

        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )
        for row in range(target.rows):
            for column in range(target.columns):
                cell = (row, column)

                if cell not in active:
                    continue

                # Background is deliberately direct: the user controls its
                # effective brightness by choosing a darker/lighter RGB value.
                colour = parameters.colour1

                for arc, geometry in geometries:
                    age = animation_age(
                        elapsed,
                        arc.started_at,
                    )
                    if age < 0.0:
                        continue

                    phase = animation_phase(
                        elapsed,
                        arc.started_at,
                        duration,
                    )
                    if not 0.0 <= phase <= 1.0:
                        continue

                    max_step = max(
                        (step for _, step, _ in geometry),
                        default=0,
                    )

                    entry = next(
                        (
                            (step, branch)
                            for geometry_cell, step, branch in geometry
                            if geometry_cell == cell
                        ),
                        None,
                    )
                    if entry is None:
                        continue

                    step, branch = entry
                    reveal_fraction = (
                        (step / max(1, max_step))
                        * growth_fraction
                    )
                    if phase < reveal_fraction:
                        continue

                    if phase < growth_fraction:
                        # Arc is actively crawling outward. Newer cells are
                        # brightest; older cells retain a visible energized tail.
                        local_age = phase - reveal_fraction
                        intensity = max(
                            0.58,
                            1.0 - local_age * 0.75,
                        )
                    elif phase < 0.72:
                        # Entire path briefly remains energized.
                        intensity = 0.78
                    else:
                        # Dim afterimage fades without changing selected hue.
                        intensity = max(
                            0.0,
                            0.78 * (1.0 - (phase - 0.72) / 0.28),
                        )

                    # Clear electrical hierarchy:
                    # dominant trunk > secondary fork > tertiary fork.
                    if branch == 1:
                        intensity *= 0.74
                    elif branch >= 2:
                        intensity *= 0.50

                    colour = _add(
                        colour,
                        _scale(parameters.colour2, intensity),
                    )

                canvas.set(
                    (row, column),
                    colour,
                )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="tesla-lightning",
        name="Tesla Lightning",
        description=(
            "Key presses emit a visibly growing dominant Tesla arc with "
            "random secondary and occasional tertiary forks from the pressed "
            "key over a configurable illuminated background. "
            "The selected lightning hue is preserved while brightness decays. "
            "Mouse clicks trigger an isolated two-zone electrical surge."
        ),
        effect_class=TeslaLightningEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(12, 12, 18),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Lightning Colour",
                kind="colour",
                default=(90, 170, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Arc Speed",
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
