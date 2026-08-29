from __future__ import annotations

from serpent_core.effects.base import Colour, clamp_byte
from serpent_core.patterns.base import Pattern, PatternSample


class GradientPattern(Pattern):
    """Linearly interpolate between two colours using the sample x position."""

    id = "gradient"

    def sample(
        self,
        point: PatternSample,
        *,
        colour1: Colour,
        colour2: Colour,
        speed: int,
    ) -> Colour:
        del speed

        position = max(0.0, min(1.0, float(point.x)))

        return (
            clamp_byte(colour1[0] + (colour2[0] - colour1[0]) * position),
            clamp_byte(colour1[1] + (colour2[1] - colour1[1]) * position),
            clamp_byte(colour1[2] + (colour2[2] - colour1[2]) * position),
        )
