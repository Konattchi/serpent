#!/usr/bin/env python3

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from serpent_core.backends.base import (
    BackendError,
    LightingBackend,
)
from serpent_core.validation import (
    validate_allowed_integer,
    validate_brightness,
    validate_colour,
)


class SysfsHardwareEffectsBackend(LightingBackend):
    """Apply fixture-described hardware effects through sysfs."""

    def __init__(
        self,
        fixture,
        sysfs_path: Path,
        *,
        openrazer_device: Any | None = None,
    ) -> None:
        super().__init__(fixture, sysfs_path)
        self.openrazer_device = openrazer_device

    def endpoint(self, name: str) -> Path:
        path = self.sysfs_path / name

        if not path.exists():
            raise BackendError(
                f"Required sysfs endpoint is missing: {path}"
            )

        return path

    def write(
        self,
        endpoint_name: str,
        payload: bytes,
        *,
        repetitions: int = 2,
        delay: float = 0.15,
    ) -> None:
        endpoint = self.endpoint(endpoint_name)

        try:
            for attempt in range(repetitions):
                endpoint.write_bytes(payload)

                if attempt + 1 < repetitions:
                    time.sleep(delay)

        except PermissionError as exc:
            raise BackendError(
                f"Permission denied while writing {endpoint}."
            ) from exc

        except OSError as exc:
            raise BackendError(
                f"Could not write {endpoint}: {exc}"
            ) from exc

    def set_brightness(self, brightness: int) -> None:
        brightness = validate_brightness(brightness)

        if self.openrazer_device is None:
            raise BackendError(
                "Brightness control requires a matched "
                "OpenRazer device."
            )

        try:
            self.openrazer_device.brightness = brightness
        except Exception as exc:
            raise BackendError(
                f"Could not set brightness: {exc}"
            ) from exc

        # Some firmware needs time to settle before changing effect.
        time.sleep(0.2)

    def required_endpoint(
        self,
        definition: dict[str, Any],
        effect: str,
    ) -> str:
        endpoint_name = definition.get("endpoint")

        if not endpoint_name:
            raise BackendError(
                f"Effect {effect!r} has no endpoint "
                "in its fixture."
            )

        return str(endpoint_name)

    def validate_payload_type(
        self,
        definition: dict[str, Any],
        expected: str,
        effect: str,
    ) -> None:
        payload_type = definition.get("payload")

        if payload_type != expected:
            raise BackendError(
                f"Effect {effect!r} expected payload "
                f"{expected!r}, but the fixture declares "
                f"{payload_type!r}."
            )

    def effect_off(
        self,
        definition: dict[str, Any],
        _settings: dict[str, Any],
    ) -> None:
        effect = "off"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "trigger",
            effect,
        )
        self.write(endpoint, b"\x01")

    def effect_static(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "static"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "rgb",
            effect,
        )

        colour = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )

        self.write(endpoint, bytes(colour))

    def effect_spectrum(
        self,
        definition: dict[str, Any],
        _settings: dict[str, Any],
    ) -> None:
        effect = "spectrum"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "trigger",
            effect,
        )
        self.write(endpoint, b"\x01")

    def effect_wave(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "wave"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "ascii-direction",
            effect,
        )

        allowed = definition.get("directions", (1, 2))
        direction = validate_allowed_integer(
            settings.get("direction", 1),
            allowed,
            name="Wave direction",
        )

        self.write(
            endpoint,
            str(direction).encode("ascii"),
        )

    def effect_reactive(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "reactive"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "speed-rgb",
            effect,
        )

        speed = validate_allowed_integer(
            settings.get("speed", 2),
            definition.get("speeds", (1, 2, 3, 4)),
            name="Reactive speed",
        )
        colour = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )

        self.write(
            endpoint,
            bytes((speed, *colour)),
        )

    def effect_breath_random(
        self,
        definition: dict[str, Any],
        _settings: dict[str, Any],
    ) -> None:
        effect = "breath-random"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "random-trigger",
            effect,
        )
        self.write(endpoint, b"\x01")

    def effect_breath_single(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "breath-single"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "rgb",
            effect,
        )

        colour = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )

        self.write(endpoint, bytes(colour))

    def effect_breath_dual(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "breath-dual"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "rgb-rgb",
            effect,
        )

        colour1 = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )
        colour2 = validate_colour(
            settings.get("colour2"),
            name="Secondary colour",
        )

        self.write(
            endpoint,
            bytes((*colour1, *colour2)),
        )

    def effect_starlight_random(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "starlight-random"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "speed",
            effect,
        )

        speed = validate_allowed_integer(
            settings.get("speed", 2),
            definition.get("speeds", (1, 2, 3)),
            name="Starlight speed",
        )

        self.write(endpoint, bytes((speed,)))

    def effect_starlight_single(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "starlight-single"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "speed-rgb",
            effect,
        )

        speed = validate_allowed_integer(
            settings.get("speed", 2),
            definition.get("speeds", (1, 2, 3)),
            name="Starlight speed",
        )
        colour = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )

        self.write(
            endpoint,
            bytes((speed, *colour)),
        )

    def effect_starlight_dual(
        self,
        definition: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        effect = "starlight-dual"
        endpoint = self.required_endpoint(definition, effect)
        self.validate_payload_type(
            definition,
            "speed-rgb-rgb",
            effect,
        )

        speed = validate_allowed_integer(
            settings.get("speed", 2),
            definition.get("speeds", (1, 2, 3)),
            name="Starlight speed",
        )
        colour1 = validate_colour(
            settings.get("colour1"),
            name="Primary colour",
        )
        colour2 = validate_colour(
            settings.get("colour2"),
            name="Secondary colour",
        )

        self.write(
            endpoint,
            bytes((speed, *colour1, *colour2)),
        )

    def apply(
        self,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        definition = self.ensure_effect_supported(effect)

        brightness = validate_brightness(
            settings.get("brightness", 100)
        )
        self.set_brightness(brightness)

        handlers = {
            "off": self.effect_off,
            "static": self.effect_static,
            "spectrum": self.effect_spectrum,
            "wave": self.effect_wave,
            "reactive": self.effect_reactive,
            "breath-random": self.effect_breath_random,
            "breath-single": self.effect_breath_single,
            "breath-dual": self.effect_breath_dual,
            "starlight-random": self.effect_starlight_random,
            "starlight-single": self.effect_starlight_single,
            "starlight-dual": self.effect_starlight_dual,
        }

        handler = handlers.get(effect)

        if handler is None:
            raise BackendError(
                f"The hardware-effects-sysfs backend has not "
                f"implemented {effect!r}."
            )

        handler(definition, settings)
