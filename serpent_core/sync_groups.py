from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_GROUP_ID = "default"
DEFAULT_GROUP_NAME = "Default"

@dataclass(frozen=True)
class SyncGroupMember:
    instance_id: str
    zone_id: str
    brightness: float = 100.0

    @property
    def key(self) -> str:
        return f"{self.instance_id}:{self.zone_id}"

@dataclass(frozen=True)
class SyncGroup:
    id: str
    name: str
    effect: str
    speed: int
    colour1: tuple[int, int, int]
    colour2: tuple[int, int, int]
    direction: int
    members: tuple[SyncGroupMember, ...]

def validate_group_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Synchronization group id must be a string.")
    result = value.strip()
    if not result:
        raise ValueError("Synchronization group id must not be empty.")
    if ":" in result:
        raise ValueError("Synchronization group id must not contain ':'.")
    return result

def validate_group_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Synchronization group name must be a string.")
    result = value.strip()
    if not result:
        raise ValueError("Synchronization group name must not be empty.")
    return result

def validate_member(member: object) -> SyncGroupMember:
    if not isinstance(member, dict):
        raise ValueError("Synchronization group member must be an object.")

    instance_id = member.get("instance_id")
    zone_id = member.get("zone_id")
    brightness = member.get("brightness", 100)

    if not isinstance(instance_id, str) or "@" not in instance_id:
        raise ValueError(
            "Synchronization group member instance_id must be a physical instance id."
        )
    if not isinstance(zone_id, str) or not zone_id.strip():
        raise ValueError("Synchronization group member zone_id must be a non-empty string.")
    if isinstance(brightness, bool) or not isinstance(brightness, (int, float)):
        raise ValueError("Synchronization group member brightness must be numeric.")

    brightness = float(brightness)
    if brightness < 0 or brightness > 100:
        raise ValueError("Synchronization group member brightness must be between 0 and 100.")

    return SyncGroupMember(
        instance_id=instance_id,
        zone_id=zone_id.strip(),
        brightness=brightness,
    )

def _colour(value: object, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Synchronization group colour must be RGB.")
    result = tuple(int(x) for x in value)
    if any(x < 0 or x > 255 for x in result):
        raise ValueError("Synchronization group RGB values must be between 0 and 255.")
    return result

def validate_group(group: object) -> SyncGroup:
    if not isinstance(group, dict):
        raise ValueError("Synchronization group must be an object.")

    members_raw = group.get("members", [])
    if not isinstance(members_raw, list):
        raise ValueError("Synchronization group members must be a list.")

    members = tuple(validate_member(member) for member in members_raw)

    seen = set()
    for member in members:
        if member.key in seen:
            raise ValueError(
                f"Synchronization group contains duplicate member {member.key}."
            )
        seen.add(member.key)

    return SyncGroup(
        id=validate_group_id(group.get("id")),
        name=validate_group_name(group.get("name")),
        effect=str(group.get("effect", "spectrum")),
        speed=int(group.get("speed", 4)),
        colour1=_colour(group.get("colour1"), (0, 0, 255)),
        colour2=_colour(group.get("colour2"), (0, 255, 255)),
        direction=int(group.get("direction", 1)),
        members=members,
    )

def validate_groups(groups: object) -> tuple[SyncGroup, ...]:
    if not isinstance(groups, list):
        raise ValueError("Synchronization groups must be a list.")

    result = tuple(validate_group(group) for group in groups)
    group_ids = set()
    member_owners: dict[str, str] = {}

    for group in result:
        if group.id in group_ids:
            raise ValueError(f"Duplicate synchronization group id {group.id!r}.")
        group_ids.add(group.id)

        for member in group.members:
            previous = member_owners.get(member.key)
            if previous is not None:
                raise ValueError(
                    f"Synchronization member {member.key} belongs to both "
                    f"{previous!r} and {group.id!r}."
                )
            member_owners[member.key] = group.id

    return result

def canonical_group_dict(group: SyncGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "effect": group.effect,
        "speed": group.speed,
        "colour1": list(group.colour1),
        "colour2": list(group.colour2),
        "direction": group.direction,
        "members": [
            {
                "instance_id": member.instance_id,
                "zone_id": member.zone_id,
                "brightness": member.brightness,
            }
            for member in group.members
        ],
    }

def legacy_member_parts(member: str) -> tuple[str, str]:
    if not isinstance(member, str) or ":" not in member:
        raise ValueError(f"Invalid legacy synchronization member: {member!r}")
    fixture_id, zone_id = member.split(":", 1)
    if not fixture_id or not zone_id:
        raise ValueError(f"Invalid legacy synchronization member: {member!r}")
    return fixture_id, zone_id

def migrate_legacy_sync(
    sync: dict[str, Any],
    *,
    fixture_to_instance: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(sync, dict):
        raise ValueError("Synchronization profile must be an object.")

    if "groups" in sync:
        validate_groups(sync["groups"])
        return dict(sync)

    raw_members = sync.get("members", [])
    if not isinstance(raw_members, list):
        raise ValueError("Synchronization members must be a list.")

    raw_brightness = sync.get("member_brightness", {})
    if not isinstance(raw_brightness, dict):
        raise ValueError("Synchronization member_brightness must be an object.")

    members = []
    for legacy_member in raw_members:
        fixture_id, zone_id = legacy_member_parts(legacy_member)

        if fixture_id not in fixture_to_instance:
            raise ValueError(
                f"Cannot migrate {legacy_member!r}: fixture {fixture_id!r} "
                "does not resolve to one connected physical instance."
            )

        members.append(
            {
                "instance_id": fixture_to_instance[fixture_id],
                "zone_id": zone_id,
                "brightness": float(raw_brightness.get(legacy_member, 100)),
            }
        )

    group = {
        "id": DEFAULT_GROUP_ID,
        "name": DEFAULT_GROUP_NAME,
        "effect": str(sync.get("effect", "spectrum")),
        "speed": int(sync.get("speed", 4)),
        "colour1": list(sync.get("colour1", [0, 0, 255])),
        "colour2": list(sync.get("colour2", [0, 255, 255])),
        "direction": int(sync.get("direction", 1)),
        "members": members,
    }

    validate_group(group)

    migrated = dict(sync)
    migrated["groups"] = [group]
    migrated["group_schema_version"] = 1
    return migrated
