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


def _mix(a: int, b: int, amount: float) -> int:
    return round(a + (b - a) * amount)


class AuroraPulseEffect(Effect):
    """A visible temporal pulse between two colours."""

    definition = EffectDefinition(
        id="aurora-pulse",
        colours=2,
        animated=True,
        speed=True,
        spatial=False,
    )

    def render(self, elapsed, parameters, target):
        target.validate()

        # Speed 1..10 maps to increasingly fast colour oscillation.
        speed = max(1, int(parameters.speed))
        frequency_hz = 0.10 + (speed - 1) * 0.08

        # Smooth 0..1..0 cycle.
        phase = (
            math.sin(elapsed * math.tau * frequency_hz) + 1.0
        ) / 2.0

        colour = tuple(
            _mix(first, second, phase)
            for first, second in zip(
                parameters.colour1,
                parameters.colour2,
            )
        )

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


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="aurora-pulse",
        name="Aurora Pulse",
        description=(
            "Smoothly pulses the whole synchronized target between "
            "two selected colours."
        ),
        effect_class=AuroraPulseEffect,
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Primary colour",
                kind="colour",
                default=(0, 80, 255),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Secondary colour",
                kind="colour",
                default=(255, 0, 180),
            ),
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
