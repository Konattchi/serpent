from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from serpent_core.device import build_device_model
from serpent_core.effects import (
    EffectParameters,
    EffectTarget,
    assess_effect_suitability,
    get_effect_definition,
)
from serpent_core.effects.base import (
    DEGRADE_SPATIAL,
    DEGRADE_TEMPORAL,
    DEGRADE_UNIFORM,
)
from serpent_core.fixtures import find_fixture_by_id
from serpent_core.topology import build_lighting_topology


@dataclass(frozen=True)
class RenderingReport:
    fixture_id: str
    device_name: str
    effect_id: str
    capability: str
    policy: str
    result: str
    spatial_positions: int
    minimum_positions: int
    recommended_positions: int

    @property
    def uses_fallback(self) -> bool:
        return self.capability in {
            "limited",
            "uniform",
        }


def _parse_members(
    members: list[str] | tuple[str, ...],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}

    for member in members:
        if not isinstance(member, str) or ":" not in member:
            raise ValueError(
                f"Invalid synchronization member: {member!r}"
            )

        fixture_id, region_id = member.split(":", 1)

        if not fixture_id or not region_id:
            raise ValueError(
                f"Invalid synchronization member: {member!r}"
            )

        grouped.setdefault(
            fixture_id,
            [],
        ).append(region_id)

    return grouped


def _target_for_fixture(
    fixture_id: str,
    region_ids: list[str],
) -> tuple[str, EffectTarget]:
    fixture = find_fixture_by_id(fixture_id)
    device = build_device_model(fixture)
    topology = build_lighting_topology(device)

    if topology is None:
        raise ValueError(
            f"{fixture.display_name} has no lighting topology."
        )

    cells: list[tuple[int, int]] = []

    for region_id in region_ids:
        region = topology.region_by_id(region_id)

        if not region.controllable:
            continue

        cells.extend(
            (cell.row, cell.column)
            for cell in region.cells
        )

    target = EffectTarget(
        rows=topology.rows,
        columns=topology.columns,
        active_cells=tuple(dict.fromkeys(cells)),
        device_class=topology.device_class,
    )
    target.validate()

    return fixture.display_name, target


def _result_description(
    *,
    spatial: bool,
    capability: str,
    policy: str,
    positions: int,
) -> str:
    if not spatial:
        return "full uniform rendering"

    if capability == "full":
        return "full spatial rendering"

    if policy == DEGRADE_TEMPORAL:
        return "synchronized temporal fallback"

    if policy == DEGRADE_UNIFORM:
        return "uniform fallback"

    if policy == DEGRADE_SPATIAL:
        if capability == "limited":
            return (
                "reduced spatial rendering "
                f"({positions} positions)"
            )

        return (
            "uniform spatial collapse "
            f"({positions} position"
            f"{'' if positions == 1 else 's'})"
        )

    return "fallback behavior unknown"


def sync_rendering_reports(
    sync_settings: dict[str, Any],
) -> tuple[RenderingReport, ...]:
    effect_id = str(
        sync_settings.get(
            "effect",
            "spectrum",
        )
    )
    definition = get_effect_definition(effect_id)

    parameters = EffectParameters(
        brightness=100.0,
        colour1=tuple(
            sync_settings.get(
                "colour1",
                (255, 0, 255),
            )
        ),
        colour2=tuple(
            sync_settings.get(
                "colour2",
                (0, 255, 255),
            )
        ),
        speed=int(
            sync_settings.get(
                "speed",
                2,
            )
        ),
        direction=int(
            sync_settings.get(
                "direction",
                1,
            )
        ),
    )

    raw_members = sync_settings.get(
        "members",
        (),
    )

    if not isinstance(
        raw_members,
        (list, tuple),
    ):
        raise ValueError(
            "Synchronization members must be a list."
        )

    reports: list[RenderingReport] = []

    for fixture_id, region_ids in _parse_members(
        raw_members
    ).items():
        device_name, target = _target_for_fixture(
            fixture_id,
            region_ids,
        )

        suitability = assess_effect_suitability(
            effect_id,
            target,
            parameters,
        )

        reports.append(
            RenderingReport(
                fixture_id=fixture_id,
                device_name=device_name,
                effect_id=effect_id,
                capability=suitability.level,
                policy=definition.degradation_policy,
                result=_result_description(
                    spatial=definition.spatial,
                    capability=suitability.level,
                    policy=definition.degradation_policy,
                    positions=suitability.spatial_positions,
                ),
                spatial_positions=(
                    suitability.spatial_positions
                ),
                minimum_positions=(
                    suitability.minimum_positions
                ),
                recommended_positions=(
                    suitability.recommended_positions
                ),
            )
        )

    return tuple(reports)


__all__ = [
    "RenderingReport",
    "sync_rendering_reports",
]
