#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serpent_core.input_anatomy import validate_fixture_input
from serpent_core.lighting_capabilities import validate_lighting_capability


FIXTURE_DIR = Path.home() / ".local" / "share" / "serpent" / "fixtures"
ZONE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class FixtureError(RuntimeError):
    """Raised when a fixture is missing or invalid."""


@dataclass(frozen=True)
class LightingZone:
    id: str
    name: str
    zone_type: str
    mapping_type: str
    columns: tuple[int, ...]
    visible: bool
    confirmed: bool
    controllable: bool
    notes: str | None = None


@dataclass(frozen=True)
class Fixture:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def display_name(self) -> str:
        manufacturer = self.data["manufacturer"]
        model = self.data["model"]
        variant = self.data.get("variant")

        if variant:
            return f"{manufacturer} {model} ({variant})"

        return f"{manufacturer} {model}"

    @property
    def usb_id(self) -> str:
        usb = self.data["usb"]
        return f"{usb['vendor_id']}:{usb['product_id']}"

    @property
    def device_class(self) -> str:
        return str(self.data["device_class"])

    @property
    def lighting_zones(self) -> tuple[LightingZone, ...]:
        zones = self.data.get("zones", {})

        if not isinstance(zones, dict):
            return ()

        result: list[LightingZone] = []

        for zone_id, definition in zones.items():
            if not isinstance(definition, dict):
                continue

            mapping = definition.get("mapping", {})

            if not isinstance(mapping, dict):
                mapping = {}

            # Compatibility with schema-version-1 fixtures that used
            # a direct "column" property.
            if "columns" in mapping:
                columns = tuple(
                    int(column)
                    for column in mapping.get("columns", [])
                )
            elif "column" in definition:
                columns = (int(definition["column"]),)
            else:
                columns = ()

            result.append(
                LightingZone(
                    id=str(zone_id),
                    name=str(definition.get("name", zone_id)),
                    zone_type=str(
                        definition.get("type", "auxiliary")
                    ),
                    mapping_type=str(
                        mapping.get("type", "matrix-columns")
                    ),
                    columns=columns,
                    visible=bool(definition.get("visible", True)),
                    confirmed=bool(definition.get("confirmed", True)),
                    controllable=bool(
                        definition.get(
                            "controllable",
                            definition.get("confirmed", True),
                        )
                    ),
                    notes=(
                        str(definition["notes"])
                        if definition.get("notes")
                        else None
                    ),
                )
            )

        return tuple(result)

    def zone_by_id(self, zone_id: str) -> LightingZone:
        for zone in self.lighting_zones:
            if zone.id == zone_id:
                return zone

        raise FixtureError(
            f"{self.id}: unknown lighting zone {zone_id!r}."
        )

    def controllable_zones(self) -> tuple[LightingZone, ...]:
        return tuple(
            zone
            for zone in self.lighting_zones
            if zone.controllable
        )

    def visible_zones(self) -> tuple[LightingZone, ...]:
        return tuple(
            zone
            for zone in self.lighting_zones
            if zone.visible
        )


def validate_fixture(data: dict[str, Any], path: Path) -> None:
    required_top_level = (
        "schema_version",
        "id",
        "manufacturer",
        "model",
        "device_class",
        "usb",
        "backend",
        "capabilities",
        "effects",
    )

    for field in required_top_level:
        if field not in data:
            raise FixtureError(
                f"{path.name}: missing required field '{field}'."
            )

    if data["schema_version"] != 1:
        raise FixtureError(
            f"{path.name}: unsupported schema_version "
            f"{data['schema_version']}."
        )

    device_class = data["device_class"]

    if (
        not isinstance(device_class, str)
        or not ZONE_ID_PATTERN.fullmatch(device_class)
    ):
        raise FixtureError(
            f"{path.name}: invalid device_class "
            f"{device_class!r}; use a lowercase slug containing "
            "letters, numbers, and hyphens."
        )

    usb = data["usb"]

    if not isinstance(usb, dict):
        raise FixtureError(
            f"{path.name}: usb must be an object."
        )

    for field in ("vendor_id", "product_id"):
        if field not in usb:
            raise FixtureError(
                f"{path.name}: usb.{field} is required."
            )

        value = str(usb[field])

        if len(value) != 4:
            raise FixtureError(
                f"{path.name}: usb.{field} must contain "
                "exactly four hexadecimal characters."
            )

        try:
            int(value, 16)
        except ValueError as exc:
            raise FixtureError(
                f"{path.name}: usb.{field} is not hexadecimal."
            ) from exc

    effects = data["effects"]

    if not isinstance(effects, dict) or not effects:
        raise FixtureError(
            f"{path.name}: effects must be a non-empty object."
        )

    validate_zones(data, path)

    try:
        validate_fixture_input(data, path)
    except ValueError as exc:
        raise FixtureError(str(exc)) from exc


def validate_zones(data: dict[str, Any], path: Path) -> None:
    telemetry = data.get("telemetry")
    if telemetry is not None:
        if not isinstance(telemetry, dict):
            raise FixtureError(f"{path.name}: telemetry must be an object.")
        allowed_telemetry = {"battery", "charging"}
        unknown_telemetry = set(telemetry) - allowed_telemetry
        if unknown_telemetry:
            raise FixtureError(
                f"{path.name}: unsupported telemetry field(s): "
                + ", ".join(sorted(unknown_telemetry))
            )
        for telemetry_name in allowed_telemetry:
            if telemetry_name in telemetry and not isinstance(telemetry[telemetry_name], bool):
                raise FixtureError(
                    f"{path.name}: telemetry.{telemetry_name} must be true or false."
                )

    zones = data.get("zones")

    if zones is None:
        return

    if not isinstance(zones, dict):
        raise FixtureError(
            f"{path.name}: zones must be an object keyed by zone ID."
        )

    matrix = data.get("capabilities", {}).get("matrix", {})

    if not isinstance(matrix, dict):
        matrix = {}

    column_count = matrix.get("columns")

    if column_count is not None:
        column_count = int(column_count)

        if column_count < 1:
            raise FixtureError(
                f"{path.name}: capabilities.matrix.columns "
                "must be at least 1."
            )

    for zone_id, definition in zones.items():
        if not ZONE_ID_PATTERN.fullmatch(str(zone_id)):
            raise FixtureError(
                f"{path.name}: invalid zone ID {zone_id!r}; "
                "use lowercase letters, numbers, and hyphens."
            )

        if not isinstance(definition, dict):
            raise FixtureError(
                f"{path.name}: zones.{zone_id} must be an object."
            )

        name = definition.get("name")

        if not isinstance(name, str) or not name.strip():
            raise FixtureError(
                f"{path.name}: zones.{zone_id}.name "
                "must be a non-empty string."
            )

        mapping = definition.get("mapping")

        if mapping is None:
            if "column" not in definition:
                raise FixtureError(
                    f"{path.name}: zones.{zone_id} needs either "
                    "mapping or the legacy column field."
                )

            columns = (int(definition["column"]),)
        else:
            if not isinstance(mapping, dict):
                raise FixtureError(
                    f"{path.name}: zones.{zone_id}.mapping "
                    "must be an object."
                )

            mapping_type = mapping.get("type")

            if mapping_type != "matrix-columns":
                raise FixtureError(
                    f"{path.name}: zones.{zone_id}.mapping.type "
                    "must currently be 'matrix-columns'."
                )

            raw_columns = mapping.get("columns")

            if (
                not isinstance(raw_columns, list)
                or not raw_columns
            ):
                raise FixtureError(
                    f"{path.name}: zones.{zone_id}.mapping.columns "
                    "must be a non-empty list."
                )

            columns = tuple(int(column) for column in raw_columns)

        if len(set(columns)) != len(columns):
            raise FixtureError(
                f"{path.name}: zones.{zone_id} repeats a matrix column."
            )

        for column in columns:
            if column < 0:
                raise FixtureError(
                    f"{path.name}: zones.{zone_id} contains "
                    "a negative matrix column."
                )

            if (
                column_count is not None
                and column >= column_count
            ):
                raise FixtureError(
                    f"{path.name}: zones.{zone_id} column {column} "
                    f"is outside the declared 0–{column_count - 1} "
                    "matrix range."
                )

        for field in (
            "visible",
            "confirmed",
            "controllable",
        ):
            if (
                field in definition
                and not isinstance(definition[field], bool)
            ):
                raise FixtureError(
                    f"{path.name}: zones.{zone_id}.{field} "
                    "must be true or false."
                )


def load_fixture(path: Path) -> Fixture:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(
            f"{path.name}: invalid JSON at line "
            f"{exc.lineno}, column {exc.colno}."
        ) from exc

    validate_fixture(data, path)
    validate_lighting_capability(data)
    return Fixture(path=path, data=data)


def load_all_fixtures() -> list[Fixture]:
    if not FIXTURE_DIR.exists():
        return []

    fixtures = [
        load_fixture(path)
        for path in sorted(FIXTURE_DIR.glob("*.json"))
    ]

    ids: set[str] = set()

    for fixture in fixtures:
        if fixture.id in ids:
            raise FixtureError(
                f"Duplicate fixture id: {fixture.id}"
            )

        ids.add(fixture.id)

    return fixtures


def find_fixture_by_id(fixture_id: str) -> Fixture:
    for fixture in load_all_fixtures():
        if fixture.id == fixture_id:
            return fixture

    raise FixtureError(f"Fixture not found: {fixture_id}")
