from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import openrazer.client

from serpent_core.discovery import detect_all_fixture_instances
from serpent_core.identity import match_fixture_identity


@dataclass(frozen=True)
class DeviceTelemetrySnapshot:
    instance_id: str
    fixture_id: str
    display_name: str
    device_class: str
    connected: bool
    battery_supported: bool
    battery: int | None
    charging_supported: bool
    charging: bool | None


def telemetry_capabilities(fixture_data: dict[str, Any]) -> tuple[bool, bool]:
    legacy_battery = bool(
        fixture_data.get("capabilities", {}).get("battery", False)
    )
    telemetry = fixture_data.get("telemetry")
    if isinstance(telemetry, dict):
        battery = bool(telemetry.get("battery", legacy_battery))
        charging = bool(telemetry.get("charging", battery))
    else:
        battery = legacy_battery
        charging = legacy_battery
    return battery, charging


def _read_attribute(device: Any, name: str) -> Any:
    if device is None:
        return None
    try:
        value = getattr(device, name)
        return value() if callable(value) else value
    except Exception:
        return None


def _battery_value(device: Any) -> int | None:
    value = _read_attribute(device, "battery_level")
    if value is None:
        return None
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


def _charging_value(device: Any) -> bool | None:
    value = _read_attribute(device, "is_charging")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "charging", "on"}:
        return True
    if text in {"false", "no", "0", "not charging", "off"}:
        return False
    return None


def collect_device_telemetry() -> list[DeviceTelemetrySnapshot]:
    try:
        openrazer_devices = list(openrazer.client.DeviceManager().devices)
    except Exception:
        openrazer_devices = []

    snapshots = []
    for detected in detect_all_fixture_instances():
        fixture = detected.fixture
        battery_supported, charging_supported = telemetry_capabilities(
            fixture.data
        )

        matched = None
        if battery_supported or charging_supported:
            try:
                identity = match_fixture_identity(fixture, openrazer_devices)
                matched = identity.device if identity.matched else None
            except Exception:
                matched = None

        snapshots.append(
            DeviceTelemetrySnapshot(
                instance_id=detected.instance_id,
                fixture_id=fixture.id,
                display_name=fixture.display_name,
                device_class=fixture.device_class,
                connected=True,
                battery_supported=battery_supported,
                battery=_battery_value(matched) if battery_supported else None,
                charging_supported=charging_supported,
                charging=_charging_value(matched) if charging_supported else None,
            )
        )

    snapshots.sort(key=lambda x: (x.device_class, x.display_name, x.instance_id))
    return snapshots
