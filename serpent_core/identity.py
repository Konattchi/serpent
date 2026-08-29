#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from serpent_core.fixtures import Fixture


class IdentityPolicy(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    IGNORED = "ignored"


class MatchConfidence(str, Enum):
    EXACT = "exact"
    FALLBACK = "fallback"
    NAME_ONLY = "name-only"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class MatchResult:
    fixture: Fixture
    device: Any | None
    matched: bool
    confidence: MatchConfidence
    reason: str
    actual_serial: str | None = None
    candidates: int = 0

    @property
    def used_fallback(self) -> bool:
        return self.confidence == MatchConfidence.FALLBACK


def identity_policy(fixture: Fixture) -> IdentityPolicy:
    detection = fixture.data.get("detection", {})

    if not isinstance(detection, dict):
        return IdentityPolicy.IGNORED

    configured = detection.get("serial_policy")

    if configured is None:
        # Backward compatibility:
        # fixtures with a serial used strict matching before Basilisk.
        return (
            IdentityPolicy.REQUIRED
            if detection.get("serial")
            else IdentityPolicy.IGNORED
        )

    try:
        return IdentityPolicy(str(configured))
    except ValueError as exc:
        allowed = ", ".join(
            policy.value
            for policy in IdentityPolicy
        )
        raise ValueError(
            f"{fixture.id}: detection.serial_policy must be "
            f"one of: {allowed}."
        ) from exc


def generated_serial_prefixes(
    fixture: Fixture,
) -> tuple[str, ...]:
    detection = fixture.data.get("detection", {})

    if not isinstance(detection, dict):
        return ("UNKNOWN_",)

    raw = detection.get(
        "generated_serial_prefixes",
        ("UNKNOWN_",),
    )

    if isinstance(raw, str):
        raw = (raw,)

    if not isinstance(raw, Iterable):
        raise ValueError(
            f"{fixture.id}: generated_serial_prefixes "
            "must be a sequence."
        )

    prefixes = tuple(
        str(prefix)
        for prefix in raw
        if str(prefix)
    )

    return prefixes or ("UNKNOWN_",)


def normalize_serial(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def is_generated_serial(
    fixture: Fixture,
    serial: Any,
) -> bool:
    value = normalize_serial(serial)

    if not value:
        return True

    return any(
        value.startswith(prefix)
        for prefix in generated_serial_prefixes(fixture)
    )


def _matching_name_devices(
    fixture: Fixture,
    devices: Iterable[Any],
) -> list[Any]:
    detection = fixture.data.get("detection", {})

    if not isinstance(detection, dict):
        detection = {}

    expected_name = detection.get(
        "openrazer_name_contains"
    )

    result: list[Any] = []

    for device in devices:
        actual_name = str(
            getattr(device, "name", "")
        )

        if (
            expected_name is None
            or str(expected_name) in actual_name
        ):
            result.append(device)

    return result


def match_fixture_identity(
    fixture: Fixture,
    devices: Iterable[Any],
) -> MatchResult:
    """Match a fixture to an OpenRazer device.

    USB-ID and sysfs endpoint matching remain the responsibility of
    discovery.py. This function resolves identity among OpenRazer
    candidates using name and fixture-declared serial policy.
    """

    candidates = _matching_name_devices(
        fixture,
        devices,
    )
    policy = identity_policy(fixture)

    detection = fixture.data.get("detection", {})

    if not isinstance(detection, dict):
        detection = {}

    expected_serial = normalize_serial(
        detection.get("serial")
    )

    if not candidates:
        return MatchResult(
            fixture=fixture,
            device=None,
            matched=False,
            confidence=MatchConfidence.NONE,
            reason="No OpenRazer device matched the expected name.",
            candidates=0,
        )

    if policy == IdentityPolicy.IGNORED:
        if len(candidates) == 1:
            device = candidates[0]
            return MatchResult(
                fixture=fixture,
                device=device,
                matched=True,
                confidence=MatchConfidence.NAME_ONLY,
                reason="Serial matching is disabled by the fixture.",
                actual_serial=normalize_serial(
                    getattr(device, "serial", "")
                ),
                candidates=1,
            )

        return MatchResult(
            fixture=fixture,
            device=None,
            matched=False,
            confidence=MatchConfidence.AMBIGUOUS,
            reason=(
                "Multiple OpenRazer devices matched the name while "
                "serial matching was disabled."
            ),
            candidates=len(candidates),
        )

    exact = [
        device
        for device in candidates
        if (
            expected_serial
            and normalize_serial(
                getattr(device, "serial", "")
            ) == expected_serial
        )
    ]

    if len(exact) == 1:
        device = exact[0]
        return MatchResult(
            fixture=fixture,
            device=device,
            matched=True,
            confidence=MatchConfidence.EXACT,
            reason="The configured serial matched exactly.",
            actual_serial=expected_serial,
            candidates=len(candidates),
        )

    if len(exact) > 1:
        return MatchResult(
            fixture=fixture,
            device=None,
            matched=False,
            confidence=MatchConfidence.AMBIGUOUS,
            reason=(
                "Multiple OpenRazer devices reported the same "
                "configured serial."
            ),
            candidates=len(exact),
        )

    if policy == IdentityPolicy.REQUIRED:
        actual_serials = ", ".join(
            normalize_serial(
                getattr(device, "serial", "")
            )
            or "<missing>"
            for device in candidates
        )

        return MatchResult(
            fixture=fixture,
            device=None,
            matched=False,
            confidence=MatchConfidence.NONE,
            reason=(
                f"Required serial {expected_serial!r} did not match; "
                f"candidate serials: {actual_serials}."
            ),
            candidates=len(candidates),
        )

    # Preferred policy permits only missing/generated identities as a
    # fallback. A different real serial is never silently accepted.
    fallback = [
        device
        for device in candidates
        if is_generated_serial(
            fixture,
            getattr(device, "serial", ""),
        )
    ]

    if len(fallback) == 1:
        device = fallback[0]
        serial = normalize_serial(
            getattr(device, "serial", "")
        )

        return MatchResult(
            fixture=fixture,
            device=device,
            matched=True,
            confidence=MatchConfidence.FALLBACK,
            reason=(
                "The configured serial was unavailable, so Serpent "
                "matched by OpenRazer name after sysfs USB-ID "
                "discovery."
            ),
            actual_serial=serial or None,
            candidates=len(candidates),
        )

    if len(fallback) > 1:
        return MatchResult(
            fixture=fixture,
            device=None,
            matched=False,
            confidence=MatchConfidence.AMBIGUOUS,
            reason=(
                "Multiple generated-serial devices matched the "
                "fixture name."
            ),
            candidates=len(fallback),
        )

    actual_serials = ", ".join(
        normalize_serial(
            getattr(device, "serial", "")
        )
        or "<missing>"
        for device in candidates
    )

    return MatchResult(
        fixture=fixture,
        device=None,
        matched=False,
        confidence=MatchConfidence.NONE,
        reason=(
            "The configured serial was not present, and the matching "
            "device reported a different real serial rather than a "
            f"generated identity: {actual_serials}."
        ),
        candidates=len(candidates),
    )
