#!/usr/bin/env python3

from __future__ import annotations

import re
from collections.abc import Iterable

from serpent_core.backends.base import BackendError


ZONE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_colour(
    value: Iterable[int] | None,
    *,
    name: str = "colour",
) -> tuple[int, int, int]:
    if value is None:
        raise BackendError(
            f"{name} requires exactly three RGB values."
        )

    values = tuple(int(component) for component in value)

    if len(values) != 3:
        raise BackendError(
            f"{name} requires exactly three RGB values."
        )

    if any(component < 0 or component > 255 for component in values):
        raise BackendError(
            f"{name} RGB values must be between 0 and 255."
        )

    return values


def validate_brightness(value: int | float) -> int:
    brightness = int(value)

    if brightness < 0 or brightness > 100:
        raise BackendError(
            "Brightness must be between 0 and 100."
        )

    return brightness


def validate_allowed_integer(
    value: int,
    allowed: Iterable[int],
    *,
    name: str,
) -> int:
    result = int(value)
    choices = tuple(int(choice) for choice in allowed)

    if result not in choices:
        choices_text = ", ".join(str(choice) for choice in choices)

        raise BackendError(
            f"{name} must be one of: {choices_text}."
        )

    return result


def validate_zone_id(value: object) -> str:
    zone_id = str(value)

    if not ZONE_ID_PATTERN.fullmatch(zone_id):
        raise BackendError(
            "Lighting zone IDs must use lowercase letters, numbers, "
            "and single hyphens."
        )

    return zone_id
