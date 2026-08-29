from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from serpent_core.device import build_device_model
from serpent_core.effects import (
    effect_ids,
    get_effect_definition,
    get_effect_plugin_spec,
)
from serpent_core.fixtures import find_fixture_by_id
from serpent_core.topology import build_lighting_topology
from serpent_core.geometry import (
    DIRECTION_BOTTOM_TO_TOP,
    DIRECTION_LEFT_TO_RIGHT,
    DIRECTION_RIGHT_TO_LEFT,
    DIRECTION_TOP_TO_BOTTOM,
)
from serpent_core.rendering import (
    RenderingReport,
    sync_rendering_reports,
)


@dataclass(frozen=True)
class ChoicePresentation:
    value: int
    label: str


@dataclass(frozen=True)
class EffectPresentation:
    id: str
    name: str
    colours: int
    animated: bool
    supports_speed: bool
    spatial: bool
    directions: tuple[ChoicePresentation, ...]
    degradation_policy: str
    description: str = ""

    @property
    def supports_direction(self) -> bool:
        return bool(self.directions)

    @property
    def controls(self) -> tuple[str, ...]:
        controls: list[str] = []

        if self.colours >= 1:
            controls.append("colour1")

        if self.colours >= 2:
            controls.append("colour2")

        if self.supports_speed:
            controls.append("speed")

        if self.supports_direction:
            controls.append("direction")

        controls.append("brightness")
        return tuple(controls)


@dataclass(frozen=True)
class SyncMemberPresentation:
    id: str
    fixture_id: str
    region_id: str
    device_name: str
    region_name: str

    @property
    def label(self) -> str:
        return f"{self.device_name} — {self.region_name}"


@dataclass(frozen=True)
class RenderingPresentation:
    fixture_id: str
    device_name: str
    capability: str
    policy: str
    result: str
    uses_fallback: bool


_DIRECTION_LABELS = {
    DIRECTION_LEFT_TO_RIGHT: "Left → Right",
    DIRECTION_RIGHT_TO_LEFT: "Right → Left",
    DIRECTION_TOP_TO_BOTTOM: "Top → Bottom",
    DIRECTION_BOTTOM_TO_TOP: "Bottom → Top",
}


def humanize_identifier(identifier: str) -> str:
    return " ".join(
        part.capitalize()
        for part in identifier.split("-")
    )


def direction_choices(
    values: tuple[int, ...],
) -> tuple[ChoicePresentation, ...]:
    return tuple(
        ChoicePresentation(
            value=value,
            label=_DIRECTION_LABELS.get(
                value,
                f"Direction {value}",
            ),
        )
        for value in values
    )


def effect_presentation(
    effect_id: str,
) -> EffectPresentation:
    definition = get_effect_definition(effect_id)
    plugin = get_effect_plugin_spec(effect_id)

    parameters = {
        parameter.id: parameter
        for parameter in plugin.parameters
    }

    colour_ids = {
        parameter_id
        for parameter_id, parameter in parameters.items()
        if parameter.kind == "colour"
    }

    direction = parameters.get("direction")
    direction_values = (
        tuple(int(value) for value in direction.choices)
        if direction is not None
        else ()
    )

    return EffectPresentation(
        id=plugin.id,
        name=plugin.name,
        colours=sum(
            parameter_id in colour_ids
            for parameter_id in ("colour1", "colour2")
        ),
        animated=definition.animated,
        supports_speed="speed" in parameters,
        spatial=definition.spatial,
        directions=direction_choices(
            direction_values
        ),
        degradation_policy=(
            definition.degradation_policy
        ),
        description=plugin.description,
    )


def effect_presentations() -> tuple[
    EffectPresentation,
    ...,
]:
    return tuple(
        effect_presentation(effect_id)
        for effect_id in effect_ids()
    )


def sync_member_presentations(
    sync_settings: dict[str, Any],
) -> tuple[SyncMemberPresentation, ...]:
    members = sync_settings.get("members", ())

    if not isinstance(members, (list, tuple)):
        return ()

    result: list[SyncMemberPresentation] = []

    for member in members:
        if not isinstance(member, str) or ":" not in member:
            continue

        fixture_id, region_id = member.split(":", 1)

        try:
            fixture = find_fixture_by_id(fixture_id)
            device = build_device_model(fixture)
            topology = build_lighting_topology(device)

            if topology is None:
                continue

            region = topology.region_by_id(region_id)
        except Exception:
            continue

        result.append(
            SyncMemberPresentation(
                id=member,
                fixture_id=fixture_id,
                region_id=region_id,
                device_name=device.name,
                region_name=region.name,
            )
        )

    return tuple(result)


def rendering_presentations(
    sync_settings: dict[str, Any],
) -> tuple[RenderingPresentation, ...]:
    reports: tuple[RenderingReport, ...] = (
        sync_rendering_reports(sync_settings)
    )

    return tuple(
        RenderingPresentation(
            fixture_id=report.fixture_id,
            device_name=report.device_name,
            capability=report.capability,
            policy=report.policy,
            result=report.result,
            uses_fallback=report.uses_fallback,
        )
        for report in reports
    )


__all__ = [
    "ChoicePresentation",
    "EffectPresentation",
    "RenderingPresentation",
    "SyncMemberPresentation",
    "direction_choices",
    "effect_presentation",
    "effect_presentations",
    "humanize_identifier",
    "rendering_presentations",
    "sync_member_presentations",
]
