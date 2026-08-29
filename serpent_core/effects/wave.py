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
from serpent_core.geometry import (
    SPATIAL_DIRECTIONS,
    directional_position,
)


class WaveEffect(Effect):
    definition = EffectDefinition(
        id="wave",
        colours=0,
        animated=True,
        speed=True,
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
                f"Wave direction is not supported: "
                f"{parameters.direction}"
            )

        canvas = EffectCanvas(target)

        for row, column in target.active_cells:
            position = directional_position(
                row,
                column,
                target.rows,
                target.columns,
                parameters.direction,
            )

            base_colour = get_pattern(
                "rainbow"
            ).sample(
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
        id="wave",
        name="Wave",
        description="Moves a spectrum wave along the selected axis.",
        effect_class=WaveEffect,
        parameters=(
            EffectParameterSpec(
                id="speed",
                label="Speed",
                kind="integer",
                default=2,
                minimum=1,
                maximum=10,
            ),
            EffectParameterSpec(
                id="direction",
                label="Direction",
                kind="choice",
                default=WaveEffect.definition.directions[0],
                choices=tuple(WaveEffect.definition.directions),
            ),
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
