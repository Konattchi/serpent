from __future__ import annotations

from typing import Any

from serpent_core.device import DeviceModel
from serpent_core.topology import LightingTopology


def validate_sync_groupability(fixture_data: dict[str, Any]) -> None:
    zones = fixture_data.get("zones", {})
    if zones is None:
        return
    if not isinstance(zones, dict):
        raise ValueError("Fixture zones must be an object.")
    for zone_id, definition in zones.items():
        if not isinstance(definition, dict):
            continue
        if "sync_groupable" in definition and not isinstance(
            definition["sync_groupable"],
            bool,
        ):
            raise ValueError(
                f"Fixture zone {zone_id!r} sync_groupable must be boolean."
            )


def zone_sync_groupable(
    fixture_data: dict[str, Any],
    zone_id: str,
    *,
    default: bool = True,
) -> bool:
    zones = fixture_data.get("zones", {})
    if not isinstance(zones, dict):
        return default
    definition = zones.get(zone_id)
    if not isinstance(definition, dict):
        return default
    if "sync_groupable" in definition:
        value = definition["sync_groupable"]
        if not isinstance(value, bool):
            raise ValueError(
                f"Fixture zone {zone_id!r} sync_groupable must be boolean."
            )
        return value
    confirmed = bool(definition.get("confirmed", True))
    controllable = bool(definition.get("controllable", confirmed))
    return confirmed and controllable


def sync_groupable_region_ids(
    device: DeviceModel,
    topology: LightingTopology,
) -> tuple[str, ...]:
    validate_sync_groupability(device.fixture.data)
    result: list[str] = []
    for region in topology.regions:
        if not region.confirmed or not region.controllable:
            continue
        if zone_sync_groupable(
            device.fixture.data,
            region.id,
            default=True,
        ):
            result.append(region.id)
    return tuple(result)


def apply_reference_sync_groupability(
    fixture_data: dict[str, Any],
) -> dict[str, Any]:
    zones = fixture_data.get("zones")
    if not isinstance(zones, dict):
        return fixture_data
    for definition in zones.values():
        if not isinstance(definition, dict):
            continue
        confirmed = bool(definition.get("confirmed", True))
        controllable = bool(definition.get("controllable", confirmed))
        definition.setdefault(
            "sync_groupable",
            confirmed and controllable,
        )
    return fixture_data
