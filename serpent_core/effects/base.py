from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


Colour = tuple[int, int, int]
Cell = tuple[int, int]

DEGRADE_SPATIAL = "spatial"
DEGRADE_UNIFORM = "uniform"
DEGRADE_TEMPORAL = "temporal"

DEGRADATION_POLICIES = (
    DEGRADE_SPATIAL,
    DEGRADE_UNIFORM,
    DEGRADE_TEMPORAL,
)


@dataclass(frozen=True)
class EffectDefinition:
    id: str
    colours: int
    animated: bool
    speed: bool
    spatial: bool
    directions: tuple[int, ...] = ()
    spatial_metric: str = "none"
    minimum_spatial_positions: int = 1
    recommended_spatial_positions: int = 1
    degradation_policy: str = "spatial"


@dataclass(frozen=True)
class EffectSuitability:
    level: str
    spatial_positions: int
    minimum_positions: int
    recommended_positions: int

    @property
    def full(self) -> bool:
        return self.level == "full"

    @property
    def limited(self) -> bool:
        return self.level == "limited"

    @property
    def uniform(self) -> bool:
        return self.level == "uniform"


@dataclass(frozen=True)
class EffectEvent:
    """Presentation-neutral event delivered to an active effect."""

    kind: str
    timestamp: float
    source: str = ""
    code: str = ""
    value: int = 0
    row: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class EffectParameters:
    brightness: float = 100.0
    colour1: Colour = (255, 255, 255)
    colour2: Colour = (0, 0, 0)
    speed: int = 2
    direction: int = 1


@dataclass(frozen=True)
class EffectTarget:
    rows: int
    columns: int
    active_cells: tuple[Cell, ...]
    device_class: str | None = None

    def validate(self) -> None:
        if self.rows < 1 or self.columns < 1:
            raise ValueError(
                "Effect target rows and columns must be at least 1."
            )

        if (
            self.device_class is not None
            and (
                not isinstance(self.device_class, str)
                or not self.device_class.strip()
            )
        ):
            raise ValueError(
                "Effect target device_class must be a non-empty "
                "string or None."
            )

        seen: set[Cell] = set()

        for row, column in self.active_cells:
            if (
                row < 0
                or row >= self.rows
                or column < 0
                or column >= self.columns
            ):
                raise ValueError(
                    f"Effect target cell ({row}, {column}) "
                    "is outside the target bounds."
                )

            if (row, column) in seen:
                raise ValueError(
                    f"Effect target contains duplicate cell "
                    f"({row}, {column})."
                )

            seen.add((row, column))

    @classmethod
    def full(
        cls,
        rows: int,
        columns: int,
    ) -> "EffectTarget":
        return cls(
            rows=rows,
            columns=columns,
            active_cells=tuple(
                (row, column)
                for row in range(rows)
                for column in range(columns)
            ),
        )


@dataclass(frozen=True)
class EffectFrame:
    rows: int
    columns: int
    pixels: tuple[tuple[Colour, ...], ...]

    def validate(self) -> None:
        if len(self.pixels) != self.rows:
            raise ValueError(
                "Effect frame row count does not match metadata."
            )

        for row in self.pixels:
            if len(row) != self.columns:
                raise ValueError(
                    "Effect frame column count does not match metadata."
                )

    def colour_at(
        self,
        row: int,
        column: int,
    ) -> Colour:
        return self.pixels[row][column]


class Effect(ABC):
    definition: EffectDefinition

    def handle_event(self, event: EffectEvent) -> None:
        """Receive an optional runtime event.

        Non-reactive effects intentionally inherit this no-op implementation.
        """
        return None

    @abstractmethod
    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        """Render a complete frame for the requested target."""


class UniformEffect(Effect):
    """Base class for effects that use one colour for all active cells."""

    @abstractmethod
    def render_colour(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> Colour:
        raise NotImplementedError

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()
        colour = self.render_colour(
            elapsed,
            parameters,
        )
        active = set(target.active_cells)

        pixels = tuple(
            tuple(
                colour
                if (row, column) in active
                else (0, 0, 0)
                for column in range(target.columns)
            )
            for row in range(target.rows)
        )

        frame = EffectFrame(
            rows=target.rows,
            columns=target.columns,
            pixels=pixels,
        )
        frame.validate()
        return frame


def clamp_byte(value: int | float) -> int:
    return max(0, min(255, round(float(value))))


def scale_colour(
    colour: Colour,
    brightness: float,
) -> Colour:
    factor = (
        max(0.0, min(100.0, float(brightness)))
        / 100.0
    )

    return tuple(
        clamp_byte(component * factor)
        for component in colour
    )  # type: ignore[return-value]
