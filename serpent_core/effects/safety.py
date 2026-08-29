from __future__ import annotations

from dataclasses import dataclass


DEFAULT_QUARANTINE_THRESHOLD = 3


@dataclass(frozen=True)
class EffectRuntimeHealth:
    effect_id: str
    consecutive_failures: int
    quarantined: bool
    last_error: str | None


class EffectSafetyState:
    """Process-local failure containment for effect rendering."""

    def __init__(
        self,
        quarantine_threshold: int = DEFAULT_QUARANTINE_THRESHOLD,
    ) -> None:
        if quarantine_threshold < 1:
            raise ValueError("Quarantine threshold must be at least 1.")

        self.quarantine_threshold = quarantine_threshold
        self._failures: dict[str, int] = {}
        self._last_error: dict[str, str] = {}
        self._quarantined: set[str] = set()

    def success(self, effect_id: str) -> None:
        if effect_id not in self._quarantined:
            self._failures[effect_id] = 0
            self._last_error.pop(effect_id, None)

    def failure(self, effect_id: str, exc: Exception) -> None:
        failures = self._failures.get(effect_id, 0) + 1
        self._failures[effect_id] = failures
        self._last_error[effect_id] = (
            f"{type(exc).__name__}: {exc}"
        )

        if failures >= self.quarantine_threshold:
            self._quarantined.add(effect_id)

    def is_quarantined(self, effect_id: str) -> bool:
        return effect_id in self._quarantined

    def health(self, effect_id: str) -> EffectRuntimeHealth:
        return EffectRuntimeHealth(
            effect_id=effect_id,
            consecutive_failures=self._failures.get(effect_id, 0),
            quarantined=self.is_quarantined(effect_id),
            last_error=self._last_error.get(effect_id),
        )

    def reset(self, effect_id: str | None = None) -> None:
        if effect_id is None:
            self._failures.clear()
            self._last_error.clear()
            self._quarantined.clear()
            return

        self._failures.pop(effect_id, None)
        self._last_error.pop(effect_id, None)
        self._quarantined.discard(effect_id)


__all__ = [
    "DEFAULT_QUARANTINE_THRESHOLD",
    "EffectRuntimeHealth",
    "EffectSafetyState",
]
