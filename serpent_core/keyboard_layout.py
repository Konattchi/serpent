from __future__ import annotations

from dataclasses import dataclass

from serpent_core.effects.base import EffectEvent
from serpent_core.input_events import LinuxKeyEvent


@dataclass(frozen=True)
class KeyMatrixPosition:
    event_code: int
    key_name: str
    row: int
    column: int


class KeyboardLayoutError(RuntimeError):
    pass


def _openrazer_maps() -> tuple[dict[int, str], dict[str, tuple[int, int]]]:
    try:
        from openrazer_daemon.keyboard import EVENT_MAPPING, KEY_MAPPING
    except Exception as exc:
        raise KeyboardLayoutError(
            "OpenRazer keyboard mapping tables are unavailable."
        ) from exc
    return EVENT_MAPPING, KEY_MAPPING


def position_for_event_code(
    event_code: int,
    *,
    rows: int,
    columns: int,
    row_offset: int = 0,
    column_offset: int = 0,
) -> KeyMatrixPosition | None:
    if rows < 1 or columns < 1:
        raise ValueError("rows and columns must both be positive")

    event_map, key_map = _openrazer_maps()
    key_name = event_map.get(int(event_code))
    if key_name is None:
        return None

    position = key_map.get(key_name)
    if position is None:
        return None

    row = int(position[0]) + int(row_offset)
    column = int(position[1]) + int(column_offset)

    if row < 0 or row >= rows or column < 0 or column >= columns:
        raise KeyboardLayoutError(
            f"OpenRazer mapped event code {event_code} ({key_name}) "
            f"to transformed out-of-range matrix cell ({row}, {column}) "
            f"for {rows}x{columns}."
        )

    return KeyMatrixPosition(
        event_code=int(event_code),
        key_name=key_name,
        row=row,
        column=column,
    )


def effect_event_from_linux_key(
    event: LinuxKeyEvent,
    *,
    rows: int,
    columns: int,
    row_offset: int = 0,
    column_offset: int = 0,
) -> EffectEvent | None:
    position = position_for_event_code(
        event.code,
        rows=rows,
        columns=columns,
        row_offset=row_offset,
        column_offset=column_offset,
    )
    if position is None:
        return None

    if event.value == 1:
        kind = "key-press"
    elif event.value == 0:
        kind = "key-release"
    elif event.value == 2:
        kind = "key-repeat"
    else:
        return None

    return EffectEvent(
        kind=kind,
        timestamp=event.timestamp,
        source=event.source,
        code=event.name,
        value=event.value,
        row=position.row,
        column=position.column,
    )


__all__ = [
    "KeyboardLayoutError",
    "KeyMatrixPosition",
    "effect_event_from_linux_key",
    "position_for_event_code",
]
