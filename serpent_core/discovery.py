#!/usr/bin/env python3

from __future__ import annotations

import hashlib

from dataclasses import dataclass
from pathlib import Path

from serpent_core.fixtures import Fixture, load_all_fixtures
from serpent_core.physical_identity import stable_instance_id


SYSFS_HID_ROOT = Path("/sys/bus/hid/devices")


@dataclass(frozen=True)
class DetectedFixture:
    fixture: Fixture
    sysfs_path: Path

    @property
    def instance_id(self) -> str:
        return stable_instance_id(
            self.fixture.id,
            self.sysfs_path,
        )


def normalize_usb_id(value: str) -> str:
    return value.replace(":", "").lower()


def sysfs_paths_for_fixture(fixture: Fixture) -> list[Path]:
    usb = fixture.data["usb"]

    vendor = str(usb["vendor_id"]).lower()
    product = str(usb["product_id"]).lower()

    matches = []

    for path in sorted(SYSFS_HID_ROOT.iterdir()):
        name = path.name.lower()

        if f"{vendor}:{product}" in name:
            matches.append(path)

    return matches


def fixture_required_endpoint(fixture: Fixture) -> str:
    backend = fixture.data.get("backend", {})

    endpoint = backend.get("sysfs_required_endpoint")

    if not endpoint:
        raise ValueError(
            f"Fixture {fixture.id} has no "
            "backend.sysfs_required_endpoint."
        )

    return str(endpoint)


def detect_fixture_instances(fixture: Fixture) -> list[DetectedFixture]:
    required_endpoint = fixture_required_endpoint(fixture)
    return [DetectedFixture(fixture=fixture, sysfs_path=path) for path in sysfs_paths_for_fixture(fixture) if (path / required_endpoint).exists()]

def detect_fixture(fixture: Fixture) -> DetectedFixture | None:
    detected = detect_fixture_instances(fixture)
    return detected[0] if detected else None


def _detect_all_fixture_instances_endpoint_level() -> list[DetectedFixture]:
    # Return every detected physical instance for every loaded fixture.
    detected: list[DetectedFixture] = []

    for fixture in load_all_fixtures():
        detected.extend(detect_fixture_instances(fixture))

    return detected


def detect_all_fixture_instances() -> list[DetectedFixture]:
    seen: set[str] = set()
    result: list[DetectedFixture] = []

    for detected in _detect_all_fixture_instances_endpoint_level():
        identity = detected.instance_id

        if identity in seen:
            continue

        seen.add(identity)
        result.append(detected)

    return result


def detect_all_fixtures() -> list[DetectedFixture]:
    detected: list[DetectedFixture] = []

    for fixture in load_all_fixtures():
        result = detect_fixture(fixture)

        if result is not None:
            detected.append(result)

    return detected
