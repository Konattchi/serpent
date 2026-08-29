from __future__ import annotations
from serpent_core.effect_sdk import animation_age, animation_phase, prune_expired
from serpent_core.effect_sdk import EffectCanvas

from dataclasses import dataclass
import math

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
class _Meteor:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseMeteor:
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
    return tuple(
        _clamp(component * amount)
        for component in colour
    )


def _add(a: Colour, b: Colour) -> Colour:
    return tuple(
        _clamp(x + y)
        for x, y in zip(a, b)
    )


class MeteorExplosionEffect(Effect):
    """A deterministic projectile-to-impact reactive effect."""

    definition = EffectDefinition(
        id="meteor-explosion",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    MAX_RADIUS = 4.5

    def __init__(self) -> None:
        self._meteors: list[_Meteor] = []
        self._mouse_meteors: list[_MouseMeteor] = []
        self._serial = 0
        self._mouse_serial = 0

    @property
    def active_meteor_count(self) -> int:
        return len(self._meteors)

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

            self._meteors.append(
                _Meteor(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="meteor-explosion-keyboard",
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

            self._mouse_meteors.append(
                _MouseMeteor(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="meteor-explosion-mouse",
                    ),
                    serial=serial,
                )
            )

    @staticmethod
    def _flight_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.78 - (speed - 1) * 0.045

    @staticmethod
    def _blast_rate(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 5.0 + speed * 1.25

    @staticmethod
    def _ring_width(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 1.55 - (speed - 1) * 0.025

    @classmethod
    def _lifetime(cls, speed: int) -> float:
        return (
            cls._flight_duration(speed)
            + (cls.MAX_RADIUS + cls._ring_width(speed))
            / cls._blast_rate(speed)
            + 0.08
        )

    @staticmethod
    def _nearest_active(
        target: EffectTarget,
        row: int,
        column: int,
    ) -> Cell:
        return min(
            target.active_cells,
            key=lambda cell: (
                (cell[0] - row) ** 2 + (cell[1] - column) ** 2,
                cell[0],
                cell[1],
            ),
        )

    @staticmethod
    def _entry_cell(
        target: EffectTarget,
        destination: Cell,
        seed: int,
    ) -> Cell:
        active = tuple(target.active_cells)
        if len(active) == 1:
            return active[0]

        rows = [cell[0] for cell in active]
        columns = [cell[1] for cell in active]
        min_row = min(rows)
        max_row = max(rows)
        min_column = min(columns)
        max_column = max(columns)

        # Meteor origin is deliberately independent of the destination.
        # Any controllable cell on the active top edge is an equal candidate.
        # This avoids left-side keys always receiving meteors from the right
        # (or vice versa) and preserves the fun of very short or very long
        # trajectories purely through deterministic RNG.
        top_edge = tuple(
            sorted(
                cell
                for cell in active
                if cell[0] == min_row
            )
        )

        candidates = top_edge or tuple(sorted(active))
        return candidates[seed % len(candidates)]

    @staticmethod
    def _projectile_colour(
        *,
        distance: float,
        progress: float,
        meteor_colour: Colour,
    ) -> Colour:
        # White-hot head, coloured body, red-orange tail.
        if distance <= 0.45:
            base = _mix((255, 255, 235), meteor_colour, distance / 0.45)
            strength = 1.0
        elif distance <= 1.35:
            base = meteor_colour
            strength = 1.0 - (distance - 0.45) / 0.90 * 0.32
        elif distance <= 2.45:
            base = _mix(meteor_colour, (190, 28, 0), 0.65)
            strength = max(0.0, 0.58 - (distance - 1.35) / 1.10 * 0.50)
        else:
            return (0, 0, 0)

        # Small ignition/fade at the beginning keeps spawning from popping.
        birth = min(1.0, progress / 0.10) if progress < 0.10 else 1.0
        return _scale(base, strength * birth)

    @staticmethod
    def _impact_colour(
        *,
        distance: float,
        radius: float,
        intensity: float,
        meteor_colour: Colour,
        impact_colour: Colour,
    ) -> Colour:
        if radius <= 0.001:
            heat = 0.0
        else:
            heat = max(0.0, min(1.35, distance / radius))

        white_hot = (255, 250, 225)

        if heat < 0.42:
            colour = _mix(
                white_hot,
                meteor_colour,
                heat / 0.42,
            )
        elif heat < 0.78:
            colour = _mix(
                meteor_colour,
                impact_colour,
                (heat - 0.42) / 0.36,
            )
        else:
            colour = _mix(
                impact_colour,
                (150, 10, 0),
                min(1.0, (heat - 0.78) / 0.42),
            )

        return _scale(colour, intensity)

    @staticmethod
    def _mouse_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.70 - (speed - 1) * 0.025

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        duration = self._mouse_duration(parameters.speed)

        self._mouse_meteors = prune_expired(
            self._mouse_meteors,
            elapsed,
            lambda _state: duration,
        )

        active_cells = tuple(sorted(target.active_cells))
        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )

        for cell in active_cells:
            colour: Colour = (0, 0, 0)

            for meteor in self._mouse_meteors:
                age = animation_age(
                    elapsed,
                    meteor.started_at,
                )
                if not 0.0 <= age <= duration:
                    continue

                phase = animation_phase(
                    elapsed,
                    meteor.started_at,
                    duration,
                )

                # Two-zone miniature meteor:
                # 0.00-0.42: bright head travels through the physical zones
                # 0.42-0.64: both zones flash at impact
                # 0.64-1.00: orange/red thermal decay
                if len(active_cells) <= 1:
                    index = 0
                else:
                    forward = (meteor.seed & 1) == 0
                    ordered = (
                        active_cells
                        if forward
                        else tuple(reversed(active_cells))
                    )
                    index = ordered.index(cell)

                position = (
                    0.0
                    if len(active_cells) <= 1
                    else index / (len(active_cells) - 1)
                )

                if phase < 0.42:
                    travel = phase / 0.42
                    distance = abs(position - travel)

                    if distance <= 0.20:
                        local = 1.0 - distance / 0.20
                        pulse = _mix(
                            parameters.colour1,
                            (255, 255, 235),
                            0.70 * local,
                        )
                        pulse = _scale(pulse, 0.45 + 0.55 * local)
                    elif position < travel and travel - position <= 0.75:
                        trail = 1.0 - (travel - position) / 0.75
                        pulse = _scale(
                            _mix(
                                parameters.colour1,
                                parameters.colour2,
                                0.70,
                            ),
                            0.18 + trail * 0.35,
                        )
                    else:
                        pulse = (0, 0, 0)

                elif phase < 0.64:
                    impact_phase = (phase - 0.42) / 0.22
                    hot = 1.0 - abs(impact_phase - 0.45) / 0.55
                    hot = max(0.0, min(1.0, hot))

                    pulse = _mix(
                        parameters.colour2,
                        (255, 250, 220),
                        0.82 * hot,
                    )
                    pulse = _scale(
                        pulse,
                        0.62 + 0.38 * hot,
                    )

                else:
                    decay = max(
                        0.0,
                        1.0 - (phase - 0.64) / 0.36,
                    )
                    pulse = _scale(
                        _mix(
                            parameters.colour2,
                            (135, 8, 0),
                            1.0 - decay,
                        ),
                        decay,
                    )

                colour = _add(colour, pulse)

            canvas.set(
                cell,
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

        speed = max(1, min(10, int(parameters.speed)))
        lifetime = self._lifetime(speed)

        self._meteors = prune_expired(
            self._meteors,
            elapsed,
            lambda _state: lifetime,
        )

        if not target.active_cells:
            return EffectCanvas(
                target,
                background=(0, 0, 0),
            ).frame()

        if len(target.active_cells) < 3 or target.rows < 2:
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        flight = self._flight_duration(speed)
        blast_rate = self._blast_rate(speed)
        ring_width = self._ring_width(speed)

        geometry = []
        for meteor in self._meteors:
            destination = self._nearest_active(
                target,
                meteor.row,
                meteor.column,
            )
            entry = self._entry_cell(
                target,
                destination,
                meteor.seed,
            )
            geometry.append((meteor, entry, destination))

        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )

        for row, column in target.active_cells:
            cell = (row, column)
            colour: Colour = (0, 0, 0)

            for meteor, entry, destination in geometry:
                age = animation_age(
                    elapsed,
                    meteor.started_at,
                )
                if age < 0.0:
                    continue

                if age < flight:
                    progress = max(0.0, min(1.0, age / flight))
                    head_row = entry[0] + (
                        destination[0] - entry[0]
                    ) * progress
                    head_column = entry[1] + (
                        destination[1] - entry[1]
                    ) * progress

                    vector_row = destination[0] - entry[0]
                    vector_column = destination[1] - entry[1]
                    vector_length = max(
                        0.001,
                        math.hypot(vector_row, vector_column),
                    )
                    unit_row = vector_row / vector_length
                    unit_column = vector_column / vector_length

                    # Directional 2x2 meteor footprint. Keep the existing
                    # trajectory/timing, but give the projectile a heavier,
                    # asymmetric body around the moving head.
                    rounded_head_row = int(round(head_row))
                    rounded_head_column = int(round(head_column))

                    row_step = 1 if vector_row >= 0 else -1
                    if vector_column > 0:
                        column_step = 1
                    elif vector_column < 0:
                        column_step = -1
                    else:
                        column_step = (
                            1 if (meteor.seed & 1) == 0 else -1
                        )

                    body_cells = {
                        (rounded_head_row, rounded_head_column): 0.00,
                        (
                            rounded_head_row,
                            rounded_head_column - column_step,
                        ): 0.34,
                        (
                            rounded_head_row - row_step,
                            rounded_head_column,
                        ): 0.48,
                        (
                            rounded_head_row - row_step,
                            rounded_head_column - column_step,
                        ): 0.72,
                    }

                    body_distance = body_cells.get(cell)
                    if body_distance is None:
                        continue

                    projectile = self._projectile_colour(
                        distance=body_distance,
                        progress=progress,
                        meteor_colour=parameters.colour1,
                    )
                    colour = _add(colour, projectile)
                    continue

                impact_age = age - flight
                radius = impact_age * blast_rate
                if radius > self.MAX_RADIUS + ring_width:
                    continue

                distance = math.hypot(
                    row - destination[0],
                    column - destination[1],
                )

                front_delta = abs(distance - radius)
                front = 0.0
                if front_delta <= ring_width:
                    front = 1.0 - front_delta / ring_width

                interior = 0.0
                if distance <= radius and radius > 0.0:
                    interior = max(
                        0.0,
                        1.0 - distance / max(radius, 0.001),
                    ) * 0.95

                intensity = max(front, interior)
                travel = radius / self.MAX_RADIUS

                if travel <= 0.60:
                    fade = 1.0
                else:
                    fade = max(
                        0.0,
                        1.0 - (travel - 0.60) / 0.40,
                    )

                intensity *= fade
                if intensity <= 0.0:
                    continue

                impact = self._impact_colour(
                    distance=distance,
                    radius=max(radius, 0.001),
                    intensity=intensity,
                    meteor_colour=parameters.colour1,
                    impact_colour=parameters.colour2,
                )
                colour = _add(colour, impact)

            canvas.set(
                cell,
                colour,
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="meteor-explosion",
        name="Meteor Explosion",
        description=(
            "A keyboard-reactive meteor streaks from a deterministic outer "
            "entry point toward the pressed key, then detonates into a compact "
            "multi-temperature explosion. Keyboard and mouse reactions are isolated: "
            "keyboard presses never animate the mouse, while mouse buttons trigger a "
            "mouse-only miniature meteor streak, impact flash, and thermal decay."
        ),
        effect_class=MeteorExplosionEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Meteor Colour",
                kind="colour",
                default=(255, 170, 32),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Impact Colour",
                kind="colour",
                default=(255, 48, 0),
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
