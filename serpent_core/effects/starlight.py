from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas

import math

from serpent_core.effects.base import (
    Colour,
    Effect,
    EffectDefinition,
    EffectFrame,
    EffectParameters,
    EffectTarget,
    scale_colour,
)


def cell_hash(
    row: int,
    column: int,
    salt: int = 0,
) -> int:
    """Small deterministic integer hash for stable per-cell timing."""

    value = (
        (row + 1) * 0x45D9F3B
        ^ (column + 1) * 0x119DE1F3
        ^ (salt + 1) * 0x3449D
    )
    value ^= value >> 16
    value *= 0x45D9F3B
    value ^= value >> 16
    return value & 0xFFFFFFFF


def unit_hash(
    row: int,
    column: int,
    salt: int = 0,
) -> float:
    return cell_hash(row, column, salt) / 0xFFFFFFFF


def mix_colour(
    first: Colour,
    second: Colour,
    amount: float,
) -> Colour:
    amount = max(0.0, min(1.0, amount))

    return tuple(
        round(
            first_component
            + (second_component - first_component) * amount
        )
        for first_component, second_component in zip(first, second)
    )  # type: ignore[return-value]


class StarlightEffect(Effect):
    definition = EffectDefinition(
        id="starlight",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        spatial_metric="cells",
        minimum_spatial_positions=1,
        recommended_spatial_positions=2,
    )

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()
        speed_factor = max(0.25, parameters.speed / 2.0)
        canvas = EffectCanvas(target)

        for row, column in target.active_cells:
            # Each cell receives a stable period, phase offset and
            # colour blend derived only from its identity.
            period = (
                2.8
                + unit_hash(row, column, 1) * 2.2
            ) / speed_factor

            phase_offset = (
                unit_hash(row, column, 2)
                * period
            )

            phase = (
                (elapsed + phase_offset)
                % period
            ) / period

            # A short smooth twinkle followed by darkness.
            if phase < 0.42:
                local = phase / 0.42
                intensity = math.sin(math.pi * local) ** 2
            else:
                intensity = 0.0

            colour = mix_colour(
                parameters.colour1,
                parameters.colour2,
                unit_hash(row, column, 3),
            )

            canvas.set(
                (row, column),
                scale_colour(
                    colour,
                    parameters.brightness * intensity,
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
        id="starlight",
        name="Starlight",
        description="Twinkles selected colours across spatial cells.",
        effect_class=StarlightEffect,
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
