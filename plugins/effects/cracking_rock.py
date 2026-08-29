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
from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)

Colour = tuple[int, int, int]
Cell = tuple[int, int]


@dataclass(frozen=True)
class _Fracture:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseFracture:
    started_at: float
    seed: int
    serial: int


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(a: Colour, b: Colour, amount: float) -> Colour:
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(
        _clamp(x + (y - x) * amount)
        for x, y in zip(a, b)
    )


def _scale(colour: Colour, amount: float) -> Colour:
    amount = max(0.0, float(amount))
    return tuple(_clamp(channel * amount) for channel in colour)


def _add(a: Colour, b: Colour) -> Colour:
    return tuple(_clamp(x + y) for x, y in zip(a, b))


class CrackingRockEffect(Effect):
    """Dark stone background with deterministic branching impact fractures."""

    definition = EffectDefinition(
        id="cracking-rock",
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
        self._fractures: list[_Fracture] = []
        self._mouse_fractures: list[_MouseFracture] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _lifetime(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # Slow = lingering glowing fault lines; fast = violent short crack.
        return 2.50 - (speed - 1) * 0.245

    @staticmethod
    def _formation_time(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # Cracks should always feel nearly instantaneous.
        return 0.090 - (speed - 1) * 0.004

    @staticmethod
    def _mouse_lifetime(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 1.10 - (speed - 1) * 0.070

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
            self._fractures.append(
                _Fracture(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="cracking-rock-keyboard",
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
            self._mouse_fractures.append(
                _MouseFracture(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="cracking-rock-mouse",
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
    def _fracture_geometry(
        cls,
        fracture: _Fracture,
        target: EffectTarget,
    ) -> tuple[tuple[Cell, int], ...]:
        """Generate 2-3 simple deterministic fault lines from the impact."""
        if not target.active_cells:
            return ()

        rng = random.Random(
            fracture.seed
            ^ (target.rows << 17)
            ^ (target.columns << 3)
            ^ len(target.active_cells)
        )

        origin = cls._nearest_active(
            target,
            fracture.row,
            fracture.column,
        )

        active = set(target.active_cells)
        chosen: dict[Cell, int] = {origin: 0}

        min_row = min(cell[0] for cell in active)
        max_row = max(cell[0] for cell in active)
        min_column = min(cell[1] for cell in active)
        max_column = max(cell[1] for cell in active)

        # Candidate destinations are real active cells on the outer boundary.
        boundary = tuple(
            sorted(
                cell
                for cell in active
                if (
                    cell[0] in {min_row, max_row}
                    or cell[1] in {min_column, max_column}
                )
                and cell != origin
            )
        )

        if not boundary:
            return tuple(chosen.items())

        arm_count = 2 + rng.randrange(2)  # 2 or 3 major cracks.

        # Divide the boundary into angular sectors around the impact so the
        # major fault lines tend to spread apart instead of overlapping.
        def angle(cell: Cell) -> float:
            return math.atan2(
                cell[0] - origin[0],
                cell[1] - origin[1],
            )

        ordered_boundary = sorted(boundary, key=angle)

        # Pick destinations from separated portions of the boundary.
        destinations: list[Cell] = []
        if ordered_boundary:
            offset = rng.randrange(len(ordered_boundary))
            spacing = max(1, len(ordered_boundary) // arm_count)

            for index in range(arm_count):
                candidate_index = (
                    offset + index * spacing + rng.randrange(max(1, spacing))
                ) % len(ordered_boundary)
                candidate = ordered_boundary[candidate_index]

                if candidate not in destinations:
                    destinations.append(candidate)

        # Fall back to extra boundary cells if angular picks collided.
        for candidate in boundary:
            if len(destinations) >= arm_count:
                break
            if candidate not in destinations:
                destinations.append(candidate)

        for arm_index, destination in enumerate(destinations):
            row = float(origin[0])
            column = float(origin[1])

            delta_row = destination[0] - origin[0]
            delta_column = destination[1] - origin[1]

            distance = max(
                1.0,
                math.hypot(delta_row, delta_column),
            )

            # One sample per approximately one LED of travel.
            steps = max(
                2,
                round(distance),
            )

            # Each arm gets a tiny perpendicular bend profile.  This creates
            # visible cracks rather than ruler-straight lines without turning
            # them into lightning.
            bend_strength = rng.uniform(-0.70, 0.70)
            bend_phase = rng.uniform(0.0, math.pi * 2.0)

            perpendicular_row = -delta_column / distance
            perpendicular_column = delta_row / distance

            generation = 0

            for step in range(1, steps + 1):
                progress = step / steps

                base_row = origin[0] + delta_row * progress
                base_column = origin[1] + delta_column * progress

                # Gentle low-frequency wobble with one or two kinks.
                wobble = (
                    math.sin(progress * math.pi * 1.5 + bend_phase)
                    * bend_strength
                )

                if step not in {1, steps} and rng.random() < 0.12:
                    wobble += rng.choice((-0.55, 0.55))

                intended_row = base_row + perpendicular_row * wobble
                intended_column = (
                    base_column + perpendicular_column * wobble
                )

                cell = cls._nearest_active(
                    target,
                    intended_row,
                    intended_column,
                )

                # Do not let sparse-topology snapping jump wildly away from
                # the intended path.
                if math.hypot(
                    cell[0] - intended_row,
                    cell[1] - intended_column,
                ) > 1.60:
                    continue

                generation += 1
                old = chosen.get(cell)
                if old is None or generation < old:
                    chosen[cell] = generation

            # Guarantee the visible fault actually reaches its chosen edge.
            generation += 1
            old = chosen.get(destination)
            if old is None or generation < old:
                chosen[destination] = generation

        return tuple(
            sorted(
                chosen.items(),
                key=lambda item: (
                    item[1],
                    item[0][0],
                    item[0][1],
                ),
            )
        )

    @staticmethod
    def _rock_colour(base: Colour, row: int, column: int) -> Colour:
        # Very subtle fixed variation makes the background read less flat
        # without introducing autonomous animation.
        variation = ((row * 7 + column * 11) % 5) - 2
        return tuple(
            _clamp(channel + variation)
            for channel in base
        )

    @staticmethod
    def _crack_colour(
        crack: Colour,
        intensity: float,
        generation: int,
    ) -> Colour:
        # Keep the fracture exactly in the user-selected hue.
        # Only brightness changes over its lifetime; no whitening,
        # heating tint, or colour drift is applied.
        return _scale(crack, intensity)

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        lifetime = self._mouse_lifetime(parameters.speed)
        self._mouse_fractures = prune_expired(
            self._mouse_fractures,
            elapsed,
            lambda _state: lifetime,
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

                colour = self._rock_colour(
                    parameters.colour1,
                    row,
                    column,
                )

                for fracture in self._mouse_fractures:
                    age = animation_age(
                        elapsed,
                        fracture.started_at,
                    )
                    if not 0.0 <= age <= lifetime:
                        continue

                    phase = animation_phase(
                        elapsed,
                        fracture.started_at,
                        lifetime,
                    )
                    if phase < 0.16:
                        # Instant fracture: first one zone, then both.
                        local = phase / 0.16
                        forward = (fracture.seed & 1) == 0
                        order = (
                            active_cells
                            if forward
                            else tuple(reversed(active_cells))
                        )
                        index = order.index(cell)
                        threshold = index / max(1, len(order))
                        intensity = 1.0 if local >= threshold else 0.25
                    elif phase < 0.40:
                        intensity = 1.0
                    else:
                        intensity = max(
                            0.0,
                            1.0 - (phase - 0.40) / 0.60,
                        )

                    colour = _add(
                        colour,
                        self._crack_colour(
                            parameters.colour2,
                            intensity,
                            0,
                        ),
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
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        lifetime = self._lifetime(parameters.speed)
        formation = self._formation_time(parameters.speed)

        self._fractures = prune_expired(
            self._fractures,
            elapsed,
            lambda _state: lifetime,
        )

        active = set(target.active_cells)

        geometry = [
            (
                fracture,
                dict(self._fracture_geometry(fracture, target)),
            )
            for fracture in self._fractures
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

                colour = self._rock_colour(
                    parameters.colour1,
                    row,
                    column,
                )

                for fracture, crack_cells in geometry:
                    generation = crack_cells.get(cell)
                    if generation is None:
                        continue

                    age = animation_age(
                        elapsed,
                        fracture.started_at,
                    )
                    if age < 0.0:
                        continue

                    # Generation-based stagger is tiny: visually this is still
                    # an almost instantaneous fracture.
                    reveal = generation * formation / 12.0
                    if age < reveal:
                        continue

                    phase = animation_phase(
                        elapsed,
                        fracture.started_at,
                        lifetime,
                    )

                    if phase < 0.10:
                        intensity = min(
                            1.0,
                            max(0.0, (age - reveal) / max(formation, 0.001)),
                        )
                    elif phase < 0.34:
                        intensity = 1.0
                    else:
                        fade = (phase - 0.34) / 0.66
                        intensity = max(0.0, 1.0 - fade)
                        # Tips cool/die a little sooner than the main fault.
                        intensity *= max(
                            0.40,
                            1.0 - generation * 0.035,
                        )

                    if intensity <= 0.0:
                        continue

                    colour = _add(
                        colour,
                        self._crack_colour(
                            parameters.colour2,
                            intensity,
                            generation,
                        ),
                    )

                canvas.set(
                    (row, column),
                    colour,
                )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="cracking-rock",
        name="Cracking Rock",
        description=(
            "A dark stone surface fractures from keyboard impacts into "
            "two or three simple crooked fault lines that run from the impact "
            "toward outer edges, appear almost instantly, hold briefly, and "
            "cool away. Keyboard and mouse "
            "reactions are isolated; mouse buttons trigger a mouse-only "
            "miniature fracture flash."
        ),
        effect_class=CrackingRockEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Rock Colour",
                kind="colour",
                default=(30, 32, 36),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Crack Colour",
                kind="colour",
                default=(255, 82, 12),
            ),
            EffectParameterSpec(
                id="speed",
                label="Crack Decay Speed",
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
