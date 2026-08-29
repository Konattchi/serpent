from __future__ import annotations

from serpent_core.patterns.base import (
    Pattern,
    PatternSample,
)
from serpent_core.patterns.checker import CheckerPattern
from serpent_core.patterns.gradient import GradientPattern
from serpent_core.patterns.rainbow import RainbowPattern


_PATTERNS: dict[str, Pattern] = {
    pattern.id: pattern
    for pattern in (
        RainbowPattern(),
        CheckerPattern(),
        GradientPattern(),
    )
}


def pattern_ids() -> tuple[str, ...]:
    return tuple(_PATTERNS)


def get_pattern(pattern_id: str) -> Pattern:
    try:
        return _PATTERNS[pattern_id]
    except KeyError as exc:
        raise ValueError(
            f"Pattern is not implemented: {pattern_id}"
        ) from exc


__all__ = [
    "Pattern",
    "PatternSample",
    "get_pattern",
    "pattern_ids",
]
