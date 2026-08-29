from __future__ import annotations

from dataclasses import dataclass


DIRECTION_LEFT_TO_RIGHT = 1
DIRECTION_RIGHT_TO_LEFT = 2
DIRECTION_TOP_TO_BOTTOM = 3
DIRECTION_BOTTOM_TO_TOP = 4

SPATIAL_DIRECTIONS = (
    DIRECTION_LEFT_TO_RIGHT,
    DIRECTION_RIGHT_TO_LEFT,
    DIRECTION_TOP_TO_BOTTOM,
    DIRECTION_BOTTOM_TO_TOP,
)


def normalize_index(
    index: int,
    size: int,
) -> float:
    """Map an index in an axis to 0.0 .. 1.0."""

    if size <= 1:
        return 0.0

    return max(
        0.0,
        min(1.0, index / float(size - 1)),
    )


def directional_position(
    row: int,
    column: int,
    rows: int,
    columns: int,
    direction: int,
) -> float:
    """Return a normalized position along a requested direction."""

    if direction == DIRECTION_LEFT_TO_RIGHT:
        return normalize_index(column, columns)

    if direction == DIRECTION_RIGHT_TO_LEFT:
        return 1.0 - normalize_index(column, columns)

    if direction == DIRECTION_TOP_TO_BOTTOM:
        return normalize_index(row, rows)

    if direction == DIRECTION_BOTTOM_TO_TOP:
        return 1.0 - normalize_index(row, rows)

    raise ValueError(
        f"Unsupported spatial direction: {direction}"
    )


def spatial_position_count(
    active_cells: tuple[tuple[int, int], ...],
    direction: int,
) -> int:
    """Count distinct usable positions along a spatial direction."""

    if direction in (
        DIRECTION_LEFT_TO_RIGHT,
        DIRECTION_RIGHT_TO_LEFT,
    ):
        return len({
            column
            for _row, column in active_cells
        })

    if direction in (
        DIRECTION_TOP_TO_BOTTOM,
        DIRECTION_BOTTOM_TO_TOP,
    ):
        return len({
            row
            for row, _column in active_cells
        })

    raise ValueError(
        f"Unsupported spatial direction: {direction}"
    )
