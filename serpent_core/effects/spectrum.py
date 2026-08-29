from __future__ import annotations

import colorsys

from serpent_core.effects.base import (
    Colour,
    EffectDefinition,
    EffectParameters,
    UniformEffect,
    scale_colour,
)


class SpectrumEffect(UniformEffect):
    definition = EffectDefinition(
        id="spectrum",
        colours=0,
        animated=True,
        speed=True,
        spatial=False,
    )

    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        hue = (
            elapsed
            * 0.125
            * (parameters.speed / 2.0)
        ) % 1.0

        red, green, blue = colorsys.hsv_to_rgb(
            hue,
            1.0,
            1.0,
        )

        return scale_colour(
            (
                round(red * 255),
                round(green * 255),
                round(blue * 255),
            ),
            parameters.brightness,
        )

from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)

# M7.3: authoritative plugin metadata.
SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="spectrum",
        name="Spectrum",
        description="Cycles smoothly through the RGB spectrum.",
        effect_class=SpectrumEffect,
        parameters=(
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
