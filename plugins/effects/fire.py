from __future__ import annotations

import math

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectFrame,
)
from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _mix(a: int, b: int, amount: float) -> int:
    amount = _clamp01(amount)
    return round(a + (b - a) * amount)


def _palette(heat: float) -> tuple[int, int, int]:
    """Classic fire: black -> red -> orange -> yellow -> pale yellow."""
    heat = _clamp01(heat)

    stops = (
        (0.00, (0, 0, 0)),
        (0.18, (75, 0, 0)),
        (0.38, (210, 18, 0)),
        (0.62, (255, 95, 0)),
        (0.82, (255, 205, 20)),
        (1.00, (255, 248, 155)),
    )

    for index in range(len(stops) - 1):
        left_pos, left = stops[index]
        right_pos, right = stops[index + 1]

        if heat <= right_pos:
            amount = (
                (heat - left_pos)
                / max(0.000001, right_pos - left_pos)
            )
            return tuple(
                _mix(a, b, amount)
                for a, b in zip(left, right)
            )

    return stops[-1][1]


def _noise(column: int, time_value: float) -> float:
    """Cheap smooth pseudo-noise with neighbor coherence."""
    a = math.sin(time_value * 1.17 + column * 0.71)
    b = math.sin(time_value * 1.91 + column * 1.37 + 1.4)
    c = math.sin(time_value * 0.63 + column * 0.29 + 2.8)
    return (a * 0.52 + b * 0.31 + c * 0.17 + 1.0) / 2.0


class FireEffect(Effect):
    definition = EffectDefinition(
        id="fire",
        colours=0,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="temporal",
    )

    def _temporal_glow(
        self,
        elapsed: float,
        speed: int,
        target,
    ) -> EffectFrame:
        """Low-resolution fallback: flickering firelight instead of fake flames."""
        t = elapsed * (0.70 + speed * 0.22)
        flicker = (
            0.58
            + 0.18 * math.sin(t * 2.1)
            + 0.11 * math.sin(t * 3.7 + 1.2)
            + 0.06 * math.sin(t * 7.1 + 0.4)
        )
        colour = _palette(_clamp01(flicker))

        frame = EffectFrame(
            rows=target.rows,
            columns=target.columns,
            pixels=tuple(
                tuple(
                    colour
                    for _column in range(target.columns)
                )
                for _row in range(target.rows)
            ),
        )
        frame.validate()
        return frame

    def render(self, elapsed, parameters, target):
        target.validate()

        speed = max(1, min(10, int(parameters.speed)))

        # A mouse or similarly tiny target cannot show convincing flame
        # columns. Render synchronized warm flicker instead.
        if target.rows < 3 or target.columns < 3:
            return self._temporal_glow(
                elapsed,
                speed,
                target,
            )

        t = elapsed * (0.55 + speed * 0.16)
        rows = target.rows
        columns = target.columns

        pixels: list[tuple[tuple[int, int, int], ...]] = []

        for row in range(rows):
            row_pixels: list[tuple[int, int, int]] = []

            # 0 at the bottom, 1 at the top.
            height = (
                (rows - 1 - row)
                / max(1, rows - 1)
            )

            for column in range(columns):
                local = _noise(column, t)

                # Neighbor influence keeps adjacent columns feeling like one
                # flame front instead of an audio equalizer.
                left = _noise(max(0, column - 1), t + 0.15)
                right = _noise(
                    min(columns - 1, column + 1),
                    t - 0.11,
                )
                coherent = (
                    local * 0.62
                    + left * 0.19
                    + right * 0.19
                )

                # Typical flame height occupies 45-95% of the target.
                flame_top = 0.45 + coherent * 0.50

                # Narrow tongues occasionally reach above the main body.
                tongue = max(
                    0.0,
                    math.sin(
                        t * 2.8
                        + column * 2.21
                    ),
                )
                flame_top += tongue * 0.10

                if height > flame_top:
                    heat = 0.0
                else:
                    depth = (
                        flame_top - height
                    ) / max(0.001, flame_top)

                    # Bottom stays hot. Tips become redder/dimmer and dance.
                    heat = (
                        0.30
                        + depth * 0.68
                        + 0.08
                        * math.sin(
                            t * 4.3
                            + column * 1.13
                            + row * 0.67
                        )
                    )

                    # Carve small transient dark pockets into the upper half.
                    if height > 0.35:
                        pocket = math.sin(
                            t * 5.9
                            + column * 1.79
                            + row * 2.17
                        )
                        if pocket > 0.82:
                            heat *= 0.45

                row_pixels.append(
                    _palette(_clamp01(heat))
                )

            pixels.append(tuple(row_pixels))

        frame = EffectFrame(
            rows=rows,
            columns=columns,
            pixels=tuple(pixels),
        )
        frame.validate()
        return frame


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="fire",
        name="Fire",
        description=(
            "Animated flame columns with a classic hot-yellow, orange, "
            "and red palette. Low-resolution targets receive synchronized "
            "firelight flicker."
        ),
        effect_class=FireEffect,
        parameters=(
            EffectParameterSpec(
                id="speed",
                label="Speed",
                kind="integer",
                default=4,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
