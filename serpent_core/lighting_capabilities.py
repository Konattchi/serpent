from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class LightingCapabilityError(ValueError):
    pass


TOPOLOGY_KINDS = {
    "matrix",
    "linear",
    "multi-channel",
    "semantic-zones",
    "none",
}

TRANSPORT_KINDS = {
    "software-frame",
    "hardware-native",
    "hybrid",
    "none",
}

SEMANTIC_PURPOSES = {
    "normal",
    "charging",
    "fast-charging",
    "fully-charged",
}


@dataclass(frozen=True)
class LightingChannel:
    id: str
    led_count: int
    rows: int | None = None
    columns: int | None = None


@dataclass(frozen=True)
class SemanticLightingZone:
    id: str
    purpose: str
    independently_controllable: bool


@dataclass(frozen=True)
class LightingCapability:
    topology: str
    transport: str
    channels: tuple[LightingChannel, ...] = ()
    semantic_zones: tuple[SemanticLightingZone, ...] = ()

    @property
    def has_lighting(self) -> bool:
        return self.topology != "none" and self.transport != "none"


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LightingCapabilityError(f"{field} must be a non-empty string.")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(character not in allowed for character in value):
        raise LightingCapabilityError(
            f"{field} must use lowercase letters, digits, '.', '_' or '-'."
        )
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LightingCapabilityError(f"{field} must be a positive integer.")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _parse_channel(raw: object) -> LightingChannel:
    if not isinstance(raw, Mapping):
        raise LightingCapabilityError("lighting.channels entries must be objects.")

    channel_id = _identifier(raw.get("id"), "lighting channel id")
    led_count = _positive_int(
        raw.get("led_count"),
        f"lighting channel {channel_id}.led_count",
    )
    rows = _optional_positive_int(
        raw.get("rows"),
        f"lighting channel {channel_id}.rows",
    )
    columns = _optional_positive_int(
        raw.get("columns"),
        f"lighting channel {channel_id}.columns",
    )

    if (rows is None) != (columns is None):
        raise LightingCapabilityError(
            f"lighting channel {channel_id!r} must define both rows and columns or neither."
        )
    if rows is not None and columns is not None and rows * columns != led_count:
        raise LightingCapabilityError(
            f"lighting channel {channel_id!r} geometry {rows}x{columns} "
            f"does not match led_count {led_count}."
        )

    return LightingChannel(
        id=channel_id,
        led_count=led_count,
        rows=rows,
        columns=columns,
    )


def _parse_semantic_zone(raw: object) -> SemanticLightingZone:
    if not isinstance(raw, Mapping):
        raise LightingCapabilityError(
            "lighting.semantic_zones entries must be objects."
        )

    zone_id = _identifier(raw.get("id"), "semantic lighting zone id")
    purpose = _identifier(
        raw.get("purpose"),
        f"semantic lighting zone {zone_id}.purpose",
    )
    independently_controllable = raw.get("independently_controllable", False)

    if not isinstance(independently_controllable, bool):
        raise LightingCapabilityError(
            f"semantic lighting zone {zone_id!r}.independently_controllable "
            "must be boolean."
        )

    return SemanticLightingZone(
        id=zone_id,
        purpose=purpose,
        independently_controllable=independently_controllable,
    )


def parse_lighting_capability(
    fixture: Mapping[str, Any],
) -> LightingCapability | None:
    raw = fixture.get("lighting")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise LightingCapabilityError("fixture lighting must be an object.")

    topology = str(raw.get("topology", "")).strip()
    transport = str(raw.get("transport", "")).strip()

    if topology not in TOPOLOGY_KINDS:
        raise LightingCapabilityError(
            f"lighting.topology must be one of {sorted(TOPOLOGY_KINDS)}."
        )
    if transport not in TRANSPORT_KINDS:
        raise LightingCapabilityError(
            f"lighting.transport must be one of {sorted(TRANSPORT_KINDS)}."
        )

    channels_raw = raw.get("channels", ())
    semantic_raw = raw.get("semantic_zones", ())

    if not isinstance(channels_raw, (list, tuple)):
        raise LightingCapabilityError("lighting.channels must be an array.")
    if not isinstance(semantic_raw, (list, tuple)):
        raise LightingCapabilityError("lighting.semantic_zones must be an array.")

    channels = tuple(_parse_channel(item) for item in channels_raw)
    semantic_zones = tuple(_parse_semantic_zone(item) for item in semantic_raw)

    channel_ids = [item.id for item in channels]
    if len(set(channel_ids)) != len(channel_ids):
        raise LightingCapabilityError("lighting channel ids must be unique.")

    semantic_ids = [item.id for item in semantic_zones]
    if len(set(semantic_ids)) != len(semantic_ids):
        raise LightingCapabilityError("semantic lighting zone ids must be unique.")

    if topology == "none":
        if channels or semantic_zones:
            raise LightingCapabilityError(
                "lighting.topology 'none' cannot define channels or semantic zones."
            )
        if transport != "none":
            raise LightingCapabilityError(
                "lighting.topology 'none' requires lighting.transport 'none'."
            )

    if topology == "linear" and len(channels) != 1:
        raise LightingCapabilityError(
            "lighting.topology 'linear' requires exactly one channel."
        )

    if topology == "multi-channel" and len(channels) < 2:
        raise LightingCapabilityError(
            "lighting.topology 'multi-channel' requires at least two channels."
        )

    if topology == "semantic-zones" and not semantic_zones:
        raise LightingCapabilityError(
            "lighting.topology 'semantic-zones' requires semantic_zones."
        )

    if topology == "matrix":
        capabilities = fixture.get("capabilities")
        matrix = (
            capabilities.get("matrix")
            if isinstance(capabilities, Mapping)
            else None
        )
        if matrix is None and not channels:
            raise LightingCapabilityError(
                "lighting.topology 'matrix' requires existing capabilities.matrix "
                "or an explicit lighting channel."
            )

    return LightingCapability(
        topology=topology,
        transport=transport,
        channels=channels,
        semantic_zones=semantic_zones,
    )


def validate_lighting_capability(
    fixture: Mapping[str, Any],
) -> None:
    parse_lighting_capability(fixture)


__all__ = [
    "LightingCapability",
    "LightingCapabilityError",
    "LightingChannel",
    "SemanticLightingZone",
    "SEMANTIC_PURPOSES",
    "TOPOLOGY_KINDS",
    "TRANSPORT_KINDS",
    "parse_lighting_capability",
    "validate_lighting_capability",
]
