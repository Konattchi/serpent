from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from serpent_core.device import DeviceModel, build_device_model
from serpent_core.sync import SyncSettings, require_topology
from serpent_core.sync_groups import SyncGroup, SyncGroupMember


@dataclass(frozen=True)
class ResolvedGroupMember:
    group_id: str
    group_name: str
    member: SyncGroupMember
    device: DeviceModel

    @property
    def key(self) -> str:
        return self.member.key


@dataclass(frozen=True)
class GroupRuntimePlan:
    group: SyncGroup
    active_members: tuple[ResolvedGroupMember, ...]
    missing_members: tuple[SyncGroupMember, ...]


def group_to_sync_settings(
    group: SyncGroup,
    *,
    frame_interval: float = 0.03,
) -> SyncSettings:
    brightness = {
        member.key: member.brightness
        for member in group.members
    }
    return SyncSettings(
        effect=group.effect,
        speed=group.speed,
        colour1=group.colour1,
        colour2=group.colour2,
        keyboard_brightness=100.0,
        mouse_brightness=100.0,
        member_brightness=brightness,
        frame_interval=frame_interval,
        direction=group.direction,
    )


def detected_device_map(detected_instances: Iterable[object]) -> dict[str, DeviceModel]:
    result: dict[str, DeviceModel] = {}
    for detected in detected_instances:
        instance_id = str(detected.instance_id)
        if instance_id in result:
            raise ValueError(
                f"Duplicate physical instance identity {instance_id!r}."
            )
        result[instance_id] = build_device_model(
            detected.fixture,
            sysfs_path=detected.sysfs_path,
        )
    return result


def resolve_group(
    group: SyncGroup,
    devices_by_instance: dict[str, DeviceModel],
) -> GroupRuntimePlan:
    active = []
    missing = []

    for member in group.members:
        device = devices_by_instance.get(member.instance_id)
        if device is None:
            missing.append(member)
            continue

        topology = require_topology(device)
        if not any(
            region.id == member.zone_id
            for region in topology.regions
        ):
            raise ValueError(
                f"{device.id}: unknown synchronization topology region "
                f"{member.zone_id!r}."
            )

        active.append(
            ResolvedGroupMember(
                group_id=group.id,
                group_name=group.name,
                member=member,
                device=device,
            )
        )

    active.sort(key=lambda item: (item.device.instance_id, item.member.zone_id))
    missing.sort(key=lambda item: (item.instance_id, item.zone_id))

    return GroupRuntimePlan(
        group=group,
        active_members=tuple(active),
        missing_members=tuple(missing),
    )


def build_group_runtime_plans(
    groups: Iterable[SyncGroup],
    detected_instances: Iterable[object],
) -> tuple[GroupRuntimePlan, ...]:
    devices = detected_device_map(detected_instances)
    plans = tuple(resolve_group(group, devices) for group in groups)
    return tuple(sorted(plans, key=lambda plan: plan.group.id))


def group_member_brightness(
    group: SyncGroup,
    instance_id: str,
    zone_id: str,
    *,
    default: float = 100.0,
) -> float:
    key = f"{instance_id}:{zone_id}"
    for member in group.members:
        if member.key == key:
            return member.brightness
    return default
