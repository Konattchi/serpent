from __future__ import annotations

from serpent_core.effect_sdk import EffectCanvas
from serpent_core.effects.base import (
    DEGRADE_TEMPORAL,
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
    spatial_position_count,
)
from serpent_core.patterns import (
    PatternSample,
    get_pattern,
)


def triangle_wave(value: float) -> float:
    phase = value % 1.0
    return 1.0 - abs(2.0 * phase - 1.0)


class MovingBandsEffect(Effect):
    definition = EffectDefinition(
        id="moving-bands",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        directions=SPATIAL_DIRECTIONS,
        spatial_metric="axis",
        minimum_spatial_positions=2,
        recommended_spatial_positions=6,
        degradation_policy=DEGRADE_TEMPORAL,
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
                "Moving Bands direction is not supported: "
                f"{parameters.direction}"
            )

        pattern = get_pattern("gradient")
        time_phase = elapsed * 0.20 * (parameters.speed / 2.0)

        positions = spatial_position_count(
            target.active_cells,
            parameters.direction,
        )
        collapse_to_temporal = (
            positions < self.definition.recommended_spatial_positions
        )

        canvas = EffectCanvas(target)

        for row, column in target.active_cells:
            if collapse_to_temporal:
                position = 0.0
            else:
                position = directional_position(
                    row,
                    column,
                    target.rows,
                    target.columns,
                    parameters.direction,
                )

            gradient_position = triangle_wave(
                position * 2.0 - time_phase
            )

            base_colour = pattern.sample(
                PatternSample(
                    row=row,
                    column=column,
                    rows=target.rows,
                    columns=target.columns,
                    x=gradient_position,
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
        id="moving-bands",
        name="Moving Bands",
        description="Moves alternating colour bands across the selected axis.",
        effect_class=MovingBandsEffect,
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
            EffectParameterSpec(
                id="direction",
                label="Direction",
                kind="choice",
                default=MovingBandsEffect.definition.directions[0],
                choices=tuple(MovingBandsEffect.definition.directions),
            ),
        ),
    ),
)

for _plugin in SERPENT_EFFECT_PLUGINS:
    _plugin.validate()
