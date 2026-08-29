from __future__ import annotations

from serpent_core.effects.base import (
    Colour,
    EffectDefinition,
    EffectParameters,
    UniformEffect,
    scale_colour,
)


class OffEffect(UniformEffect):
    definition = EffectDefinition(
        id="off",
        colours=0,
        animated=False,
        speed=False,
        spatial=False,
    )

    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        del elapsed, parameters
        return 0, 0, 0


class StaticEffect(UniformEffect):
    definition = EffectDefinition(
        id="static",
        colours=1,
        animated=False,
        speed=False,
        spatial=False,
    )

    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        del elapsed
        return scale_colour(
            parameters.colour1,
            parameters.brightness,
        )

from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)

# M7.3: authoritative plugin metadata.
SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="off",
        name="Off",
        description="Turns all active lighting cells off.",
        effect_class=OffEffect,
        parameters=(),
    ),
    EffectPluginSpec(
        id="static",
        name="Static",
        description="Displays one constant colour across the target.",
        effect_class=StaticEffect,
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Colour",
                kind="colour",
                default=(255, 255, 255),
            ),
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
