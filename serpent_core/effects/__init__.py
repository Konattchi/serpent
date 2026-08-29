from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import pkgutil
import sys
from types import ModuleType

from serpent_core.effects.base import (
    Cell,
    Colour,
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectSuitability,
    EffectTarget,
)
from serpent_core.effects.plugin import (
    EffectPluginError,
    EffectPluginSpec,
    legacy_plugin_spec,
)
from serpent_core.effects.safety import (
    EffectRuntimeHealth,
    EffectSafetyState,
)
from serpent_core.geometry import spatial_position_count


_DISCOVERY_SKIP = {"base", "plugin", "safety"}

DEFAULT_USER_EFFECT_DIR = (
    Path(
        os.environ.get(
            "XDG_DATA_HOME",
            str(Path.home() / ".local" / "share"),
        )
    )
    / "serpent"
    / "plugins"
    / "effects"
)


@dataclass(frozen=True)
class EffectDiscoveryIssue:
    module: str
    error: str


@dataclass(frozen=True)
class EffectPluginOrigin:
    kind: str
    location: str


@dataclass(frozen=True)
class EffectPluginReloadResult:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    reloaded: tuple[str, ...]


def _effect_classes(module: ModuleType) -> tuple[type[Effect], ...]:
    classes: list[type[Effect]] = []

    for _name, candidate in inspect.getmembers(module, inspect.isclass):
        if candidate is Effect:
            continue
        if not issubclass(candidate, Effect):
            continue
        if candidate.__module__ != module.__name__:
            continue
        if inspect.isabstract(candidate):
            continue
        classes.append(candidate)

    return tuple(classes)


def _plugin_specs_from_module(
    module: ModuleType,
) -> tuple[EffectPluginSpec, ...]:
    explicit = getattr(module, "SERPENT_EFFECT_PLUGINS", None)

    if explicit is not None:
        if not isinstance(explicit, (tuple, list)):
            raise EffectPluginError(
                f"{module.__name__}.SERPENT_EFFECT_PLUGINS must be "
                "a tuple or list."
            )

        specs = tuple(explicit)

        for spec in specs:
            if not isinstance(spec, EffectPluginSpec):
                raise EffectPluginError(
                    f"{module.__name__} exported a non-EffectPluginSpec."
                )
            spec.validate()

        return specs

    return tuple(
        legacy_plugin_spec(effect_class)
        for effect_class in _effect_classes(module)
    )


def _stage_specs(
    module_specs: tuple[EffectPluginSpec, ...],
    existing: dict[str, EffectPluginSpec],
) -> dict[str, EffectPluginSpec]:
    staged: dict[str, EffectPluginSpec] = {}

    for spec in module_specs:
        if spec.id in staged:
            raise EffectPluginError(
                f"Module declares duplicate effect id {spec.id!r}."
            )

        if spec.id in existing:
            previous = existing[spec.id]
            raise EffectPluginError(
                f"Duplicate effect id {spec.id!r}; "
                f"{previous.effect_class.__module__} already registered it."
            )

        staged[spec.id] = spec

    return staged


def discover_effect_plugins(
    package_name: str = "serpent_core.effects",
) -> tuple[
    dict[str, EffectPluginSpec],
    tuple[EffectDiscoveryIssue, ...],
]:
    package = importlib.import_module(package_name)
    package_path = getattr(package, "__path__", None)

    if package_path is None:
        raise EffectPluginError(
            f"Effect package {package_name!r} has no package path."
        )

    specs: dict[str, EffectPluginSpec] = {}
    issues: list[EffectDiscoveryIssue] = []

    module_names = sorted(
        item.name
        for item in pkgutil.iter_modules(package_path)
        if (
            not item.ispkg
            and not item.name.startswith("_")
            and item.name not in _DISCOVERY_SKIP
        )
    )

    for short_name in module_names:
        full_name = f"{package_name}.{short_name}"

        try:
            module = importlib.import_module(full_name)
            staged = _stage_specs(
                _plugin_specs_from_module(module),
                specs,
            )
            specs.update(staged)
        except Exception as exc:
            issues.append(
                EffectDiscoveryIssue(
                    module=full_name,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    ordered = {
        effect_id: specs[effect_id]
        for effect_id in sorted(specs)
    }
    return ordered, tuple(issues)


def _external_module_name(path: Path) -> str:
    digest = hashlib.sha256(
        str(path.resolve()).encode("utf-8")
    ).hexdigest()[:12]
    safe_stem = "".join(
        character if character.isalnum() else "_"
        for character in path.stem
    )
    return f"serpent_user_effect_{safe_stem}_{digest}"


def _load_external_module(path: Path) -> ModuleType:
    # Load one user plugin from fresh source, bypassing stale bytecode caches.
    path = path.expanduser().resolve()
    module_name = _external_module_name(path)
    spec = importlib.util.spec_from_file_location(module_name, path)

    if spec is None or spec.loader is None:
        raise EffectPluginError(
            f'Could not create import specification for {path}.'
        )

    source = path.read_bytes()
    code = compile(source, str(path), 'exec')

    previous = sys.modules.get(module_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        exec(code, module.__dict__)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise

    return module


def discover_external_effect_plugins(
    directory: Path | str = DEFAULT_USER_EFFECT_DIR,
    *,
    reserved: dict[str, EffectPluginSpec] | None = None,
) -> tuple[
    dict[str, EffectPluginSpec],
    dict[str, EffectPluginOrigin],
    tuple[EffectDiscoveryIssue, ...],
]:
    root = Path(directory).expanduser()
    existing = dict(reserved or {})
    specs: dict[str, EffectPluginSpec] = {}
    origins: dict[str, EffectPluginOrigin] = {}
    issues: list[EffectDiscoveryIssue] = []

    if not root.exists():
        return {}, {}, ()

    if not root.is_dir():
        return (
            {},
            {},
            (
                EffectDiscoveryIssue(
                    module=str(root),
                    error=(
                        "EffectPluginError: user effect path "
                        "is not a directory."
                    ),
                ),
            ),
        )

    paths = sorted(
        (
            path
            for path in root.glob("*.py")
            if path.is_file() and not path.name.startswith("_")
        ),
        key=lambda path: path.name,
    )

    for path in paths:
        try:
            module = _load_external_module(path)
            combined = dict(existing)
            combined.update(specs)
            staged = _stage_specs(
                _plugin_specs_from_module(module),
                combined,
            )
            specs.update(staged)

            for effect_id in staged:
                origins[effect_id] = EffectPluginOrigin(
                    kind="user",
                    location=str(path),
                )

        except Exception as exc:
            issues.append(
                EffectDiscoveryIssue(
                    module=str(path),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    ordered_specs = {
        effect_id: specs[effect_id]
        for effect_id in sorted(specs)
    }
    ordered_origins = {
        effect_id: origins[effect_id]
        for effect_id in sorted(origins)
    }

    return ordered_specs, ordered_origins, tuple(issues)


_BUILTIN_PLUGIN_SPECS, _BUILTIN_DISCOVERY_ISSUES = discover_effect_plugins()

_BUILTIN_ORIGINS = {
    effect_id: EffectPluginOrigin(
        kind="built-in",
        location=spec.effect_class.__module__,
    )
    for effect_id, spec in _BUILTIN_PLUGIN_SPECS.items()
}

_USER_PLUGIN_SPECS, _USER_ORIGINS, _USER_DISCOVERY_ISSUES = (
    discover_external_effect_plugins(
        DEFAULT_USER_EFFECT_DIR,
        reserved=_BUILTIN_PLUGIN_SPECS,
    )
)

_PLUGIN_SPECS = {
    **_BUILTIN_PLUGIN_SPECS,
    **_USER_PLUGIN_SPECS,
}
_PLUGIN_SPECS = {
    effect_id: _PLUGIN_SPECS[effect_id]
    for effect_id in sorted(_PLUGIN_SPECS)
}

_PLUGIN_ORIGINS = {
    **_BUILTIN_ORIGINS,
    **_USER_ORIGINS,
}

_DISCOVERY_ISSUES = (
    *_BUILTIN_DISCOVERY_ISSUES,
    *_USER_DISCOVERY_ISSUES,
)

_EFFECTS: dict[str, Effect] = {
    effect_id: spec.effect_class()
    for effect_id, spec in _PLUGIN_SPECS.items()
}

_SAFETY = EffectSafetyState()


def effect_ids() -> tuple[str, ...]:
    return tuple(_EFFECTS)


def effect_plugin_specs() -> tuple[EffectPluginSpec, ...]:
    return tuple(_PLUGIN_SPECS.values())


def effect_discovery_issues() -> tuple[EffectDiscoveryIssue, ...]:
    return tuple(_DISCOVERY_ISSUES)


def effect_plugin_origin(effect_id: str) -> EffectPluginOrigin:
    try:
        return _PLUGIN_ORIGINS[effect_id]
    except KeyError as exc:
        raise ValueError(
            f"Effect plugin is not registered: {effect_id}"
        ) from exc


def user_effect_directory() -> Path:
    return DEFAULT_USER_EFFECT_DIR


def get_effect(effect_id: str) -> Effect:
    try:
        return _EFFECTS[effect_id]
    except KeyError as exc:
        raise ValueError(
            f"Software effect is not implemented: {effect_id}"
        ) from exc


def get_effect_definition(effect_id: str) -> EffectDefinition:
    return get_effect(effect_id).definition


def reset_effect_instance(effect_id: str) -> Effect:
    """Replace one registered effect with a fresh constructed instance.

    Plugin metadata/registration and runtime safety state are intentionally
    preserved. Only transient per-effect object state is discarded.
    """

    try:
        spec = _PLUGIN_SPECS[effect_id]
    except KeyError as exc:
        raise ValueError(
            f"Effect plugin is not registered: {effect_id}"
        ) from exc

    effect = spec.effect_class()
    _EFFECTS[effect_id] = effect
    return effect


def reload_effect_plugins(
    *,
    required_effect_id: str | None = None,
) -> EffectPluginReloadResult:
    # Atomically rediscover installed user effect plugins from fresh source.
    global _USER_PLUGIN_SPECS
    global _USER_ORIGINS
    global _USER_DISCOVERY_ISSUES
    global _PLUGIN_SPECS
    global _PLUGIN_ORIGINS
    global _DISCOVERY_ISSUES
    global _EFFECTS

    prefix = 'serpent_user_effect_'
    module_snapshot = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith(prefix)
    }

    def restore_modules() -> None:
        for name in tuple(sys.modules):
            if name.startswith(prefix) and name not in module_snapshot:
                sys.modules.pop(name, None)
        for name, module in module_snapshot.items():
            sys.modules[name] = module

    candidate_specs, candidate_origins, issues = discover_external_effect_plugins(
        DEFAULT_USER_EFFECT_DIR,
        reserved=_BUILTIN_PLUGIN_SPECS,
    )

    if issues:
        restore_modules()
        detail = '; '.join(
            f'{issue.module}: {issue.error}'
            for issue in issues
        )
        raise EffectPluginError(
            'User effect reload rejected; existing registry kept: ' + detail
        )

    combined_specs = {
        **_BUILTIN_PLUGIN_SPECS,
        **candidate_specs,
    }

    if required_effect_id is not None and required_effect_id not in combined_specs:
        restore_modules()
        raise EffectPluginError(
            'User effect reload would remove the active effect '
            f'{required_effect_id!r}; switch effects first.'
        )

    try:
        candidate_instances = {
            effect_id: spec.effect_class()
            for effect_id, spec in candidate_specs.items()
        }
    except Exception as exc:
        restore_modules()
        raise EffectPluginError(
            'User effect reload rejected during construction: '
            f'{type(exc).__name__}: {exc}'
        ) from exc

    old_user_ids = set(_USER_PLUGIN_SPECS)
    new_user_ids = set(candidate_specs)

    next_specs = {
        effect_id: combined_specs[effect_id]
        for effect_id in sorted(combined_specs)
    }
    next_origins = {
        **_BUILTIN_ORIGINS,
        **candidate_origins,
    }

    next_effects: dict[str, Effect] = {}
    for effect_id in next_specs:
        if effect_id in candidate_instances:
            next_effects[effect_id] = candidate_instances[effect_id]
        else:
            next_effects[effect_id] = _EFFECTS[effect_id]

    _USER_PLUGIN_SPECS = candidate_specs
    _USER_ORIGINS = candidate_origins
    _USER_DISCOVERY_ISSUES = ()
    _PLUGIN_SPECS = next_specs
    _PLUGIN_ORIGINS = next_origins
    _DISCOVERY_ISSUES = (*_BUILTIN_DISCOVERY_ISSUES,)
    _EFFECTS = next_effects

    for effect_id in new_user_ids:
        _SAFETY.reset(effect_id)

    live_module_names = {
        _external_module_name(Path(origin.location))
        for origin in candidate_origins.values()
    }
    for name in tuple(sys.modules):
        if name.startswith(prefix) and name not in live_module_names:
            sys.modules.pop(name, None)

    return EffectPluginReloadResult(
        added=tuple(sorted(new_user_ids - old_user_ids)),
        removed=tuple(sorted(old_user_ids - new_user_ids)),
        reloaded=tuple(sorted(old_user_ids & new_user_ids)),
    )


def get_effect_plugin_spec(effect_id: str) -> EffectPluginSpec:
    try:
        return _PLUGIN_SPECS[effect_id]
    except KeyError as exc:
        raise ValueError(
            f"Effect plugin is not registered: {effect_id}"
        ) from exc


def effect_runtime_health(effect_id: str) -> EffectRuntimeHealth:
    get_effect(effect_id)
    return _SAFETY.health(effect_id)


def reset_effect_quarantine(effect_id: str | None = None) -> None:
    if effect_id is not None:
        get_effect(effect_id)

    _SAFETY.reset(effect_id)


def assess_effect_suitability(
    effect_id: str,
    target: EffectTarget,
    parameters: EffectParameters,
) -> EffectSuitability:
    definition = get_effect_definition(effect_id)

    if not definition.spatial:
        return EffectSuitability(
            level="full",
            spatial_positions=len(target.active_cells),
            minimum_positions=1,
            recommended_positions=1,
        )

    if definition.spatial_metric == "axis":
        positions = spatial_position_count(
            target.active_cells,
            parameters.direction,
        )
    elif definition.spatial_metric == "cells":
        positions = len(target.active_cells)
    else:
        positions = len(target.active_cells)

    if positions < definition.minimum_spatial_positions:
        level = "uniform"
    elif positions < definition.recommended_spatial_positions:
        level = "limited"
    else:
        level = "full"

    return EffectSuitability(
        level=level,
        spatial_positions=positions,
        minimum_positions=definition.minimum_spatial_positions,
        recommended_positions=definition.recommended_spatial_positions,
    )


def _safe_black_frame(target: EffectTarget) -> EffectFrame:
    pixels = tuple(
        tuple((0, 0, 0) for _column in range(target.columns))
        for _row in range(target.rows)
    )
    frame = EffectFrame(
        rows=target.rows,
        columns=target.columns,
        pixels=pixels,
    )
    frame.validate()
    return frame


def render_effect(
    effect_id: str,
    elapsed: float,
    parameters: EffectParameters,
    target: EffectTarget,
) -> EffectFrame:
    effect = get_effect(effect_id)

    if _SAFETY.is_quarantined(effect_id):
        return _safe_black_frame(target)

    try:
        frame = effect.render(elapsed, parameters, target)

        if not isinstance(frame, EffectFrame):
            raise TypeError(
                f"{effect_id} returned {type(frame).__name__}, "
                "expected EffectFrame."
            )

        frame.validate()
    except Exception as exc:
        _SAFETY.failure(effect_id, exc)
        return _safe_black_frame(target)

    _SAFETY.success(effect_id)
    return frame


__all__ = [
    "Cell",
    "Colour",
    "DEFAULT_USER_EFFECT_DIR",
    "Effect",
    "EffectDefinition",
    "EffectEvent",
    "EffectDiscoveryIssue",
    "EffectFrame",
    "EffectParameters",
    "EffectPluginOrigin",
    "EffectPluginReloadResult",
    "EffectPluginSpec",
    "EffectRuntimeHealth",
    "EffectSuitability",
    "EffectTarget",
    "assess_effect_suitability",
    "discover_effect_plugins",
    "discover_external_effect_plugins",
    "effect_discovery_issues",
    "effect_ids",
    "effect_plugin_origin",
    "effect_plugin_specs",
    "effect_runtime_health",
    "get_effect",
    "get_effect_definition",
    "get_effect_plugin_spec",
    "render_effect",
    "reload_effect_plugins",
    "reset_effect_instance",
    "reset_effect_quarantine",
    "user_effect_directory",
]
