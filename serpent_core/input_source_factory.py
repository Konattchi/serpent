from __future__ import annotations

from pathlib import Path

from serpent_core.device import build_device_model
from serpent_core.fixtures import load_all_fixtures
from serpent_core.reactive_input import (
    KeyboardEventSource,
    MouseEventSource,
    ReactiveEventSource,
)


INPUT_BASE = Path("/dev/input/by-id")


def _paths(interfaces: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple(INPUT_BASE / name for name in interfaces)


def build_reactive_sources() -> tuple[ReactiveEventSource, ...]:
    result: list[ReactiveEventSource] = []

    for fixture in load_all_fixtures():
        model = build_device_model(fixture)
        anatomy = model.input_anatomy
        if anatomy is None:
            continue

        event_paths = _paths(anatomy.interfaces)

        if model.device_class == "keyboard":
            matrix = model.capabilities.matrix
            if matrix is None or anatomy.mapping is None:
                continue

            result.append(
                KeyboardEventSource(
                    source_id=model.id,
                    event_paths=event_paths,
                    matrix_rows=matrix.rows,
                    matrix_columns=matrix.columns,
                    row_offset=anatomy.mapping.row_offset,
                    column_offset=anatomy.mapping.column_offset,
                )
            )
            continue

        if model.device_class == "mouse":
            if anatomy.buttons is None:
                continue

            result.append(
                MouseEventSource(
                    source_id=model.id,
                    event_paths=event_paths,
                    button_minimum=anatomy.buttons.minimum_code,
                    button_maximum=anatomy.buttons.maximum_code,
                    macro_interface=(
                        anatomy.macro.interface
                        if anatomy.macro
                        else None
                    ),
                    macro_policy=(
                        anatomy.macro.policy
                        if anatomy.macro
                        else None
                    ),
                    macro_event_code=(
                        anatomy.macro.event_code
                        if anatomy.macro
                        else "MACRO_BUTTON"
                    ),
                )
            )

    return tuple(result)


__all__ = ["INPUT_BASE", "build_reactive_sources"]
