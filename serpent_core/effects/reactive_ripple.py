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
class _Ripple:
    row: int
    column: int
    started_at: float


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_channel(value: float) -> int:
    return max(0, min(255, round(value)))


def _triangle(distance_from_peak: float, half_width: float) -> float:
    if half_width <= 0:
        return 0.0
    return _clamp01(1.0 - abs(distance_from_peak) / half_width)


def _mix(a, b, amount):
    amount = _clamp01(amount)
    return tuple(
        _clamp_channel(x + (y - x) * amount)
        for x, y in zip(a, b)
    )


class ReactiveRippleEffect(Effect):
    definition = EffectDefinition(
        id="reactive-ripple",
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
        self._ripples: list[_Ripple] = []
        self._mouse_pulses: list[float] = []

    @property
    def active_ripple_count(self) -> int:
        return len(self._ripples)

    def handle_event(self, event: EffectEvent) -> None:
        if event_matches(
            event,
            kind="mouse-press",
            source_prefix="",
        ):
            self._mouse_pulses.append(event_timestamp(event))
            return

        if not event_matches(
            event,
            kind="key-press",
            source_prefix="keyboard:",
        ):
            return

        cell = event_cell(event)
        if cell is None:
            return

        self._ripples.append(
            _Ripple(
                row=cell[0],
                column=cell[1],
                started_at=event_timestamp(event),
            )
        )

    def _radius_per_second(self, speed: int) -> float:
        return 2.5 + max(1, min(10, speed)) * 1.5

    def _wave_geometry(self, speed: int) -> tuple[float, float]:
        clamped = max(1, min(10, speed))
        return 1.10, 0.78 - (clamped - 1) * 0.012

    @staticmethod
    def _max_radius_from_origin(
        row: int,
        column: int,
        rows: int,
        columns: int,
    ) -> float:
        corners = (
            (0, 0),
            (0, columns - 1),
            (rows - 1, 0),
            (rows - 1, columns - 1),
        )
        return max(
            math.hypot(row - cr, column - cc)
            for cr, cc in corners
        )

    def _render_mouse(self, elapsed, parameters, target):
        duration = 0.62
        self._mouse_pulses = [
            started
            for started in self._mouse_pulses
            if 0.0 <= elapsed - started <= duration
        ]

        low = parameters.colour1
        crest = parameters.colour2
        pixels = []

        for row in range(target.rows):
            rendered = []
            for column in range(target.columns):
                red = green = blue = 0.0

                for started in self._mouse_pulses:
                    age = elapsed - started
                    phase = age / duration

                    # Temporal A -> B -> A wave. Slight column delay gives
                    # the two Naga lighting regions a travelling-wave feel.
                    local_phase = phase - column * 0.10
                    if not 0.0 <= local_phase <= 1.0:
                        continue

                    if local_phase < 0.5:
                        colour = _mix(
                            low,
                            crest,
                            local_phase / 0.5,
                        )
                        envelope = local_phase / 0.5
                    else:
                        colour = _mix(
                            crest,
                            low,
                            (local_phase - 0.5) / 0.5,
                        )
                        envelope = (1.0 - local_phase) / 0.5

                    envelope = max(0.20, envelope)

                    red += colour[0] * envelope
                    green += colour[1] * envelope
                    blue += colour[2] * envelope

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
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        speed = max(1, min(10, int(parameters.speed)))
        radius_rate = self._radius_per_second(speed)
        side_offset, half_width = self._wave_geometry(speed)
        wave_extent = side_offset + half_width

        live = []
        for ripple in self._ripples:
            age = elapsed - ripple.started_at
            if age < 0.0:
                continue

            farthest = self._max_radius_from_origin(
                ripple.row,
                ripple.column,
                target.rows,
                target.columns,
            )
            radius = age * radius_rate

            if radius <= farthest + wave_extent:
                live.append(ripple)

        self._ripples = live
        low_colour = parameters.colour1
        crest_colour = parameters.colour2

        canvas = EffectCanvas(
            target,
            background=(0, 0, 0),
        )

        for row, column in target.active_cells:
            red = green = blue = 0.0

            for ripple in self._ripples:
                age = elapsed - ripple.started_at
                if age < 0.0:
                    continue

                radius = age * radius_rate
                distance = math.hypot(
                    row - ripple.row,
                    column - ripple.column,
                )
                signed_delta = distance - radius

                inner_low = _triangle(
                    signed_delta + side_offset,
                    half_width,
                )
                crest = _triangle(
                    signed_delta,
                    half_width,
                )
                outer_low = _triangle(
                    signed_delta - side_offset,
                    half_width,
                )
                low = max(inner_low, outer_low)

                farthest = self._max_radius_from_origin(
                    ripple.row,
                    ripple.column,
                    target.rows,
                    target.columns,
                )
                travel = radius / max(0.001, farthest)
                travel_fade = max(
                    0.62,
                    1.0 - max(0.0, travel - 0.45) * 0.34,
                )

                red += (
                    low_colour[0] * low * 0.58
                    + crest_colour[0] * crest
                ) * travel_fade
                green += (
                    low_colour[1] * low * 0.58
                    + crest_colour[1] * crest
                ) * travel_fade
                blue += (
                    low_colour[2] * low * 0.58
                    + crest_colour[2] * crest
                ) * travel_fade

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
        id="reactive-ripple",
        name="Reactive Ripple",
        description=(
            "Keyboard presses launch A-B-A spatial waves. Mouse presses "
            "launch a device-local A-B-A pulse across the Naga lighting."
        ),
        effect_class=ReactiveRippleEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Wave Colour",
                kind="colour",
                default=(0, 80, 180),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Crest Colour",
                kind="colour",
                default=(120, 235, 255),
            ),
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

