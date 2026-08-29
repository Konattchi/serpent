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
from serpent_core.geometry import (
    SPATIAL_DIRECTIONS,
    directional_position,
)
from serpent_core.patterns import (
    PatternSample,
    get_pattern,
)


class GradientEffect(Effect):
    definition = EffectDefinition(
        id="gradient",
        colours=2,
        animated=False,
        speed=False,
        spatial=True,
        directions=SPATIAL_DIRECTIONS,
        spatial_metric="axis",
        minimum_spatial_positions=2,
        recommended_spatial_positions=6,
    )

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if parameters.direction not in SPATIAL_DIRECTIONS:
            raise ValueError(
                f"Gradient direction is not supported: "
                f"{parameters.direction}"
            )

        pattern = get_pattern("gradient")
        canvas = EffectCanvas(target)

        for row, column in target.active_cells:
            position = directional_position(
                row,
                column,
                target.rows,
                target.columns,
                parameters.direction,
            )

            base_colour = pattern.sample(
                PatternSample(
                    row=row,
                    column=column,
                    rows=target.rows,
                    columns=target.columns,
                    x=position,
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
        id="gradient",
        name="Gradient",
        description="Blends two colours across the selected spatial axis.",
        effect_class=GradientEffect,
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
                id="direction",
                label="Direction",
                kind="choice",
                default=GradientEffect.definition.directions[0],
                choices=tuple(GradientEffect.definition.directions),
            ),
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
