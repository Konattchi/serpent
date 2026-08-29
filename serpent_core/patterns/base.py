from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from serpent_core.effects.base import Colour


@dataclass(frozen=True)
class PatternSample:
    row: int
    column: int
    rows: int
    columns: int
    x: float
    y: float
    elapsed: float


class Pattern(ABC):
    """A device-independent 2D colour source."""

    id: str

    @abstractmethod
    def sample(
        self,
        point: PatternSample,
        *,
        colour1: Colour,
        colour2: Colour,
        speed: int,
    ) -> Colour:
        raise NotImplementedError
