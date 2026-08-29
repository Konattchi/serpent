from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from serpent_core.effects.base import Effect


EFFECT_PLUGIN_API_VERSION = 1
_ALLOWED_INPUT_CAPABILITIES = frozenset({"keyboard", "mouse"})

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RENDER_TARGET_PATTERN = _ID_PATTERN
_PARAMETER_KINDS = {
    "colour",
    "integer",
    "number",
    "choice",
    "boolean",
}


class EffectPluginError(ValueError):
    """Raised when an effect plugin violates the public plugin contract."""


@dataclass(frozen=True)
class EffectParameterSpec:
    """Presentation-neutral description of one effect parameter."""

    id: str
    label: str
    kind: str
    default: Any = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[Any, ...] = ()

    def validate(self) -> None:
        if not _ID_PATTERN.fullmatch(self.id):
            raise EffectPluginError(
                f"Invalid effect parameter id: {self.id!r}."
            )

        if not self.label.strip():
            raise EffectPluginError(
                f"Effect parameter {self.id!r} has no label."
            )

        if self.kind not in _PARAMETER_KINDS:
            raise EffectPluginError(
                f"Effect parameter {self.id!r} uses unsupported "
                f"kind {self.kind!r}."
            )

        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise EffectPluginError(
                f"Effect parameter {self.id!r} has minimum greater "
                "than maximum."
            )

        if self.kind == "choice" and not self.choices:
            raise EffectPluginError(
                f"Choice parameter {self.id!r} must declare choices."
            )

        if self.kind != "choice" and self.choices:
            raise EffectPluginError(
                f"Non-choice parameter {self.id!r} cannot declare choices."
            )

        if self.kind == "colour":
            value = self.default
            if (
                not isinstance(value, tuple)
                or len(value) != 3
                or any(
                    not isinstance(component, int)
                    or isinstance(component, bool)
                    or component < 0
                    or component > 255
                    for component in value
                )
            ):
                raise EffectPluginError(
                    f"Colour parameter {self.id!r} must default to "
                    "an RGB tuple of bytes."
                )

        if self.kind in {"integer", "number"}:
            value = self.default
            numeric = isinstance(value, (int, float)) and not isinstance(
                value,
                bool,
            )

            if not numeric:
                raise EffectPluginError(
                    f"Numeric parameter {self.id!r} needs a numeric default."
                )

            if self.minimum is not None and value < self.minimum:
                raise EffectPluginError(
                    f"Default for {self.id!r} is below its minimum."
                )

            if self.maximum is not None and value > self.maximum:
                raise EffectPluginError(
                    f"Default for {self.id!r} is above its maximum."
                )

        if self.kind == "choice" and self.default not in self.choices:
            raise EffectPluginError(
                f"Default for {self.id!r} is not one of its choices."
            )

        if self.kind == "boolean" and not isinstance(self.default, bool):
            raise EffectPluginError(
                f"Boolean parameter {self.id!r} needs a boolean default."
            )


@dataclass(frozen=True)
class EffectPluginSpec:
    """Public contract a Serpent effect plugin must satisfy.

    M7.1 defines the contract only. Discovery/loading remains the job of
    later milestones.
    """

    id: str
    name: str
    description: str
    effect_class: type[Effect]
    parameters: tuple[EffectParameterSpec, ...] = ()
    api_version: int = EFFECT_PLUGIN_API_VERSION
    input_capabilities: tuple[str, ...] | None = None
    render_targets: tuple[str, ...] = ("keyboard", "mouse")

    def validate(self) -> None:
        if self.api_version != EFFECT_PLUGIN_API_VERSION:
            raise EffectPluginError(
                f"Effect plugin {self.id!r} targets API "
                f"{self.api_version}; Serpent supports "
                f"{EFFECT_PLUGIN_API_VERSION}."
            )

        if not _ID_PATTERN.fullmatch(self.id):
            raise EffectPluginError(
                f"Invalid effect plugin id: {self.id!r}."
            )

        if not self.name.strip():
            raise EffectPluginError(
                f"Effect plugin {self.id!r} has no display name."
            )

        if not self.description.strip():
            raise EffectPluginError(
                f"Effect plugin {self.id!r} has no description."
            )

        if not isinstance(self.effect_class, type) or not issubclass(
            self.effect_class,
            Effect,
        ):
            raise EffectPluginError(
                f"Effect plugin {self.id!r} does not expose an Effect class."
            )

        try:
            effect = self.effect_class()
        except Exception as exc:
            raise EffectPluginError(
                f"Effect plugin {self.id!r} could not be constructed: {exc}"
            ) from exc

        definition = getattr(effect, "definition", None)
        definition_id = getattr(definition, "id", None)

        if definition_id != self.id:
            raise EffectPluginError(
                f"Effect plugin id {self.id!r} does not match "
                f"Effect.definition.id {definition_id!r}."
            )

        seen: set[str] = set()

        for parameter in self.parameters:
            parameter.validate()

            if parameter.id in seen:
                raise EffectPluginError(
                    f"Effect plugin {self.id!r} declares duplicate "
                    f"parameter {parameter.id!r}."
                )

            seen.add(parameter.id)

        if self.input_capabilities is not None:
            if not isinstance(self.input_capabilities, tuple):
                raise EffectPluginError(
                    f"Effect plugin {self.id!r} input_capabilities "
                    "must be a tuple or None."
                )

            if len(set(self.input_capabilities)) != len(
                self.input_capabilities
            ):
                raise EffectPluginError(
                    f"Effect plugin {self.id!r} declares duplicate "
                    "input capabilities."
                )

            for capability in self.input_capabilities:
                if capability not in _ALLOWED_INPUT_CAPABILITIES:
                    raise EffectPluginError(
                        f"Effect plugin {self.id!r} has unsupported "
                        f"reactive input capability {capability!r}."
                    )

            if (
                self.input_capabilities
                and type(effect).handle_event is Effect.handle_event
            ):
                raise EffectPluginError(
                    f"Effect plugin {self.id!r} declares reactive input "
                    "but does not override Effect.handle_event()."
                )

        if not isinstance(self.render_targets, tuple):
            raise EffectPluginError(
                f"Effect plugin {self.id!r} render_targets must be a tuple."
            )

        if not self.render_targets:
            raise EffectPluginError(
                f"Effect plugin {self.id!r} must declare at least one "
                "render target."
            )

        if len(set(self.render_targets)) != len(self.render_targets):
            raise EffectPluginError(
                f"Effect plugin {self.id!r} declares duplicate render targets."
            )

        for target in self.render_targets:
            if (
                not isinstance(target, str)
                or not _RENDER_TARGET_PATTERN.fullmatch(target)
            ):
                raise EffectPluginError(
                    f"Effect plugin {self.id!r} has invalid "
                    f"render target {target!r}; render targets are "
                    "extensible lowercase device-class slugs."
                )


def legacy_parameter_specs(effect: Effect) -> tuple[EffectParameterSpec, ...]:
    """Translate the current EffectDefinition into the public M7.1 schema.

    Brightness is intentionally absent: it belongs to the renderer/member,
    not to the effect plugin.
    """

    definition = effect.definition
    parameters: list[EffectParameterSpec] = []

    if definition.colours >= 1:
        parameters.append(
            EffectParameterSpec(
                id="colour1",
                label="Primary colour",
                kind="colour",
                default=(255, 255, 255),
            )
        )

    if definition.colours >= 2:
        parameters.append(
            EffectParameterSpec(
                id="colour2",
                label="Secondary colour",
                kind="colour",
                default=(0, 0, 0),
            )
        )

    if definition.speed:
        parameters.append(
            EffectParameterSpec(
                id="speed",
                label="Speed",
                kind="integer",
                default=2,
                minimum=1,
                maximum=10,
            )
        )

    if definition.directions:
        parameters.append(
            EffectParameterSpec(
                id="direction",
                label="Direction",
                kind="choice",
                default=definition.directions[0],
                choices=tuple(definition.directions),
            )
        )

    return tuple(parameters)


def legacy_plugin_spec(
    effect_class: type[Effect],
    *,
    name: str | None = None,
    description: str | None = None,
) -> EffectPluginSpec:
    """Wrap a current built-in effect in the M7.1 plugin contract."""

    effect = effect_class()
    effect_id = effect.definition.id

    spec = EffectPluginSpec(
        id=effect_id,
        name=name or effect_id.replace("-", " ").title(),
        description=(
            description
            or f"Built-in Serpent {effect_id.replace('-', ' ')} effect."
        ),
        effect_class=effect_class,
        parameters=legacy_parameter_specs(effect),
    )
    spec.validate()
    return spec


__all__ = [
    "EFFECT_PLUGIN_API_VERSION",
    "EffectParameterSpec",
    "EffectPluginError",
    "EffectPluginSpec",
    "legacy_parameter_specs",
    "legacy_plugin_spec",
]
