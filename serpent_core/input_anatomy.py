from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InputMapping:
    type: str
    row_offset: int = 0
    column_offset: int = 0


@dataclass(frozen=True)
class InputButtons:
    type: str
    minimum_code: int
    maximum_code: int


@dataclass(frozen=True)
class InputMacro:
    interface: str
    policy: str
    event_code: str


@dataclass(frozen=True)
class InputAnatomy:
    interfaces: tuple[str, ...]
    mapping: InputMapping | None = None
    buttons: InputButtons | None = None
    macro: InputMacro | None = None


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def parse_fixture_input(data: dict[str, Any]) -> InputAnatomy | None:
    raw = data.get("input")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("input must be an object.")

    raw_interfaces = raw.get("interfaces")
    if (
        not isinstance(raw_interfaces, list)
        or not raw_interfaces
        or any(not isinstance(item, str) or not item.strip() for item in raw_interfaces)
    ):
        raise ValueError("input.interfaces must be a non-empty list of strings.")

    interfaces = tuple(item.strip() for item in raw_interfaces)
    if len(set(interfaces)) != len(interfaces):
        raise ValueError("input.interfaces contains duplicate entries.")

    mapping = None
    raw_mapping = raw.get("mapping")
    if raw_mapping is not None:
        if not isinstance(raw_mapping, dict):
            raise ValueError("input.mapping must be an object.")
        mapping_type = _non_empty_string(
            raw_mapping.get("type"),
            "input.mapping.type",
        )
        if mapping_type != "openrazer-keyboard":
            raise ValueError(
                "input.mapping.type must currently be 'openrazer-keyboard'."
            )
        mapping = InputMapping(
            type=mapping_type,
            row_offset=int(raw_mapping.get("row_offset", 0)),
            column_offset=int(raw_mapping.get("column_offset", 0)),
        )

    buttons = None
    raw_buttons = raw.get("buttons")
    if raw_buttons is not None:
        if not isinstance(raw_buttons, dict):
            raise ValueError("input.buttons must be an object.")
        button_type = _non_empty_string(
            raw_buttons.get("type"),
            "input.buttons.type",
        )
        if button_type != "linux-mouse":
            raise ValueError(
                "input.buttons.type must currently be 'linux-mouse'."
            )
        minimum = int(raw_buttons.get("minimum_code", 272))
        maximum = int(raw_buttons.get("maximum_code", 279))
        if minimum < 0 or maximum < minimum:
            raise ValueError(
                "input.buttons code range is invalid."
            )
        buttons = InputButtons(
            type=button_type,
            minimum_code=minimum,
            maximum_code=maximum,
        )

    macro = None
    raw_macro = raw.get("macro")
    if raw_macro is not None:
        if not isinstance(raw_macro, dict):
            raise ValueError("input.macro must be an object.")
        interface = _non_empty_string(
            raw_macro.get("interface"),
            "input.macro.interface",
        )
        policy = _non_empty_string(
            raw_macro.get("policy"),
            "input.macro.policy",
        )
        if policy != "collapse-chord":
            raise ValueError(
                "input.macro.policy must currently be 'collapse-chord'."
            )
        if interface not in interfaces:
            raise ValueError(
                "input.macro.interface must also appear in input.interfaces."
            )
        macro = InputMacro(
            interface=interface,
            policy=policy,
            event_code=_non_empty_string(
                raw_macro.get("event_code", "MACRO_BUTTON"),
                "input.macro.event_code",
            ),
        )

    device_class = str(data.get("device_class", ""))
    if device_class == "keyboard":
        if mapping is None:
            raise ValueError(
                "keyboard fixtures with input metadata require input.mapping."
            )
        if buttons is not None or macro is not None:
            raise ValueError(
                "keyboard input metadata cannot declare mouse buttons/macros."
            )
    elif device_class == "mouse":
        if mapping is not None:
            raise ValueError(
                "mouse input metadata cannot declare keyboard mapping."
            )
        if buttons is None:
            raise ValueError(
                "mouse fixtures with input metadata require input.buttons."
            )

    return InputAnatomy(
        interfaces=interfaces,
        mapping=mapping,
        buttons=buttons,
        macro=macro,
    )


def validate_fixture_input(data: dict[str, Any], path: Path) -> None:
    try:
        parse_fixture_input(data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path.name}: {exc}") from exc


__all__ = [
    "InputAnatomy",
    "InputButtons",
    "InputMacro",
    "InputMapping",
    "parse_fixture_input",
    "validate_fixture_input",
]
