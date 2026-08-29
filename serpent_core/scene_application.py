from __future__ import annotations

import copy

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from serpent_core.scenes import Scene, SceneDevice, SceneEffect, validate_scene


class SceneApplicationError(RuntimeError):
    """Raised when a scene cannot be planned or committed safely."""


@dataclass(frozen=True)
class SceneOperation:
    kind: str
    target: str | None = None
    effect: str | None = None
    parameters: tuple[tuple[str, object], ...] = ()
    brightness: int | None = None
    linked: bool | None = None

    def parameter_dict(self) -> dict[str, object]:
        return dict(self.parameters)


@dataclass(frozen=True)
class SceneApplicationPlan:
    scene_id: str
    scene_name: str
    mode: str
    operations: tuple[SceneOperation, ...]
    groups: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class RuntimeSnapshot:
    payload: object


class SceneRuntime(Protocol):
    def snapshot(self) -> RuntimeSnapshot: ...
    def validate_operation(self, operation: SceneOperation) -> None: ...
    def apply_operation(self, operation: SceneOperation) -> None: ...
    def restore(self, snapshot: RuntimeSnapshot) -> None: ...


def _effect_operation(
    kind: str,
    effect: SceneEffect,
    *,
    target: str | None = None,
    brightness: int | None = None,
    linked: bool | None = None,
) -> SceneOperation:
    return SceneOperation(
        kind=kind,
        target=target,
        effect=effect.id,
        parameters=effect.parameters,
        brightness=brightness,
        linked=linked,
    )


def _plan_individual_device(device: SceneDevice) -> tuple[SceneOperation, ...]:
    result: list[SceneOperation] = []

    if device.effect is not None:
        result.append(
            _effect_operation(
                "apply-device",
                device.effect,
                target=device.id,
                brightness=device.brightness,
                linked=device.linked,
            )
        )
        return tuple(result)

    for zone in device.zones:
        result.append(
            _effect_operation(
                "apply-zone",
                zone.effect,
                target=f"{device.id}:{zone.id}",
                brightness=zone.brightness,
            )
        )

    if device.linked is not None:
        result.append(
            SceneOperation(
                kind="set-linked",
                target=device.id,
                linked=device.linked,
            )
        )

    return tuple(result)


def build_scene_application_plan(scene: Scene) -> SceneApplicationPlan:
    validate_scene(scene)

    if scene.mode == "synchronized":
        if getattr(scene, "groups", ()):
            return SceneApplicationPlan(
                scene_id=scene.id,
                scene_name=scene.name,
                mode=scene.mode,
                operations=(),
                groups=tuple(copy.deepcopy(scene.groups)),
            )

        assert scene.effect is not None
        operations: list[SceneOperation] = [
            SceneOperation(
                kind="enable-sync",
                effect=scene.effect.id,
                parameters=scene.effect.parameters,
            )
        ]
        for member in scene.members:
            operations.append(
                SceneOperation(
                    kind="set-member-brightness",
                    target=member.id,
                    brightness=member.brightness,
                )
            )
        return SceneApplicationPlan(
            scene_id=scene.id,
            scene_name=scene.name,
            mode=scene.mode,
            operations=tuple(operations),
        )

    if scene.mode == "individual":
        operations: list[SceneOperation] = [SceneOperation(kind="disable-sync")]
        for device in scene.devices:
            operations.extend(_plan_individual_device(device))
        return SceneApplicationPlan(
            scene_id=scene.id,
            scene_name=scene.name,
            mode=scene.mode,
            operations=tuple(operations),
        )

    raise SceneApplicationError(f"Unsupported scene mode: {scene.mode!r}")


def validate_scene_application_plan(
    plan: SceneApplicationPlan,
    runtime: SceneRuntime,
) -> None:
    """Preflight every operation or group payload before live mutation."""
    if plan.operations:
        for operation in plan.operations:
            runtime.validate_operation(operation)
        return

    groups = getattr(plan, "groups", ())
    if plan.mode == "synchronized" and groups:
        try:
            from serpent_core.sync_groups import validate_groups
            validate_groups(list(groups))
        except Exception as exc:
            raise SceneApplicationError(
                f"Invalid synchronized Scene groups: {exc}"
            ) from exc
        return

    raise SceneApplicationError("Scene application plan is empty.")


def commit_scene_application_plan(
    plan: SceneApplicationPlan,
    runtime: SceneRuntime,
) -> None:
    """Commit a preflighted plan with best-effort transactional rollback.

    Runtime state is snapshotted before validation. If validation or any live
    operation fails, restore() receives the original snapshot.
    """
    snapshot = runtime.snapshot()

    try:
        validate_scene_application_plan(plan, runtime)

        commit_plan = getattr(runtime, "commit_plan", None)

        if commit_plan is not None:
            commit_plan(plan)
        else:
            for operation in plan.operations:
                runtime.apply_operation(operation)
    except Exception as exc:
        try:
            runtime.restore(snapshot)
        except Exception as restore_exc:
            raise SceneApplicationError(
                f"Scene {plan.scene_id!r} failed and rollback also failed: "
                f"{restore_exc}"
            ) from exc
        raise SceneApplicationError(
            f"Scene {plan.scene_id!r} was not applied; previous runtime state "
            f"was restored: {exc}"
        ) from exc


def apply_scene(scene: Scene, runtime: SceneRuntime) -> SceneApplicationPlan:
    plan = build_scene_application_plan(scene)
    commit_scene_application_plan(plan, runtime)
    return plan


__all__ = [
    "RuntimeSnapshot",
    "SceneApplicationError",
    "SceneApplicationPlan",
    "SceneOperation",
    "SceneRuntime",
    "apply_scene",
    "build_scene_application_plan",
    "commit_scene_application_plan",
    "validate_scene_application_plan",
]
