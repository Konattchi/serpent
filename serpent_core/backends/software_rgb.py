#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

from serpent_core.backends.base import (
    BackendError,
    LightingBackend,
)
from serpent_core.validation import (
    validate_brightness,
    validate_colour,
    validate_zone_id,
)


class SoftwareRgbSysfsBackend(LightingBackend):
    """Control Serpent's persistent software RGB renderer."""

    def __init__(
        self,
        fixture,
        sysfs_path: Path,
        *,
        profile_path: Path,
        service_name: str,
        openrazer_device: Any | None = None,
    ) -> None:
        super().__init__(fixture, sysfs_path)

        self.profile_path = profile_path
        self.service_name = service_name
        self.openrazer_device = openrazer_device

    def fixture_data(self) -> dict[str, Any]:
        data = getattr(self.fixture, "data", self.fixture)

        if not isinstance(data, dict):
            raise BackendError(
                "The selected fixture does not contain fixture data."
            )

        return data

    def zone_definitions(self) -> dict[str, dict[str, Any]]:
        zones = self.fixture_data().get("zones", {})

        if not isinstance(zones, dict) or not zones:
            raise BackendError(
                "The selected fixture does not declare lighting zones."
            )

        result: dict[str, dict[str, Any]] = {}

        for raw_zone_id, raw_definition in zones.items():
            zone_id = validate_zone_id(raw_zone_id)

            if not isinstance(raw_definition, dict):
                raise BackendError(
                    f"Fixture zone {zone_id!r} is not an object."
                )

            result[zone_id] = raw_definition

        return result

    def zone_ids(
        self,
        *,
        controllable_only: bool = False,
        visible_only: bool = False,
    ) -> tuple[str, ...]:
        result: list[str] = []

        for zone_id, definition in self.zone_definitions().items():
            confirmed = bool(
                definition.get("confirmed", True)
            )
            controllable = bool(
                definition.get("controllable", confirmed)
            )
            visible = bool(
                definition.get("visible", True)
            )

            if controllable_only and not controllable:
                continue

            if visible_only and not visible:
                continue

            result.append(zone_id)

        return tuple(result)

    def primary_zone_id(self) -> str:
        backend = self.fixture_data().get("backend", {})

        if isinstance(backend, dict):
            requested = backend.get("linked_source_zone")

            if requested is not None:
                zone_id = validate_zone_id(requested)

                if zone_id not in self.zone_definitions():
                    raise BackendError(
                        "Fixture linked_source_zone refers to "
                        f"unknown zone {zone_id!r}."
                    )

                return zone_id

        controllable = self.zone_ids(controllable_only=True)

        if not controllable:
            raise BackendError(
                "The selected fixture has no controllable lighting zones."
            )

        return controllable[0]

    def default_settings(self) -> dict[str, Any]:
        return {
            "effect": "static",
            "brightness": 20,
            "colour1": [0, 0, 255],
            "colour2": [0, 255, 255],
            "speed": 2,
        }

    def default_mouse_profile(self) -> dict[str, Any]:
        defaults = self.default_settings()

        return {
            "linked": True,
            "zones": {
                zone_id: copy.deepcopy(defaults)
                for zone_id in self.zone_ids()
            },
        }

    def normalise_zone(
        self,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = self.default_settings()

        return {
            key: copy.deepcopy(settings.get(key, value))
            for key, value in defaults.items()
        }

    def normalise_mouse_profile(
        self,
        mouse: dict[str, Any],
    ) -> dict[str, Any]:
        declared_zone_ids = self.zone_ids()
        zones = mouse.get("zones")

        if isinstance(zones, dict):
            normalised = {
                "linked": bool(mouse.get("linked", True)),
                "zones": {},
            }

            for zone_id in declared_zone_ids:
                zone = zones.get(zone_id, {})

                if not isinstance(zone, dict):
                    zone = {}

                normalised["zones"][zone_id] = (
                    self.normalise_zone(zone)
                )

            # Preserve profile data for zones temporarily absent from a
            # fixture. This prevents a fixture downgrade from destroying
            # user settings.
            for zone_id, zone in zones.items():
                if (
                    zone_id not in normalised["zones"]
                    and isinstance(zone, dict)
                ):
                    normalised["zones"][str(zone_id)] = copy.deepcopy(zone)

            return normalised

        # Backward compatibility with the old flat mouse profile.
        legacy = self.normalise_zone(mouse)

        return {
            "linked": True,
            "zones": {
                zone_id: copy.deepcopy(legacy)
                for zone_id in declared_zone_ids
            },
        }

    def load_profile(self) -> dict[str, Any]:
        if not self.profile_path.exists():
            return {
                "mouse": self.default_mouse_profile(),
            }

        try:
            data = json.loads(
                self.profile_path.read_text(encoding="utf-8")
            )
        except OSError as exc:
            raise BackendError(
                f"Could not read Serpent profile: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise BackendError(
                f"Serpent profile contains invalid JSON: {exc}"
            ) from exc

        mouse = data.get("mouse")

        if not isinstance(mouse, dict):
            mouse = {}

        data["mouse"] = self.normalise_mouse_profile(mouse)
        return data

    def save_profile(self, profile: dict[str, Any]) -> None:
        try:
            self.profile_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.profile_path.write_text(
                json.dumps(profile, indent=4) + "\n",
                encoding="utf-8",
            )

        except OSError as exc:
            raise BackendError(
                f"Could not save Serpent profile: {exc}"
            ) from exc

    def restart_engine(self) -> None:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "restart",
                self.service_name,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if result.returncode != 0:
            output = result.stdout.strip()

            raise BackendError(
                f"Could not restart {self.service_name}: "
                f"{output or 'unknown systemctl error'}"
            )

    def update_zone(
        self,
        zone: dict[str, Any],
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        definition = self.ensure_effect_supported(effect)

        zone["effect"] = effect

        if "brightness" in settings:
            zone["brightness"] = validate_brightness(
                settings["brightness"]
            )

        colour_count = int(
            definition.get("colours", 0)
        )

        if colour_count >= 1 and "colour1" in settings:
            zone["colour1"] = list(
                validate_colour(
                    settings["colour1"],
                    name="Primary colour",
                )
            )

        if colour_count >= 2 and "colour2" in settings:
            zone["colour2"] = list(
                validate_colour(
                    settings["colour2"],
                    name="Secondary colour",
                )
            )

        if (
            definition.get("speed")
            or definition.get("speeds")
            or "speed" in settings
        ):
            speed = int(
                settings.get(
                    "speed",
                    zone.get("speed", 2),
                )
            )

            if speed < 1:
                raise BackendError(
                    "Animation speed must be at least 1."
                )

            zone["speed"] = speed

    def apply(
        self,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        """Apply an effect to every controllable fixture zone."""

        profile = self.load_profile()
        mouse = profile["mouse"]
        zones = mouse["zones"]

        for zone_id in self.zone_ids(controllable_only=True):
            self.update_zone(
                zones[zone_id],
                effect,
                settings,
            )

        mouse["linked"] = True

        self.save_profile(profile)
        self.restart_engine()

    def apply_zone(
        self,
        zone_id: str,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        """Apply an effect to one fixture-declared zone."""

        zone_id = validate_zone_id(zone_id)
        definitions = self.zone_definitions()

        if zone_id not in definitions:
            raise BackendError(
                f"Unknown lighting zone: {zone_id!r}."
            )

        definition = definitions[zone_id]
        confirmed = bool(definition.get("confirmed", True))
        controllable = bool(
            definition.get("controllable", confirmed)
        )

        if not controllable:
            raise BackendError(
                f"Lighting zone {zone_id!r} is declared "
                "non-controllable."
            )

        profile = self.load_profile()
        mouse = profile["mouse"]

        self.update_zone(
            mouse["zones"][zone_id],
            effect,
            settings,
        )

        mouse["linked"] = False

        self.save_profile(profile)
        self.restart_engine()

    def set_linked(self, linked: bool) -> None:
        profile = self.load_profile()
        mouse = profile["mouse"]

        if linked:
            source_id = self.primary_zone_id()
            source = copy.deepcopy(
                mouse["zones"][source_id]
            )

            for zone_id in self.zone_ids(controllable_only=True):
                mouse["zones"][zone_id] = copy.deepcopy(source)

        mouse["linked"] = bool(linked)

        self.save_profile(profile)
        self.restart_engine()
