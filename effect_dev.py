#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import py_compile
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable

ROOT = Path.home() / ".local/share/serpent"
sys.path.insert(0, str(ROOT))

from serpent_core.device import build_device_model
from serpent_core.effects import effect_ids
from serpent_core.fixtures import (
    Fixture,
    find_fixture_by_id,
    load_all_fixtures,
)
from serpent_core.sync import require_topology, topology_target
from serpent_core.effects.base import (
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectPluginSpec


class DeveloperToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedPluginFile:
    path: Path
    module: ModuleType
    specs: tuple[EffectPluginSpec, ...]


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FixtureEffectTarget:
    fixture_id: str
    fixture_name: str
    device_class: str
    target: EffectTarget


def fixture_effect_target(fixture: Fixture) -> FixtureEffectTarget:
    device = build_device_model(fixture)
    topology = require_topology(device)
    target = topology_target(
        topology,
        controllable_only=True,
    )
    target.validate()

    if not target.active_cells:
        raise DeveloperToolError(
            f"Fixture {fixture.id!r} has no controllable lighting cells."
        )

    return FixtureEffectTarget(
        fixture_id=fixture.id,
        fixture_name=fixture.display_name,
        device_class=device.device_class,
        target=target,
    )


def fixture_effect_targets() -> tuple[FixtureEffectTarget, ...]:
    result: list[FixtureEffectTarget] = []

    for fixture in load_all_fixtures():
        try:
            result.append(fixture_effect_target(fixture))
        except Exception:
            continue

    return tuple(result)


def matching_fixture_targets(
    render_target: str,
) -> tuple[FixtureEffectTarget, ...]:
    return tuple(
        item
        for item in fixture_effect_targets()
        if item.device_class == render_target
    )


def select_fixture_target(
    *,
    fixture_id: str | None,
    render_target: str,
) -> FixtureEffectTarget:
    if fixture_id:
        try:
            selected = fixture_effect_target(
                find_fixture_by_id(fixture_id)
            )
        except Exception as exc:
            raise DeveloperToolError(
                f"Could not build fixture target {fixture_id!r}: {exc}"
            ) from exc

        if selected.device_class != render_target:
            raise DeveloperToolError(
                f"Fixture {fixture_id!r} is device class "
                f"{selected.device_class!r}, not {render_target!r}."
            )
        return selected

    matches = matching_fixture_targets(render_target)
    if not matches:
        raise DeveloperToolError(
            f"No installed lighting fixture provides render target "
            f"{render_target!r}. Use --fixture after installing a matching "
            "fixture definition."
        )

    return matches[0]


def _load_module(path: Path) -> ModuleType:
    path = path.expanduser().resolve()

    if not path.is_file():
        raise DeveloperToolError(f"Plugin file does not exist: {path}")

    py_compile.compile(str(path), doraise=True)

    module_name = (
        "serpent_dev_"
        + path.stem.replace("-", "_")
        + "_"
        + str(abs(hash(str(path))))
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if spec is None or spec.loader is None:
        raise DeveloperToolError(
            f"Could not create an import spec for {path}."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return module


def load_plugin_file(path: Path) -> LoadedPluginFile:
    module = _load_module(path)
    explicit = getattr(module, "SERPENT_EFFECT_PLUGINS", None)

    if not isinstance(explicit, (tuple, list)):
        raise DeveloperToolError(
            "Developer validation requires explicit "
            "SERPENT_EFFECT_PLUGINS metadata."
        )

    specs = tuple(explicit)

    if not specs:
        raise DeveloperToolError(
            "SERPENT_EFFECT_PLUGINS must contain at least one plugin."
        )

    for spec in specs:
        if not isinstance(spec, EffectPluginSpec):
            raise DeveloperToolError(
                "SERPENT_EFFECT_PLUGINS contains a non-EffectPluginSpec."
            )
        spec.validate()

    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise DeveloperToolError(
            "Plugin file declares duplicate effect ids."
        )

    return LoadedPluginFile(
        path=path.expanduser().resolve(),
        module=module,
        specs=specs,
    )


def _static_safety_warnings(path: Path) -> tuple[str, ...]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    warnings: list[str] = []

    forbidden_literals = (
        "/dev/input",
        "EVIOCGRAB",
        "systemctl",
        "/sys/bus/hid",
        "matrix_effect_",
        "matrix_custom_frame",
    )

    for token in forbidden_literals:
        if token in source:
            warnings.append(
                f"Source contains direct runtime/hardware token: {token}"
            )

    imported_roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", 1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    for module in ("subprocess", "fcntl"):
        if module in imported_roots:
            warnings.append(
                f"Source imports {module}; review for direct OS/input access."
            )

    return tuple(dict.fromkeys(warnings))


def validate_file(
    path: Path,
    *,
    allow_installed_id: bool = False,
) -> tuple[LoadedPluginFile, ValidationResult]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        loaded = load_plugin_file(path)
    except Exception as exc:
        dummy = LoadedPluginFile(
            path=path.expanduser(),
            module=ModuleType("invalid"),
            specs=(),
        )
        return (
            dummy,
            ValidationResult(
                errors=(
                    f"{type(exc).__name__}: {exc}",
                ),
                warnings=(),
            ),
        )

    installed = set(effect_ids())

    if not allow_installed_id:
        for spec in loaded.specs:
            if spec.id in installed:
                errors.append(
                    f"Effect id {spec.id!r} is already registered "
                    "in this Serpent process."
                )

    warnings.extend(_static_safety_warnings(loaded.path))

    for spec in loaded.specs:
        if spec.input_capabilities is None:
            warnings.append(
                f"{spec.id}: input_capabilities uses legacy auto-detection; "
                "new reactive plugins should declare it explicitly."
            )

        if not spec.render_targets:
            errors.append(
                f"{spec.id}: no render targets declared."
            )

        try:
            effect = spec.effect_class()
        except Exception as exc:
            errors.append(
                f"{spec.id}: constructor failed: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # Basic offline frame contract on each declared target class.
        params = default_effect_parameters(spec)

        targets: list[FixtureEffectTarget] = []

        for render_target in spec.render_targets:
            matches = matching_fixture_targets(render_target)

            if not matches:
                warnings.append(
                    f"{spec.id}: no installed fixture provides "
                    f"render target {render_target!r}; offline render "
                    "contract was not exercised for that target class."
                )
                continue

            targets.extend(matches)

        for fixture_target in targets:
            try:
                frame = effect.render(
                    0.0,
                    params,
                    fixture_target.target,
                )
                if not isinstance(frame, EffectFrame):
                    raise TypeError(
                        f"returned {type(frame).__name__}, expected EffectFrame"
                    )
                frame.validate()
            except Exception as exc:
                errors.append(
                    f"{spec.id}: {fixture_target.device_class} offline "
                    f"render failed on fixture "
                    f"{fixture_target.fixture_id!r} "
                    f"({fixture_target.target.rows}x"
                    f"{fixture_target.target.columns}, "
                    f"{len(fixture_target.target.active_cells)} "
                    "controllable cells): "
                    f"{type(exc).__name__}: {exc}"
                )

    return (
        loaded,
        ValidationResult(
            errors=tuple(errors),
            warnings=tuple(dict.fromkeys(warnings)),
        ),
    )


def default_effect_parameters(spec: EffectPluginSpec) -> EffectParameters:
    values = {
        "brightness": 100.0,
        "colour1": (255, 255, 255),
        "colour2": (0, 0, 0),
        "speed": 2,
        "direction": 1,
    }

    for parameter in spec.parameters:
        if parameter.id in values:
            value = parameter.default
            if parameter.kind == "colour":
                value = tuple(value)
            values[parameter.id] = value

    return EffectParameters(**values)


def _select_spec(
    loaded: LoadedPluginFile,
    effect_id: str | None,
) -> EffectPluginSpec:
    if effect_id is None:
        if len(loaded.specs) != 1:
            raise DeveloperToolError(
                "Plugin file contains multiple effects; use --effect-id."
            )
        return loaded.specs[0]

    for spec in loaded.specs:
        if spec.id == effect_id:
            return spec

    raise DeveloperToolError(
        f"Effect id {effect_id!r} is not declared by this file."
    )


def _ascii_frame(frame: EffectFrame) -> str:
    chars = " .:-=+*#%@"
    lines = []

    for row in frame.pixels:
        rendered = []
        for red, green, blue in row:
            level = max(red, green, blue) / 255.0
            index = round(level * (len(chars) - 1))
            rendered.append(chars[index])
        lines.append("".join(rendered))

    return "\n".join(lines)


def command_validate(args: argparse.Namespace) -> int:
    loaded, result = validate_file(
        Path(args.path),
        allow_installed_id=args.allow_installed_id,
    )

    print(f"Plugin: {loaded.path}")

    for warning in result.warnings:
        print(f"! {warning}")

    for error in result.errors:
        print(f"✗ {error}")

    if result.errors:
        print()
        print(
            f"Validation failed: {len(result.errors)} error(s), "
            f"{len(result.warnings)} warning(s)."
        )
        return 1

    print()
    for spec in loaded.specs:
        reactive = (
            "legacy-auto"
            if spec.input_capabilities is None
            else ", ".join(spec.input_capabilities) or "none"
        )
        print(
            f"✓ {spec.id}: API {spec.api_version}; "
            f"input=[{reactive}]; "
            f"render=[{', '.join(spec.render_targets)}]"
        )

    print()
    print(
        f"Validation passed: {len(loaded.specs)} effect(s), "
        f"{len(result.warnings)} warning(s)."
    )
    print("Offline only: no plugin installed and no hardware/input opened.")
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    loaded = load_plugin_file(Path(args.path))

    print(f"File: {loaded.path}")

    for spec in loaded.specs:
        reactive = (
            "legacy-auto"
            if spec.input_capabilities is None
            else ", ".join(spec.input_capabilities) or "none"
        )

        print()
        print(spec.name)
        print("-" * len(spec.name))
        print(f"Id: {spec.id}")
        print(f"Plugin API: {spec.api_version}")
        print(f"Reactive input: {reactive}")
        print("Render targets: " + ", ".join(spec.render_targets))
        print(f"Description: {spec.description}")
        print("Parameters:")

        if not spec.parameters:
            print("  none")
        else:
            for parameter in spec.parameters:
                extras = []
                if parameter.minimum is not None:
                    extras.append(f"min={parameter.minimum}")
                if parameter.maximum is not None:
                    extras.append(f"max={parameter.maximum}")
                if parameter.choices:
                    extras.append(
                        "choices=" + ",".join(map(str, parameter.choices))
                    )
                suffix = "; " + "; ".join(extras) if extras else ""
                print(
                    f"  {parameter.id} — {parameter.label} "
                    f"(type={parameter.kind}; "
                    f"default={parameter.default!r}{suffix})"
                )

    print()
    print("Offline inspection only.")
    return 0


def command_simulate(args: argparse.Namespace) -> int:
    loaded = load_plugin_file(Path(args.path))
    spec = _select_spec(loaded, args.effect_id)
    effect = spec.effect_class()
    params = default_effect_parameters(spec)

    fixture_target = select_fixture_target(
        fixture_id=args.fixture,
        render_target=args.target,
    )

    if args.target not in spec.render_targets:
        raise DeveloperToolError(
            f"Effect {spec.id!r} does not declare render target "
            f"{args.target!r}."
        )

    target = fixture_target.target

    if args.event == "keyboard":
        event = EffectEvent(
            kind="key-press",
            timestamp=0.0,
            source="keyboard:developer-simulator",
            code=args.code,
            value=1,
            row=args.row,
            column=args.column,
        )
    else:
        event = EffectEvent(
            kind="mouse-press",
            timestamp=0.0,
            source="mouse:developer-simulator",
            code=args.code,
            value=1,
            row=None,
            column=None,
        )

    effect.handle_event(event)

    steps = max(1, args.steps)
    duration = max(0.0, args.seconds)

    print(
        f"Simulating {spec.id}: event={args.event} "
        f"target={args.target}"
    )
    print(
        f"Fixture: {fixture_target.fixture_id} "
        f"({fixture_target.fixture_name})"
    )
    print(
        f"Topology: {target.rows}x{target.columns}; "
        f"controllable cells={len(target.active_cells)}"
    )

    for index in range(steps):
        elapsed = (
            0.0
            if steps == 1
            else duration * index / (steps - 1)
        )
        frame = effect.render(elapsed, params, target)
        frame.validate()

        print()
        print(f"t={elapsed:.3f}s")
        print(_ascii_frame(frame))

    print()
    print("Offline simulation only: no input/hardware/services touched.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serpent-effect-dev",
        description=(
            "Offline Serpent effect-plugin developer tools."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate",
        help="Compile/import/validate a plugin file offline.",
    )
    validate.add_argument("path")
    validate.add_argument(
        "--allow-installed-id",
        action="store_true",
        help=(
            "Do not treat an already-registered effect id as an error. "
            "Useful while validating a replacement for an installed plugin."
        ),
    )
    validate.set_defaults(func=command_validate)

    inspect = sub.add_parser(
        "inspect",
        help="Show plugin metadata from a file without installing it.",
    )
    inspect.add_argument("path")
    inspect.set_defaults(func=command_inspect)

    simulate = sub.add_parser(
        "simulate",
        help="Feed one synthetic event and render offline frames.",
    )
    simulate.add_argument("path")
    simulate.add_argument("--effect-id")
    simulate.add_argument(
        "--event",
        choices=("keyboard", "mouse"),
        default="keyboard",
    )
    simulate.add_argument(
        "--target",
        choices=("keyboard", "mouse"),
        default="keyboard",
    )
    simulate.add_argument(
        "--fixture",
        help=(
            "Use a specific installed fixture topology. "
            "The fixture device class must match --target."
        ),
    )
    simulate.add_argument("--row", type=int, default=3)
    simulate.add_argument("--column", type=int, default=5)
    simulate.add_argument("--code", default="KEY_G")
    simulate.add_argument("--seconds", type=float, default=0.8)
    simulate.add_argument("--steps", type=int, default=5)
    simulate.set_defaults(func=command_simulate)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.func(args))
    except (
        DeveloperToolError,
        OSError,
        ValueError,
        TypeError,
        SyntaxError,
        ImportError,
    ) as exc:
        print(
            f"serpent-effect-dev: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
