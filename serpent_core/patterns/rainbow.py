from __future__ import annotations

import colorsys

from serpent_core.effects.base import Colour
from serpent_core.patterns.base import (
    Pattern,
    PatternSample,
)


class RainbowPattern(Pattern):
    id = "rainbow"

    def sample(
        self,
        point: PatternSample,
        *,
        colour1: Colour,
        colour2: Colour,
        speed: int,
    ) -> Colour:
        del colour1, colour2

        hue = (
            point.elapsed
            * 0.125
            * (speed / 2.0)
            + point.x
        ) % 1.0

        red, green, blue = colorsys.hsv_to_rgb(
            hue,
            1.0,
            1.0,
        )

        return (
            round(red * 255),
            round(green * 255),
            round(blue * 255),
        )
