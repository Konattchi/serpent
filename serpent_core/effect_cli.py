from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from serpent_core.effects import (
    effect_plugin_origin,
    effect_plugin_specs,
    get_effect_plugin_spec,
    user_effect_directory,
)
from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginError,
)


SYNC_RUNTIME_PARAMETER_IDS = {
    "colour1",
    "colour2",
    "speed",
    "direction",
}


def _option_name(parameter_id: str) -> str:
    return "--" + parameter_id.replace("_", "-")


def _all_parameter_specs() -> dict[str, EffectParameterSpec]:
    result: dict[str, EffectParameterSpec] = {}

    for plugin in effect_plugin_specs():
        for parameter in plugin.parameters:
            existing = result.get(parameter.id)

            if existing is None:
                result[parameter.id] = parameter
                continue

            if existing.kind != parameter.kind:
                raise EffectPluginError(
                    f"Parameter {parameter.id!r} has conflicting kinds "
                    f"{existing.kind!r} and {parameter.kind!r}."
                )

    return {
        parameter_id: result[parameter_id]
        for parameter_id in sorted(result)
    }


def add_sync_effect_arguments(parser: argparse.ArgumentParser) -> None:
    for parameter_id, parameter in _all_parameter_specs().items():
        if parameter_id not in SYNC_RUNTIME_PARAMETER_IDS:
            continue

        option = _option_name(parameter_id)
        kwargs: dict[str, Any] = {
            "dest": parameter_id,
            "default": None,
            "help": f"{parameter.label} for effects that support it.",
        }

        if parameter.kind == "colour":
            kwargs.update(
                nargs=3,
                type=int,
                metavar=("R", "G", "B"),
            )
        elif parameter.kind == "integer":
            kwargs["type"] = int
        elif parameter.kind == "number":
            kwargs["type"] = float
        elif parameter.kind == "choice":
            sample = parameter.default
            kwargs["type"] = int if isinstance(sample, int) else str
        elif parameter.kind == "boolean":
            kwargs["action"] = argparse.BooleanOptionalAction
            kwargs.pop("default", None)
        else:
            raise EffectPluginError(
                f"Unsupported CLI parameter kind: {parameter.kind!r}."
            )

        parser.add_argument(option, **kwargs)


def _value_for(args: argparse.Namespace, parameter_id: str) -> Any:
    return getattr(args, parameter_id, None)


def validate_sync_effect_arguments(args: argparse.Namespace) -> None:
    plugin = get_effect_plugin_spec(str(args.effect))
    allowed = {
        parameter.id: parameter
        for parameter in plugin.parameters
    }

    for parameter_id in SYNC_RUNTIME_PARAMETER_IDS:
        value = _value_for(args, parameter_id)

        if value is None:
            continue

        if parameter_id not in allowed:
            raise ValueError(
                f"Effect {plugin.id!r} does not support "
                f"{_option_name(parameter_id)}."
            )

        parameter = allowed[parameter_id]
        parameter.validate()

        if parameter.kind == "colour":
            if (
                not isinstance(value, (list, tuple))
                or len(value) != 3
                or any(
                    not isinstance(component, int)
                    or component < 0
                    or component > 255
                    for component in value
                )
            ):
                raise ValueError(
                    f"{parameter.label} must contain three values "
                    "between 0 and 255."
                )
        elif parameter.kind in {"integer", "number"}:
            if parameter.minimum is not None and value < parameter.minimum:
                raise ValueError(
                    f"{parameter.label} must be at least "
                    f"{parameter.minimum}."
                )
            if parameter.maximum is not None and value > parameter.maximum:
                raise ValueError(
                    f"{parameter.label} must be at most "
                    f"{parameter.maximum}."
                )
        elif parameter.kind == "choice":
            if value not in parameter.choices:
                choices = ", ".join(str(choice) for choice in parameter.choices)
                raise ValueError(
                    f"{parameter.label} must be one of: {choices}."
                )


def _origin_text(effect_id: str) -> str:
    origin = effect_plugin_origin(effect_id)
    if origin.kind == "built-in":
        return "built-in"
    return f"user:{Path(origin.location).name}"


def effect_list_text() -> str:
    lines = ["Effects", "-------"]

    for plugin in effect_plugin_specs():
        controls = ", ".join(
            parameter.id
            for parameter in plugin.parameters
        ) or "none"
        reactive = (
            "legacy-auto"
            if plugin.input_capabilities is None
            else ",".join(plugin.input_capabilities) or "none"
        )
        lines.append(
            f"{plugin.id}: {plugin.name} "
            f"[{controls}] <{_origin_text(plugin.id)}> "
            f"reactive:{reactive}"
        )

    return "\n".join(lines)


def effect_show_text(effect_id: str) -> str:
    plugin = get_effect_plugin_spec(effect_id)
    origin = effect_plugin_origin(effect_id)

    lines = [
        plugin.name,
        "-" * len(plugin.name),
        f"Id: {plugin.id}",
        f"Plugin API: {plugin.api_version}",
        f"Origin: {origin.kind}",
        f"Location: {origin.location}",
        f"Description: {plugin.description}",
        (
            "Reactive input: legacy-auto"
            if plugin.input_capabilities is None
            else "Reactive input: "
            + (", ".join(plugin.input_capabilities) or "none")
        ),
        "Render targets: " + ", ".join(plugin.render_targets),
        "Parameters:",
    ]

    if not plugin.parameters:
        lines.append("  none")
    else:
        for parameter in plugin.parameters:
            detail = [
                f"type={parameter.kind}",
                f"default={parameter.default!r}",
            ]
            if parameter.minimum is not None:
                detail.append(f"min={parameter.minimum}")
            if parameter.maximum is not None:
                detail.append(f"max={parameter.maximum}")
            if parameter.choices:
                detail.append(
                    "choices="
                    + ",".join(str(choice) for choice in parameter.choices)
                )

            lines.append(
                f"  {parameter.id} — {parameter.label} "
                f"({'; '.join(detail)})"
            )

    return "\n".join(lines)


def effect_directory_text() -> str:
    return str(user_effect_directory())


__all__ = [
    "SYNC_RUNTIME_PARAMETER_IDS",
    "add_sync_effect_arguments",
    "effect_directory_text",
    "effect_list_text",
    "effect_show_text",
    "validate_sync_effect_arguments",
]
