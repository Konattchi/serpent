from __future__ import annotations

from serpent_core.effect_sdk import EffectCanvas
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectFrame,
    EffectParameters,
    EffectTarget,
    scale_colour,
)
from serpent_core.patterns import (
    PatternSample,
    get_pattern,
)


class CheckerEffect(Effect):
    definition = EffectDefinition(
        id="checker",
        colours=2,
        animated=False,
        speed=False,
        spatial=True,
        spatial_metric="cells",
        minimum_spatial_positions=2,
        recommended_spatial_positions=4,
    )

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()
        pattern = get_pattern("checker")
        canvas = EffectCanvas(target)

        for row, column in target.active_cells:
            base_colour = pattern.sample(
                PatternSample(
                    row=row,
                    column=column,
                    rows=target.rows,
                    columns=target.columns,
                    x=0.0,
                    y=0.0,
                    elapsed=elapsed,
                ),
                colour1=parameters.colour1,
                colour2=parameters.colour2,
                speed=parameters.speed,
            )

            canvas.set(
                (row, column),
                scale_colour(
                    base_colour,
                    parameters.brightness,
                ),
            )

        return canvas.frame()

from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)

# M7.3: authoritative plugin metadata.
SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="checker",
        name="Checker",
        description="Alternates two colours in a spatial checker pattern.",
        effect_class=CheckerEffect,
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
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
