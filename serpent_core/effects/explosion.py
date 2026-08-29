from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas

from dataclasses import dataclass
import math

from serpent_core.effect_sdk import event_cell, event_matches, event_timestamp
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
)
from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)


@dataclass(frozen=True)
class _Blast:
    row: int
    column: int
    started_at: float


def _clamp_channel(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(
        _clamp_channel(x + (y - x) * amount)
        for x, y in zip(a, b)
    )


class ExplosionEffect(Effect):
    """Short-range multi-temperature reactive explosion."""

    definition = EffectDefinition(
        id="explosion",
        colours=0,
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
        self._blasts: list[_Blast] = []
        self._mouse_blasts: list[float] = []

    @property
    def active_blast_count(self) -> int:
        return len(self._blasts)

    def handle_event(self, event: EffectEvent) -> None:
        if event_matches(
            event,
            kind="mouse-press",
            source_prefix="",
        ):
            self._mouse_blasts.append(event_timestamp(event))
            return

        if event_matches(
            event,
            kind="key-press",
            source_prefix="keyboard:",
        ):
            cell = event_cell(event)
            if cell is None:
                return

            self._blasts.append(
                _Blast(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                )
            )

    def _radius_per_second(self, speed: int) -> float:
        return 5.0 + max(1, min(10, int(speed))) * 1.3

    def _ring_width(self, speed: int) -> float:
        return 1.55 - (max(1, min(10, int(speed))) - 1) * 0.025

    @staticmethod
    def _heat_colour(
        *,
        radial_position: float,
        radius: float,
        intensity: float,
    ) -> tuple[int, int, int]:
        """White-hot centre -> yellow -> orange -> red outer blast.

        radial_position is a cell's distance from the blast origin.
        radius is the current shockwave radius.

        The colour is spatial, not merely temporal: one frame can show
        several heat bands at once inside the same local explosion.
        """

        if radius <= 0.001:
            heat = 0.0
        else:
            heat = radial_position / radius

        heat = max(0.0, min(1.35, heat))

        white_hot = (255, 250, 220)
        yellow = (255, 210, 30)
        orange = (255, 92, 0)
        red = (190, 16, 0)

        if heat < 0.45:
            colour = _mix(
                white_hot,
                yellow,
                heat / 0.45,
            )
        elif heat < 0.78:
            colour = _mix(
                yellow,
                orange,
                (heat - 0.45) / 0.33,
            )
        else:
            colour = _mix(
                orange,
                red,
                min(1.0, (heat - 0.78) / 0.40),
            )

        return tuple(
            _clamp_channel(channel * intensity)
            for channel in colour
        )

    def _render_mouse(self, elapsed, target) -> EffectFrame:
        # Keep the approved mouse animation untouched.
        duration = 0.52
        self._mouse_blasts = [
            started
            for started in self._mouse_blasts
            if 0.0 <= elapsed - started <= duration
        ]

        pixels = []
        for row in range(target.rows):
            rendered = []
            for column in range(target.columns):
                red = green = blue = 0.0

                for started in self._mouse_blasts:
                    phase = (elapsed - started) / duration
                    local_phase = phase - column * 0.10

                    if not 0.0 <= local_phase <= 1.0:
                        continue

                    if local_phase < 0.16:
                        colour = (255, 245, 180)
                        strength = local_phase / 0.16
                    elif local_phase < 0.48:
                        colour = (255, 120, 0)
                        strength = (
                            1.0
                            - (local_phase - 0.16) / 0.32 * 0.35
                        )
                    else:
                        colour = (180, 18, 0)
                        strength = (1.0 - local_phase) / 0.52

                    strength = max(0.0, strength)
                    red += colour[0] * strength
                    green += colour[1] * strength
                    blue += colour[2] * strength

                rendered.append(
                    (
                        _clamp_channel(red),
                        _clamp_channel(green),
                        _clamp_channel(blue),
                    )
                )
            pixels.append(tuple(rendered))

        frame = EffectFrame(
            rows=target.rows,
            columns=target.columns,
            pixels=tuple(pixels),
        )
        frame.validate()
        return frame

    def render(self, elapsed, parameters, target):
        target.validate()

        if target.rows < 3 or target.columns < 3:
            return self._render_mouse(elapsed, target)

        speed = max(1, min(10, int(parameters.speed)))
        radius_rate = self._radius_per_second(speed)
        ring_width = self._ring_width(speed)

        self._blasts = [
            blast
            for blast in self._blasts
            if 0.0 <= elapsed - blast.started_at
            and (elapsed - blast.started_at) * radius_rate
            <= self.MAX_RADIUS + ring_width
        ]

        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )

        for row, column in target.active_cells:
            red = green = blue = 0.0

            for blast in self._blasts:
                age = elapsed - blast.started_at
                if age < 0.0:
                    continue

                radius = age * radius_rate
                distance = math.hypot(
                    row - blast.row,
                    column - blast.column,
                )

                # Keep the local shock front, but add a hot interior glow
                # so white/yellow/orange/red can coexist within one blast.
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

                # Overall late-radius collapse remains the defining
                # short-range Explosion behavior.
                travel = radius / self.MAX_RADIUS
                if travel <= 0.60:
                    lifetime = 1.0
                else:
                    lifetime = max(
                        0.0,
                        1.0 - (travel - 0.60) / 0.40,
                    )

                intensity *= lifetime

                if intensity <= 0.0:
                    continue

                colour = self._heat_colour(
                    radial_position=distance,
                    radius=max(radius, 0.001),
                    intensity=intensity,
                )

                red += colour[0]
                green += colour[1]
                blue += colour[2]

            canvas.set(
                (row, column),
                (
                    _clamp_channel(red),
                    _clamp_channel(green),
                    _clamp_channel(blue),
                ),
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="explosion",
        name="Explosion",
        description=(
            "A short-range 4-5-key blast with a white-hot centre, yellow "
            "transition, orange body, and red outer shockwave. Multiple "
            "explosions coexist; mouse presses use the matching local burst."
        ),
        effect_class=ExplosionEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="speed",
                label="Speed",
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

