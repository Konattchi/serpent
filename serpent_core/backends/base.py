#!/usr/bin/env python3

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from serpent_core.fixtures import Fixture


class BackendError(RuntimeError):
    """A user-facing backend failure."""


class LightingBackend(ABC):
    """Common interface implemented by Serpent lighting backends."""

    def __init__(
        self,
        fixture: Fixture,
        sysfs_path: Path,
    ) -> None:
        self.fixture = fixture
        self.sysfs_path = sysfs_path

    @property
    def backend_type(self) -> str:
        return str(self.fixture.data["backend"]["type"])

    @property
    def supported_effects(self) -> tuple[str, ...]:
        return tuple(self.fixture.data.get("effects", {}).keys())

    def ensure_effect_supported(self, effect: str) -> dict[str, Any]:
        effects = self.fixture.data.get("effects", {})

        if effect not in effects:
            raise BackendError(
                f"{self.fixture.display_name} does not support "
                f"the effect {effect!r}."
            )

        definition = effects[effect]

        if not isinstance(definition, dict):
            raise BackendError(
                f"Fixture effect definition is invalid: {effect}"
            )

        return definition

    @abstractmethod
    def apply(
        self,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        """Apply one effect using the provided settings."""
