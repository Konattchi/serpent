from __future__ import annotations
import copy
from typing import Any

def sync_region_assignments(profile: dict[str, Any], instance_id: str) -> dict[str, str]:
    sync = profile.get("sync", {})
    groups = sync.get("groups", []) if isinstance(sync, dict) else []
    result: dict[str, str] = {}
    if not isinstance(groups, list):
        return result
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("name") or group.get("id") or "Sync group")
        members = group.get("members", [])
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            if str(member.get("instance_id", "")) != instance_id:
                continue
            region_id = member.get("zone_id", member.get("region_id"))
            if isinstance(region_id, str) and region_id:
                result[region_id] = label
    return result

def store_personal_region_settings(
    profile: dict[str, Any], *, instance_id: str, fixture_id: str,
    region_id: str, settings: dict[str, Any],
) -> None:
    devices = profile.setdefault("fixture_devices", {})
    if not isinstance(devices, dict):
        raise ValueError("fixture_devices must be an object")
    device = devices.setdefault(instance_id, {})
    if not isinstance(device, dict):
        raise ValueError("fixture device profile must be an object")
    device["fixture_id"] = fixture_id
    if region_id == "__device__":
        device["settings"] = copy.deepcopy(settings)
        return
    zones = device.setdefault("zones", {})
    if not isinstance(zones, dict):
        raise ValueError("fixture device zones must be an object")
    zones[region_id] = copy.deepcopy(settings)

def personal_region_settings(
    profile: dict[str, Any], *, instance_id: str, region_id: str,
) -> dict[str, Any] | None:
    devices = profile.get("fixture_devices", {})
    if not isinstance(devices, dict):
        return None
    device = devices.get(instance_id)
    if not isinstance(device, dict):
        return None
    zones = device.get("zones", {})
    if isinstance(zones, dict):
        value = zones.get(region_id)
        if isinstance(value, dict) and value.get("effect"):
            return copy.deepcopy(value)
    settings = device.get("settings")
    if isinstance(settings, dict) and settings.get("effect"):
        return copy.deepcopy(settings)
    return None
