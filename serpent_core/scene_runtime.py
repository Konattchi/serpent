from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from serpent_core.fixtures import find_fixture_by_id
from serpent_core.scene_application import RuntimeSnapshot, SceneApplicationError, SceneApplicationPlan, SceneOperation
from serpent_core.discovery import detect_all_fixture_instances
from serpent_core.backends.registry import create_backend
from serpent_core.device import build_device_model
from serpent_core.topology import build_lighting_topology

KEYBOARD_FIXTURE_ID = "razer-deathstalker-v2"
MOUSE_FIXTURE_ID = "razer-naga-v2-pro-wireless"
PROFILE_PATH = Path.home() / ".config" / "serpent" / "profile.json"


@dataclass(frozen=True)
class SerpentRuntimeSnapshot:
    profile_text: str
    owner: str


def _default_command_runner(command: list[str]) -> None:
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise SceneApplicationError(result.stdout.strip() or "Runtime command failed: " + " ".join(command))


def _default_owner_getter() -> str:
    from serpent_core.ownership import current_owner
    return current_owner()


def _default_owner_setter(owner: str) -> None:
    from serpent_core.ownership import set_owner
    set_owner(owner)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class SerpentSceneRuntime:
    def __init__(
        self,
        *,
        profile_path: Path = PROFILE_PATH,
        serpent_command: str = "serpent",
        command_runner: Callable[[list[str]], None] = _default_command_runner,
        owner_getter: Callable[[], str] = _default_owner_getter,
        owner_setter: Callable[[str], None] = _default_owner_setter,
    ) -> None:
        self.profile_path = Path(profile_path)
        self.serpent_command = serpent_command
        self.command_runner = command_runner
        self.owner_getter = owner_getter
        self.owner_setter = owner_setter

    def snapshot(self) -> RuntimeSnapshot:
        if not self.profile_path.is_file():
            raise SceneApplicationError(f"Serpent profile does not exist: {self.profile_path}")
        return RuntimeSnapshot(
            SerpentRuntimeSnapshot(
                profile_text=self.profile_path.read_text(encoding="utf-8"),
                owner=self.owner_getter(),
            )
        )

    def _load_profile(self) -> dict[str, object]:
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SceneApplicationError(f"Could not read Serpent profile: {exc}") from exc
        if not isinstance(data, dict):
            raise SceneApplicationError("Serpent profile root must be an object.")
        return data

    def _generic_profile_entry(self, instance_id: str) -> dict[str, object] | None:
        profile = self._load_profile()
        devices = profile.get("fixture_devices", {})
        if not isinstance(devices, dict):
            return None
        entry = devices.get(instance_id)
        return entry if isinstance(entry, dict) else None

    def _generic_fixture_for_target(self, instance_id: str):
        entry = self._generic_profile_entry(instance_id)
        if entry is None:
            raise SceneApplicationError(
                f"Scene device {instance_id!r} is not present in fixture_devices."
            )
        fixture_id = entry.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id:
            raise SceneApplicationError(
                f"Scene device {instance_id!r} has no fixture_id metadata."
            )
        return find_fixture_by_id(fixture_id)

    @staticmethod
    def _fixture_supports_effect(fixture, effect_id: str | None) -> bool:
        if effect_id is None:
            return False
        effects = fixture.data.get("effects", {})
        return isinstance(effects, dict) and effect_id in effects

    def validate_operation(self, operation: SceneOperation) -> None:
        allowed = {
            "enable-sync",
            "set-member-brightness",
            "disable-sync",
            "apply-device",
            "apply-zone",
            "set-linked",
        }
        if operation.kind not in allowed:
            raise SceneApplicationError(
                f"Unsupported scene runtime operation: {operation.kind!r}"
            )

        if operation.kind == "apply-device":
            if operation.target is None:
                raise SceneApplicationError("Device operations require a target.")
            if operation.target == KEYBOARD_FIXTURE_ID:
                fixture = find_fixture_by_id(KEYBOARD_FIXTURE_ID)
            else:
                fixture = self._generic_fixture_for_target(operation.target)
            if not self._fixture_supports_effect(fixture, operation.effect):
                raise SceneApplicationError(
                    f"{fixture.id} does not support fixture-native effect {operation.effect!r}."
                )

        if operation.kind == "apply-zone":
            if operation.target is None or ":" not in operation.target:
                raise SceneApplicationError("Zone operations require device:zone targets.")
            device_id, zone_id = operation.target.split(":", 1)
            if device_id == MOUSE_FIXTURE_ID:
                fixture = find_fixture_by_id(MOUSE_FIXTURE_ID)
            else:
                fixture = self._generic_fixture_for_target(device_id)
            device = build_device_model(fixture)
            topology = build_lighting_topology(device)
            if topology is None:
                raise SceneApplicationError(
                    f"{fixture.id} exposes no lighting topology."
                )
            topology.validate()
            if not any(region.id == zone_id for region in topology.regions):
                raise SceneApplicationError(
                    f"{fixture.id} has no topology region {zone_id!r}."
                )
            if not self._fixture_supports_effect(fixture, operation.effect):
                raise SceneApplicationError(
                    f"{fixture.id} does not support fixture-native effect {operation.effect!r}."
                )

        if operation.kind == "set-linked" and operation.target != MOUSE_FIXTURE_ID:
            raise SceneApplicationError(
                "Linked-zone mode is retained only for the legacy Naga personal profile."
            )

    def apply_operation(self, operation: SceneOperation) -> None:
        raise SceneApplicationError("SerpentSceneRuntime requires plan-aware commit.")

    @staticmethod
    def _append_effect_arguments(command: list[str], parameters: dict[str, object]) -> None:
        for key in ("colour1", "colour2"):
            value = parameters.get(key)
            if value is not None:
                command.extend([f"--{key}", *[str(component) for component in value]])
        if "speed" in parameters:
            command.extend(["--speed", str(parameters["speed"])])
        if "direction" in parameters:
            command.extend(["--direction", str(parameters["direction"])])

    def synchronized_command(self, plan: SceneApplicationPlan) -> list[str]:
        enable = next((op for op in plan.operations if op.kind == "enable-sync"), None)
        if enable is None or enable.effect is None:
            raise SceneApplicationError("Synchronized plan has no enable-sync operation.")

        command = [self.serpent_command, "sync", "enable", enable.effect]
        self._append_effect_arguments(command, enable.parameter_dict())

        for operation in plan.operations:
            if operation.kind != "set-member-brightness":
                continue
            if operation.target is None or operation.brightness is None:
                raise SceneApplicationError("Member-brightness operation is incomplete.")
            command.extend(["--member-brightness", operation.target, str(operation.brightness)])
        return command

    @staticmethod
    def _effect_settings(operation: SceneOperation) -> dict[str, object]:
        if operation.effect is None:
            raise SceneApplicationError(f"{operation.kind} has no effect.")
        settings: dict[str, object] = {"effect": operation.effect}
        settings.update(operation.parameter_dict())
        if operation.brightness is not None:
            settings["brightness"] = operation.brightness
        return settings

    def staged_individual_profile(self, plan: SceneApplicationPlan) -> dict[str, object]:
        profile = copy.deepcopy(self._load_profile())

        mouse = profile.setdefault("mouse", {})
        keyboard = profile.setdefault("keyboard", {})
        fixture_devices = profile.setdefault("fixture_devices", {})

        if not isinstance(mouse, dict) or not isinstance(keyboard, dict):
            raise SceneApplicationError(
                "Serpent profile mouse/keyboard sections must be objects."
            )
        if not isinstance(fixture_devices, dict):
            raise SceneApplicationError(
                "Serpent profile fixture_devices section must be an object."
            )

        mouse_zones = mouse.setdefault("zones", {})
        if not isinstance(mouse_zones, dict):
            raise SceneApplicationError("Serpent mouse zones section must be an object.")

        for operation in plan.operations:
            if operation.kind == "disable-sync":
                sync = profile.setdefault("sync", {})
                if isinstance(sync, dict):
                    sync["enabled"] = False
            elif operation.kind == "apply-device":
                assert operation.target is not None
                if operation.target == KEYBOARD_FIXTURE_ID:
                    keyboard.clear()
                    keyboard.update(self._effect_settings(operation))
                    continue
                fixture = self._generic_fixture_for_target(operation.target)
                current = fixture_devices.setdefault(operation.target, {})
                if not isinstance(current, dict):
                    current = {}
                    fixture_devices[operation.target] = current
                current["fixture_id"] = fixture.id
                current["settings"] = self._effect_settings(operation)
            elif operation.kind == "apply-zone":
                assert operation.target is not None
                device_id, zone_id = operation.target.split(":", 1)
                if device_id == MOUSE_FIXTURE_ID:
                    mouse_zones[zone_id] = self._effect_settings(operation)
                    continue
                fixture = self._generic_fixture_for_target(device_id)
                current = fixture_devices.setdefault(device_id, {})
                if not isinstance(current, dict):
                    current = {}
                    fixture_devices[device_id] = current
                current["fixture_id"] = fixture.id
                zones = current.setdefault("zones", {})
                if not isinstance(zones, dict):
                    zones = {}
                    current["zones"] = zones
                zones[zone_id] = self._effect_settings(operation)
            elif operation.kind == "set-linked":
                mouse["linked"] = bool(operation.linked)

        return profile

    def _apply_generic_profile_hardware(self) -> None:
        # Apply connected fixture-native generic personal settings.
        profile = self._load_profile()
        fixture_devices = profile.get("fixture_devices", {})
        if not isinstance(fixture_devices, dict):
            return

        detected = {
            item.instance_id: item
            for item in detect_all_fixture_instances()
        }

        for instance_id, saved in fixture_devices.items():
            if not isinstance(instance_id, str) or not isinstance(saved, dict):
                continue
            live = detected.get(instance_id)
            if live is None:
                continue

            fixture_effects = live.fixture.data.get("effects", {})
            if not isinstance(fixture_effects, dict):
                fixture_effects = {}

            backend = create_backend(live.fixture, live.sysfs_path)

            settings = saved.get("settings")
            if isinstance(settings, dict):
                effect = settings.get("effect")
                if isinstance(effect, str) and effect in fixture_effects:
                    backend.apply(effect, settings)

            zones = saved.get("zones")
            if isinstance(zones, dict):
                for zone_id, zone_settings in zones.items():
                    if not isinstance(zone_id, str) or not isinstance(zone_settings, dict):
                        continue
                    effect = zone_settings.get("effect")
                    if isinstance(effect, str) and effect in fixture_effects:
                        backend.apply_zone(zone_id, effect, zone_settings)

    def _commit_group_scene(self, plan: SceneApplicationPlan) -> None:
        groups = getattr(plan, "groups", None)
        if not groups:
            raise SceneApplicationError("Group-aware synchronized plan has no groups.")

        try:
            from serpent_core.sync_groups import validate_groups
            validate_groups(list(groups))
        except Exception as exc:
            raise SceneApplicationError(f"Invalid synchronized scene groups: {exc}") from exc

        profile = copy.deepcopy(self._load_profile())
        sync = profile.setdefault("sync", {})
        if not isinstance(sync, dict):
            raise SceneApplicationError("Serpent profile sync section must be an object.")

        sync["groups"] = [copy.deepcopy(group) for group in groups]
        sync["enabled"] = True

        _atomic_write(
            self.profile_path,
            json.dumps(profile, indent=4) + "\n",
        )

        # _default_command_runner intentionally returns None, so do not try
        # to infer state from `serpent sync status` output here. Read the
        # actual ownership + systemd state directly.
        service_state = subprocess.run(
            [
                "systemctl",
                "--user",
                "is-active",
                "serpent-sync.service",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()

        active_sync = (
            self.owner_getter() == "sync"
            and service_state == "active"
        )

        if active_sync:
            self.command_runner(
                [self.serpent_command, "sync", "reload-engine"]
            )
            return

        # If Sync is not currently active, start the service directly after
        # writing sync.enabled + sync.groups. Do not route through legacy
        # `sync enable <effect>`, which would rewrite single-effect fields.
        self.command_runner(
            ["systemctl", "--user", "start", "serpent-sync.service"]
        )

    def commit_plan(self, plan: SceneApplicationPlan) -> None:
        if plan.mode == "synchronized":
            if getattr(plan, "groups", None):
                self._commit_group_scene(plan)
                return
            self.command_runner(self.synchronized_command(plan))
            return

        if plan.mode != "individual":
            raise SceneApplicationError(
                f"Unsupported application mode: {plan.mode!r}"
            )

        self.command_runner([self.serpent_command, "sync", "disable"])
        profile = self.staged_individual_profile(plan)
        _atomic_write(
            self.profile_path,
            json.dumps(profile, indent=4) + "\n",
        )

        self.command_runner(
            [self.serpent_command, "keyboard", "apply-profile"]
        )
        self.command_runner(
            ["systemctl", "--user", "restart", "serpent-individual.service"]
        )
        self._apply_generic_profile_hardware()

    def restore(self, snapshot: RuntimeSnapshot) -> None:
        payload = snapshot.payload
        if not isinstance(payload, SerpentRuntimeSnapshot):
            raise SceneApplicationError("Unexpected Serpent runtime snapshot.")

        _atomic_write(self.profile_path, payload.profile_text)
        self.owner_setter(payload.owner)

        if payload.owner == "sync":
            self.command_runner(["systemctl", "--user", "restart", "serpent-sync.service"])
        else:
            self.command_runner(["systemctl", "--user", "stop", "serpent-sync.service"])
            self.command_runner(["systemctl", "--user", "restart", "serpent-individual.service"])
            self.command_runner([self.serpent_command, "keyboard", "apply-profile"])
        self._apply_generic_profile_hardware()


__all__ = [
    "KEYBOARD_FIXTURE_ID",
    "MOUSE_FIXTURE_ID",
    "PROFILE_PATH",
    "SerpentRuntimeSnapshot",
    "SerpentSceneRuntime",
]
