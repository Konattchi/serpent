from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas

import math

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour = tuple[int, int, int]
Cell = tuple[int, int]


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _scale(colour: Colour, amount: float) -> Colour:
    amount = max(0.0, float(amount))
    return tuple(_clamp(channel * amount) for channel in colour)


class PacManPatrolEffect(Effect):
    """Autonomous 4x4 Pac-Man patrol with synchronized mouse waka pulse."""

    definition = EffectDefinition(
        id="pacman-patrol",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=6,
        recommended_spatial_positions=12,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    SPRITE_WIDTH = 6
    SPRITE_HEIGHT = 6

    # 4x4 silhouettes. The open frame deliberately sacrifices a few pixels
    # on the facing side so the mouth motion remains obvious at low resolution.
    OPEN_RIGHT = (
        "011110",
        "111111",
        "111100",
        "111000",
        "111111",
        "011110",
    )
    CLOSED_RIGHT = (
        "011110",
        "111111",
        "111111",
        "111111",
        "111111",
        "011110",
    )

    OPEN_LEFT = tuple(row[::-1] for row in OPEN_RIGHT)
    CLOSED_LEFT = tuple(row[::-1] for row in CLOSED_RIGHT)

    @staticmethod
    def _movement_period(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # Columns advanced per second via phase accumulator.
        return 0.34 - (speed - 1) * 0.022

    @staticmethod
    def _mouth_period(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.24 - (speed - 1) * 0.012

    @classmethod
    def _mouth_closed(cls, elapsed: float, speed: int) -> bool:
        period = max(0.06, cls._mouth_period(speed))
        return int(max(0.0, elapsed) / period) % 2 == 1

    @classmethod
    def _sprite_for(cls, direction: int, closed: bool) -> tuple[str, ...]:
        if direction >= 0:
            return cls.CLOSED_RIGHT if closed else cls.OPEN_RIGHT
        return cls.CLOSED_LEFT if closed else cls.OPEN_LEFT

    @classmethod
    def _patrol_state(
        cls,
        elapsed: float,
        speed: int,
        columns: int,
    ) -> tuple[int, int]:
        """Return (left_column, direction), bouncing just beyond the edges."""
        if columns <= 0:
            return (0, 1)

        period = max(0.05, cls._movement_period(speed))
        step = int(max(0.0, elapsed) / period)

        # Pac-Man fully exits before respawning from the opposite side.
        left_exit = -cls.SPRITE_WIDTH
        right_exit = columns
        travel = max(1, right_exit - left_exit)

        cycle = travel * 2
        phase = step % cycle

        if phase < travel:
            return (left_exit + phase, 1)

        return (right_exit - (phase - travel), -1)

    @staticmethod
    def _vertical_top(target: EffectTarget) -> int:
        # Full-height on a 6-row keyboard; centered on taller fixtures.
        if target.rows <= PacManPatrolEffect.SPRITE_HEIGHT:
            return 0
        return max(
            0,
            (target.rows - PacManPatrolEffect.SPRITE_HEIGHT) // 2,
        )

    @classmethod
    def _sprite_cells(
        cls,
        target: EffectTarget,
        elapsed: float,
        speed: int,
    ) -> tuple[Cell, ...]:
        left, direction = cls._patrol_state(
            elapsed,
            speed,
            target.columns,
        )
        closed = cls._mouth_closed(elapsed, speed)
        sprite = cls._sprite_for(direction, closed)
        top = cls._vertical_top(target)
        active = set(target.active_cells)

        cells: list[Cell] = []

        for sprite_row, pattern in enumerate(sprite):
            for sprite_column, value in enumerate(pattern):
                if value != "1":
                    continue

                row = top + sprite_row
                column = left + sprite_column

                if not (
                    0 <= row < target.rows
                    and 0 <= column < target.columns
                ):
                    continue

                cell = (row, column)
                if cell in active:
                    cells.append(cell)

        return tuple(cells)

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        closed = self._mouth_closed(elapsed, parameters.speed)

        # User-requested niche:
        # mouth CLOSED => Pac-Man colour
        # mouth OPEN   => Background colour
        current = (
            parameters.colour2
            if closed
            else parameters.colour1
        )

        return EffectCanvas(
            target,
            background=current,
        ).frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if len(target.active_cells) < 4 or target.rows < 2:
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        sprite_cells = set(
            self._sprite_cells(
                target,
                elapsed,
                parameters.speed,
            )
        )

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell in sprite_cells:
            canvas.set(
                cell,
                parameters.colour2,
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="pacman-patrol",
        name="Pac-Man Patrol",
        description=(
            "A single autonomous 6x6 Pac-Man endlessly patrols the keyboard, "
            "opening and closing his mouth as he moves and reversing direction "
            "after fully exiting an edge. The mouse follows the same waka cycle: "
            "mouth open uses Background Colour; mouth closed uses Pac-Man Colour."
        ),
        effect_class=PacManPatrolEffect,
        input_capabilities=(),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(8, 8, 14),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Pac-Man Colour",
                kind="colour",
                default=(255, 220, 0),
            ),
            EffectParameterSpec(
                id="speed",
                label="Patrol Speed",
                kind="integer",
                default=5,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
