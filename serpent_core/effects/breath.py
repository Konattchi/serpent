from __future__ import annotations

import math

from serpent_core.effects.base import (
    Colour,
    EffectDefinition,
    EffectParameters,
    UniformEffect,
    scale_colour,
)


class BreathSingleEffect(UniformEffect):
    definition = EffectDefinition(
        id="breath-single",
        colours=1,
        animated=True,
        speed=True,
        spatial=False,
    )

    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        phase = (
            elapsed
            * 2.7
            * (parameters.speed / 2.0)
        )
        pulse = (math.sin(phase) + 1.0) / 2.0

        return scale_colour(
            parameters.colour1,
            parameters.brightness * pulse,
        )


class BreathDualEffect(UniformEffect):
    definition = EffectDefinition(
        id="breath-dual",
        colours=2,
        animated=True,
        speed=True,
        spatial=False,
    )

    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        phase = (
            elapsed
            * 1.7
            * (parameters.speed / 2.0)
        ) % (2.0 * math.pi)

        if phase < math.pi:
            colour = parameters.colour1
            pulse = math.sin(phase)
        else:
            colour = parameters.colour2
            pulse = math.sin(phase - math.pi)

        return scale_colour(
            colour,
            parameters.brightness * max(0.0, pulse),
        )

from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)

# M7.3: authoritative plugin metadata.
SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="breath-single",
        name="Breath Single",
        description="Pulses one colour in a breathing animation.",
        effect_class=BreathSingleEffect,
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Primary colour",
                kind="colour",
                default=(255, 255, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Speed",
                kind="integer",
                default=2,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
    EffectPluginSpec(
        id="breath-dual",
        name="Breath Dual",
        description="Breathes between two selected colours.",
        effect_class=BreathDualEffect,
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Primary colour",
                kind="colour",
                default=(255, 255, 255),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Secondary colour",
                kind="colour",
                default=(0, 0, 0),
            ),
            EffectParameterSpec(
                id="speed",
                label="Speed",
                kind="integer",
                default=2,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
