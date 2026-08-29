from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import copy
import re

from serpent_core.effects import effect_ids, get_effect_definition, get_effect_plugin_spec

SCENE_SCHEMA_VERSION = 1
SCENE_MODES = ("individual", "synchronized")
_EFFECT_PARAMETER_KEYS = frozenset(("colour1", "colour2", "speed", "direction"))
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_MEMBER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._-]*$")


class SceneValidationError(ValueError):
    """Raised when serialized scene data violates the scene contract."""


def _require_object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneValidationError(f"{label} must be an object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = set(),
    label: str,
) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise SceneValidationError(
            f"{label} is missing required field(s): {', '.join(sorted(missing))}."
        )
    if unknown:
        raise SceneValidationError(
            f"{label} contains unknown field(s): {', '.join(sorted(unknown))}."
        )


def _validate_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise SceneValidationError(
            f"{label} must be a non-empty lowercase identifier using "
            "letters, digits, '.', '_' or '-'."
        )
    return value
def _validate_device_id(value: object) -> str:
    if isinstance(value, str) and value.count("@") == 1:
        fixture_id, instance_id = value.split("@", 1)
        fixture_id = _validate_id(fixture_id, "Device fixture id")
        instance_id = _validate_id(instance_id, "Device instance id")
        return f"{fixture_id}@{instance_id}"
    return _validate_id(value, "Device id")




def _validate_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneValidationError("Scene name must be a non-empty string.")
    return value.strip()


def _validate_colour(value: object, label: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, int) for v in value)
    ):
        raise SceneValidationError(f"{label} must contain exactly three integer RGB values.")
    colour = tuple(value)
    if any(v < 0 or v > 255 for v in colour):
        raise SceneValidationError(f"{label} RGB values must be between 0 and 255.")
    return colour  # type: ignore[return-value]


def _validate_brightness(value: object, label: str = "Brightness") -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneValidationError(f"{label} must be a number.")
    brightness = float(value)
    if brightness < 0 or brightness > 100:
        raise SceneValidationError(f"{label} must be between 0 and 100.")
    if not brightness.is_integer():
        raise SceneValidationError(f"{label} must be a whole percentage.")
    return int(brightness)


def _validate_speed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SceneValidationError("Effect speed must be an integer of at least 1.")
    return value


def _validate_direction(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SceneValidationError("Effect direction must be an integer.")
    return value
def _validate_plugin_parameter(spec, value: object, label: str) -> object:
    kind = spec.kind
    if kind == "colour":
        return _validate_colour(value, label)
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SceneValidationError(f"{label} must be an integer.")
        if spec.minimum is not None and value < spec.minimum:
            raise SceneValidationError(f"{label} is below its minimum.")
        if spec.maximum is not None and value > spec.maximum:
            raise SceneValidationError(f"{label} is above its maximum.")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SceneValidationError(f"{label} must be numeric.")
        if spec.minimum is not None and value < spec.minimum:
            raise SceneValidationError(f"{label} is below its minimum.")
        if spec.maximum is not None and value > spec.maximum:
            raise SceneValidationError(f"{label} is above its maximum.")
        return value
    if kind == "choice":
        if value not in spec.choices:
            raise SceneValidationError(f"{label} is not one of the supported choices.")
        return copy.deepcopy(value)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise SceneValidationError(f"{label} must be boolean.")
        return value
    if kind == "string":
        if not isinstance(value, str):
            raise SceneValidationError(f"{label} must be a string.")
        return value
    raise SceneValidationError(f"{label} uses unsupported parameter kind {kind!r}.")




@dataclass(frozen=True)
class SceneEffect:
    id: str
    parameters: tuple[tuple[str, object], ...] = ()

    def parameter_dict(self) -> dict[str, object]:
        return {key: copy.deepcopy(value) for key, value in self.parameters}


@dataclass(frozen=True)
class SceneMember:
    id: str
    brightness: int


@dataclass(frozen=True)
class SceneZone:
    id: str
    effect: SceneEffect
    brightness: int


@dataclass(frozen=True)
class SceneDevice:
    id: str
    effect: SceneEffect | None = None
    brightness: int | None = None
    linked: bool | None = None
    zones: tuple[SceneZone, ...] = ()


@dataclass(frozen=True)
class Scene:
    schema_version: int
    id: str
    name: str
    mode: str
    effect: SceneEffect | None = None
    members: tuple[SceneMember, ...] = ()
    devices: tuple[SceneDevice, ...] = ()
    groups: tuple[dict[str, object], ...] = ()


def _effect_from_dict(raw: object, *, synchronized: bool) -> SceneEffect:
    data = _require_object(raw, "Scene effect")
    _require_exact_keys(
        data,
        required={"id", "parameters"},
        optional=set(),
        label="Scene effect",
    )
    effect_id = _validate_id(data["id"], "Effect id")
    if effect_id not in effect_ids():
        raise SceneValidationError(f"Unknown effect id: {effect_id!r}.")

    params_raw = _require_object(data["parameters"], "Effect parameters")

    try:
        plugin_spec = get_effect_plugin_spec(effect_id)
    except Exception:
        plugin_spec = None

    if plugin_spec is not None:
        by_id = {parameter.id: parameter for parameter in plugin_spec.parameters}
        unknown = set(params_raw) - set(by_id)
        if unknown:
            raise SceneValidationError(
                "Effect parameters contain unknown field(s): "
                + ", ".join(sorted(unknown))
                + "."
            )
        params: list[tuple[str, object]] = []
        for key, value in params_raw.items():
            spec = by_id[key]
            normalized = _validate_plugin_parameter(
                spec,
                value,
                f"Effect parameter {key!r}",
            )
            params.append((key, normalized))
        return SceneEffect(effect_id, tuple(params))

    definition = get_effect_definition(effect_id) if synchronized else None
    params: list[tuple[str, object]] = []
    for key in ("colour1", "colour2", "speed", "direction"):
        if key not in params_raw:
            continue
        value = params_raw[key]
        if key.startswith("colour"):
            normalized: object = _validate_colour(value, key)
        elif key == "speed":
            normalized = _validate_speed(value)
        else:
            normalized = _validate_direction(value)
            if (
                synchronized
                and definition is not None
                and definition.directions
                and normalized not in definition.directions
            ):
                raise SceneValidationError(
                    f"Direction {normalized} is not supported by {effect_id!r}."
                )
        params.append((key, normalized))
    return SceneEffect(effect_id, tuple(params))


def _member_from_item(member_id: object, raw: object) -> SceneMember:
    if not isinstance(member_id, str) or not _MEMBER_RE.fullmatch(member_id):
        raise SceneValidationError(
            f"Invalid synchronized member id: {member_id!r}."
        )
    data = _require_object(raw, f"Member {member_id!r}")
    _require_exact_keys(data, required={"brightness"}, label=f"Member {member_id!r}")
    return SceneMember(
        id=member_id,
        brightness=_validate_brightness(
            data["brightness"], f"Member {member_id!r} brightness"
        ),
    )


def _device_from_item(device_id: object, raw: object) -> SceneDevice:
    device_id = _validate_device_id(device_id)
    data = _require_object(raw, f"Device {device_id!r}")
    _require_exact_keys(
        data,
        required=set(),
        optional={"effect", "brightness", "linked", "zones"},
        label=f"Device {device_id!r}",
    )

    effect = (
        _effect_from_dict(data["effect"], synchronized=False)
        if "effect" in data
        else None
    )
    brightness = (
        _validate_brightness(data["brightness"], f"Device {device_id!r} brightness")
        if "brightness" in data
        else None
    )
    linked = data.get("linked")
    if linked is not None and not isinstance(linked, bool):
        raise SceneValidationError(f"Device {device_id!r} linked must be boolean.")

    zones: list[SceneZone] = []
    if "zones" in data:
        raw_zones = _require_object(data["zones"], f"Device {device_id!r} zones")
        for zone_id, zone_raw in raw_zones.items():
            zone_id = _validate_id(zone_id, "Zone id")
            zone_data = _require_object(zone_raw, f"Zone {zone_id!r}")
            _require_exact_keys(
                zone_data,
                required={"effect", "brightness"},
                label=f"Zone {zone_id!r}",
            )
            zones.append(
                SceneZone(
                    id=zone_id,
                    effect=_effect_from_dict(zone_data["effect"], synchronized=False),
                    brightness=_validate_brightness(
                        zone_data["brightness"], f"Zone {zone_id!r} brightness"
                    ),
                )
            )

    if effect is None and not zones:
        raise SceneValidationError(
            f"Device {device_id!r} must define an effect or at least one zone."
        )
    if effect is not None and zones:
        raise SceneValidationError(
            f"Device {device_id!r} cannot define both a device effect and zones."
        )
    if zones and linked is None:
        linked = False

    return SceneDevice(
        id=device_id,
        effect=effect,
        brightness=brightness,
        linked=linked,
        zones=tuple(zones),
    )


def scene_from_dict(raw: object) -> Scene:
    data = _require_object(raw, "Scene")
    _require_exact_keys(
        data,
        required={"schema_version", "id", "name", "mode"},
        optional={"effect", "members", "devices", "groups"},
        label="Scene",
    )

    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise SceneValidationError("Scene schema_version must be an integer.")
    if version != SCENE_SCHEMA_VERSION:
        raise SceneValidationError(
            f"Unsupported scene schema version: {version!r}; "
            f"expected {SCENE_SCHEMA_VERSION}."
        )

    scene_id = _validate_id(data["id"], "Scene id")
    name = _validate_name(data["name"])
    mode = data["mode"]
    if mode not in SCENE_MODES:
        raise SceneValidationError(
            f"Scene mode must be one of: {', '.join(SCENE_MODES)}."
        )

    if mode == "synchronized":
        if "devices" in data:
            raise SceneValidationError("Synchronized scenes cannot contain devices.")

        if "groups" in data:
            if "effect" in data or "members" in data:
                raise SceneValidationError(
                    "Group-aware synchronized scenes cannot also contain legacy effect/members."
                )
            groups_raw = data["groups"]
            if not isinstance(groups_raw, list) or not groups_raw:
                raise SceneValidationError("Synchronized scene groups must be a non-empty list.")
            try:
                from serpent_core.sync_groups import validate_groups
                validate_groups(groups_raw)
            except Exception as exc:
                raise SceneValidationError(f"Invalid synchronized scene groups: {exc}") from exc
            return Scene(
                version,
                scene_id,
                name,
                mode,
                groups=tuple(copy.deepcopy(groups_raw)),
            )

        if "effect" not in data or "members" not in data:
            raise SceneValidationError(
                "Synchronized scenes require groups or legacy effect and members."
            )
        effect = _effect_from_dict(data["effect"], synchronized=True)
        members_raw = _require_object(data["members"], "Scene members")
        if not members_raw:
            raise SceneValidationError("Synchronized scenes require at least one member.")
        members = tuple(
            _member_from_item(member_id, member_raw)
            for member_id, member_raw in members_raw.items()
        )
        return Scene(version, scene_id, name, mode, effect=effect, members=members)

    if "effect" in data or "members" in data or "groups" in data:
        raise SceneValidationError(
            "Individual scenes cannot contain synchronized effect/members/groups."
        )

    devices_raw = _require_object(data.get("devices"), "Scene devices")
    if not devices_raw:
        raise SceneValidationError("Individual scenes require at least one device.")
    devices = tuple(
        _device_from_item(device_id, device_raw)
        for device_id, device_raw in devices_raw.items()
    )
    return Scene(version, scene_id, name, mode, devices=devices)


def _effect_to_dict(effect: SceneEffect) -> dict[str, object]:
    params: dict[str, object] = {}
    for key, value in effect.parameters:
        if isinstance(value, tuple):
            params[key] = list(value)
        else:
            params[key] = copy.deepcopy(value)
    return {"id": effect.id, "parameters": params}


def scene_to_dict(scene: Scene) -> dict[str, object]:
    validate_scene(scene)
    result: dict[str, object] = {
        "schema_version": scene.schema_version,
        "id": scene.id,
        "name": scene.name,
        "mode": scene.mode,
    }

    if scene.mode == "synchronized":
        if scene.groups:
            result["groups"] = [copy.deepcopy(group) for group in scene.groups]
        else:
            assert scene.effect is not None
            result["effect"] = _effect_to_dict(scene.effect)
            result["members"] = {
                member.id: {"brightness": member.brightness}
                for member in scene.members
            }
    else:
        devices: dict[str, object] = {}
        for device in scene.devices:
            item: dict[str, object] = {}
            if device.effect is not None:
                item["effect"] = _effect_to_dict(device.effect)
            if device.brightness is not None:
                item["brightness"] = device.brightness
            if device.linked is not None:
                item["linked"] = device.linked
            if device.zones:
                item["zones"] = {
                    zone.id: {
                        "effect": _effect_to_dict(zone.effect),
                        "brightness": zone.brightness,
                    }
                    for zone in device.zones
                }
            devices[device.id] = item
        result["devices"] = devices

    return result


def validate_scene(scene: Scene) -> None:
    if not isinstance(scene, Scene):
        raise SceneValidationError("Expected a Scene instance.")
    raw: dict[str, object] = {
        "schema_version": scene.schema_version,
        "id": scene.id,
        "name": scene.name,
        "mode": scene.mode,
    }
    if scene.mode == "synchronized":
        if scene.groups:
            raw["groups"] = [copy.deepcopy(group) for group in scene.groups]
        else:
            if scene.effect is not None:
                raw["effect"] = _effect_to_dict(scene.effect)
            raw["members"] = {
                member.id: {"brightness": member.brightness}
                for member in scene.members
            }
    elif scene.mode == "individual":
        devices: dict[str, object] = {}
        for device in scene.devices:
            item: dict[str, object] = {}
            if device.effect is not None:
                item["effect"] = _effect_to_dict(device.effect)
            if device.brightness is not None:
                item["brightness"] = device.brightness
            if device.linked is not None:
                item["linked"] = device.linked
            if device.zones:
                item["zones"] = {
                    zone.id: {
                        "effect": _effect_to_dict(zone.effect),
                        "brightness": zone.brightness,
                    }
                    for zone in device.zones
                }
            devices[device.id] = item
        raw["devices"] = devices
    scene_from_dict(raw)


__all__ = [
    "SCENE_SCHEMA_VERSION",
    "SCENE_MODES",
    "Scene",
    "SceneDevice",
    "SceneEffect",
    "SceneMember",
    "SceneValidationError",
    "SceneZone",
    "scene_from_dict",
    "scene_to_dict",
    "validate_scene",
]
