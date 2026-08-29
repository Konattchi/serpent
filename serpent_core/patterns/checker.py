from __future__ import annotations

from serpent_core.effects.base import Colour
from serpent_core.patterns.base import (
    Pattern,
    PatternSample,
)


class CheckerPattern(Pattern):
    id = "checker"

    def sample(
        self,
        point: PatternSample,
        *,
        colour1: Colour,
        colour2: Colour,
        speed: int,
    ) -> Colour:
        del speed

        return (
            colour1
            if (point.row + point.column) % 2 == 0
            else colour2
        )
