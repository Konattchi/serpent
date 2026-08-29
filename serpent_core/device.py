#!/usr/bin/env python3

from __future__ import annotations

import hashlib

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from serpent_core.fixtures import Fixture, FixtureError, LightingZone
from serpent_core.input_anatomy import InputAnatomy, parse_fixture_input
from serpent_core.physical_identity import stable_instance_id


@dataclass(frozen=True)
class MatrixCapability:
    rows: int
    columns: int


@dataclass(frozen=True)
class DpiCapability:
    supported: bool
    model: str | None
    axes: int
    maximum: int | None
    stage_count_source: str | None


@dataclass(frozen=True)
class PollingRateCapability:
    supported: bool
    values: tuple[int, ...]


@dataclass(frozen=True)
class PerformanceCapability:
    dpi: DpiCapability
    polling_rate: PollingRateCapability


@dataclass(frozen=True)
class DeviceCapabilities:
    battery: bool
    charging_state: bool
    brightness: bool
    matrix: MatrixCapability | None
    performance: PerformanceCapability


@dataclass(frozen=True)
class DeviceEffect:
    id: str
    backend: str
    colour_count: int
    has_speed: bool
    speeds: tuple[int, ...]
    directions: tuple[int, ...]


@dataclass(frozen=True)
class DeviceModel:
    """Fixture-derived device description used by Serpent frontends."""

    fixture: Fixture
    sysfs_path: Path | None
    zones: tuple[LightingZone, ...]
    effects: tuple[DeviceEffect, ...]
    capabilities: DeviceCapabilities

    @property
    def id(self) -> str:
        return self.fixture.id

    @property
    def instance_id(self) -> str:
        return stable_instance_id(
            self.fixture.id,
            self.sysfs_path,
        )

    @property
    def name(self) -> str:
        return self.fixture.display_name

    @property
    def device_class(self) -> str:
        return self.fixture.device_class

    @property
    def usb_id(self) -> str:
        return self.fixture.usb_id

    @property
    def input_anatomy(self) -> InputAnatomy | None:
        return parse_fixture_input(self.fixture.data)

    @property
    def backend_type(self) -> str:
        backend = self.fixture.data.get("backend", {})

        if not isinstance(backend, dict):
            raise FixtureError(
                f"{self.id}: backend must be an object."
            )

        backend_type = backend.get("type")

        if not isinstance(backend_type, str) or not backend_type:
            raise FixtureError(
                f"{self.id}: backend.type is missing."
            )

        return backend_type

    @property
    def connected(self) -> bool:
        return self.sysfs_path is not None

    def zone_by_id(self, zone_id: str) -> LightingZone:
        for zone in self.zones:
            if zone.id == zone_id:
                return zone

        raise FixtureError(
            f"{self.id}: unknown lighting zone {zone_id!r}."
        )

    def effect_by_id(self, effect_id: str) -> DeviceEffect:
        for effect in self.effects:
            if effect.id == effect_id:
                return effect

        raise FixtureError(
            f"{self.id}: unknown effect {effect_id!r}."
        )

    def visible_zones(self) -> tuple[LightingZone, ...]:
        return tuple(
            zone
            for zone in self.zones
            if zone.visible
        )

    def controllable_zones(self) -> tuple[LightingZone, ...]:
        return tuple(
            zone
            for zone in self.zones
            if zone.controllable
        )

    def confirmed_zones(self) -> tuple[LightingZone, ...]:
        return tuple(
            zone
            for zone in self.zones
            if zone.confirmed
        )


def _boolean(
    mapping: dict[str, Any],
    key: str,
    *,
    fallback: bool = False,
) -> bool:
    return bool(mapping.get(key, fallback))


def _integer_tuple(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()

    if not isinstance(value, Iterable) or isinstance(
        value,
        (str, bytes, dict),
    ):
        raise FixtureError(
            "Expected a sequence of integer capability values."
        )

    return tuple(int(item) for item in value)


def build_performance_capability(
    fixture: Fixture,
    capabilities: dict[str, Any],
) -> PerformanceCapability:
    raw = fixture.data.get("performance", {})

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise FixtureError(
            f"{fixture.id}: performance must be an object."
        )

    raw_dpi = raw.get("dpi", {})

    if not isinstance(raw_dpi, dict):
        raise FixtureError(
            f"{fixture.id}: performance.dpi must be an object."
        )

    raw_polling = raw.get("polling_rate", {})

    if not isinstance(raw_polling, dict):
        raise FixtureError(
            f"{fixture.id}: performance.polling_rate "
            "must be an object."
        )

    polling_values = _integer_tuple(
        raw_polling.get("values")
    )

    return PerformanceCapability(
        dpi=DpiCapability(
            supported=_boolean(capabilities, "dpi"),
            model=(
                str(raw_dpi["model"])
                if raw_dpi.get("model")
                else None
            ),
            axes=int(raw_dpi.get("axes", 1)),
            maximum=(
                int(raw_dpi["maximum"])
                if raw_dpi.get("maximum") is not None
                else None
            ),
            stage_count_source=(
                str(raw_dpi["stage_count_source"])
                if raw_dpi.get("stage_count_source")
                else None
            ),
        ),
        polling_rate=PollingRateCapability(
            supported=_boolean(
                capabilities,
                "poll_rate",
            ),
            values=polling_values,
        ),
    )


def build_capabilities(
    fixture: Fixture,
) -> DeviceCapabilities:
    raw = fixture.data.get("capabilities", {})

    if not isinstance(raw, dict):
        raise FixtureError(
            f"{fixture.id}: capabilities must be an object."
        )

    raw_matrix = raw.get("matrix")
    matrix: MatrixCapability | None = None

    if raw_matrix is not None:
        if not isinstance(raw_matrix, dict):
            raise FixtureError(
                f"{fixture.id}: capabilities.matrix "
                "must be an object."
            )

        rows = int(raw_matrix.get("rows", 0))
        columns = int(raw_matrix.get("columns", 0))

        if rows < 1 or columns < 1:
            raise FixtureError(
                f"{fixture.id}: matrix rows and columns "
                "must both be at least 1."
            )

        matrix = MatrixCapability(
            rows=rows,
            columns=columns,
        )

    return DeviceCapabilities(
        battery=_boolean(raw, "battery"),
        charging_state=_boolean(
            raw,
            "charging_state",
        ),
        brightness=_boolean(raw, "brightness"),
        matrix=matrix,
        performance=build_performance_capability(
            fixture,
            raw,
        ),
    )


def build_effects(
    fixture: Fixture,
) -> tuple[DeviceEffect, ...]:
    raw_effects = fixture.data.get("effects", {})

    if not isinstance(raw_effects, dict):
        raise FixtureError(
            f"{fixture.id}: effects must be an object."
        )

    result: list[DeviceEffect] = []

    for effect_id, raw_definition in raw_effects.items():
        if not isinstance(raw_definition, dict):
            raise FixtureError(
                f"{fixture.id}: effect {effect_id!r} "
                "must be an object."
            )

        speeds = _integer_tuple(
            raw_definition.get("speeds")
        )
        directions = _integer_tuple(
            raw_definition.get("directions")
        )

        result.append(
            DeviceEffect(
                id=str(effect_id),
                backend=str(
                    raw_definition.get(
                        "backend",
                        "unknown",
                    )
                ),
                colour_count=int(
                    raw_definition.get("colours", 0)
                ),
                has_speed=bool(
                    raw_definition.get("speed")
                    or speeds
                ),
                speeds=speeds,
                directions=directions,
            )
        )

    return tuple(result)


def build_device_model(
    fixture: Fixture,
    *,
    sysfs_path: Path | None = None,
) -> DeviceModel:
    return DeviceModel(
        fixture=fixture,
        sysfs_path=sysfs_path,
        zones=fixture.lighting_zones,
        effects=build_effects(fixture),
        capabilities=build_capabilities(fixture),
    )
