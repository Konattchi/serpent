from __future__ import annotations
from serpent_core.effect_sdk import animation_age, animation_phase, prune_expired
from serpent_core.effect_sdk import EffectCanvas

from dataclasses import dataclass
import math

from serpent_core.effect_random import event_seed
from serpent_core.effect_sdk import event_cell, event_matches, event_timestamp
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour = tuple[int, int, int]
Cell = tuple[int, int]


@dataclass(frozen=True)
class _Implosion:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseImplosion:
    started_at: float
    seed: int
    serial: int


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _scale(colour: Colour, amount: float) -> Colour:
    amount = max(0.0, float(amount))
    return tuple(_clamp(channel * amount) for channel in colour)


def _add(a: Colour, b: Colour) -> Colour:
    return tuple(_clamp(x + y) for x, y in zip(a, b))


class ImplosionEffect(Effect):
    """A spatial energy ring collapses inward toward the pressed key."""

    definition = EffectDefinition(
        id="implosion",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    MAX_RADIUS = 4.8

    def __init__(self) -> None:
        self._implosions: list[_Implosion] = []
        self._mouse_implosions: list[_MouseImplosion] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 1.18 - (speed - 1) * 0.075

    @staticmethod
    def _mouse_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.82 - (speed - 1) * 0.045

    def handle_event(self, event: EffectEvent) -> None:
        if event_matches(
            event,
            kind="key-press",
            source_prefix="keyboard:",
        ):
            cell = event_cell(event)
            if cell is None:
                return
            serial = self._serial
            self._serial += 1
            self._implosions.append(
                _Implosion(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="implosion-keyboard",
                    ),
                    serial=serial,
                )
            )
            return

        if event_matches(
            event,
            kind="mouse-press",
            source_prefix="mouse:",
        ):
            serial = self._mouse_serial
            self._mouse_serial += 1
            self._mouse_implosions.append(
                _MouseImplosion(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="implosion-mouse",
                    ),
                    serial=serial,
                )
            )

    @staticmethod
    def _nearest_active(
        target: EffectTarget,
        row: float,
        column: float,
    ) -> Cell:
        return min(
            target.active_cells,
            key=lambda cell: (
                (cell[0] - row) ** 2 + (cell[1] - column) ** 2,
                cell[0],
                cell[1],
            ),
        )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        duration = self._mouse_duration(parameters.speed)

        self._mouse_implosions = prune_expired(
            self._mouse_implosions,
            elapsed,
            lambda _state: duration,
        )

        active_cells = tuple(sorted(target.active_cells))
        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell in active_cells:
            colour = parameters.colour1

            for event in self._mouse_implosions:
                age = animation_age(
                    elapsed,
                    event.started_at,
                )
                if age < 0.0:
                    continue

                phase = animation_phase(
                    elapsed,
                    event.started_at,
                    duration,
                )
                if not 0.0 <= phase <= 1.0:
                    continue

                # Two controllable LEDs behave like an outer pair collapsing
                # toward one final hot compression point.
                if len(active_cells) <= 1:
                    position = 0.0
                else:
                    position = active_cells.index(cell) / (
                        len(active_cells) - 1
                    )

                center = 0.5

                if phase < 0.18:
                    # Outer field appears quickly.
                    intensity = 0.55
                elif phase < 0.68:
                    collapse = (phase - 0.18) / 0.50
                    radius = 0.60 * (1.0 - collapse)
                    distance = abs(position - center)
                    width = 0.34
                    delta = abs(distance - radius)
                    intensity = max(0.0, 1.0 - delta / width)
                    intensity = max(intensity, 0.12)
                elif phase < 0.82:
                    # Final compression snap.
                    intensity = 1.0
                else:
                    intensity = max(
                        0.0,
                        1.0 - (phase - 0.82) / 0.18,
                    )

                colour = _add(
                    colour,
                    _scale(parameters.colour2, intensity),
                )

            canvas.set(
                cell,
                colour,
            )

        return canvas.frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if len(target.active_cells) < 3 or target.rows < 2:
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        duration = self._duration(parameters.speed)

        self._implosions = prune_expired(
            self._implosions,
            elapsed,
            lambda _state: duration,
        )

        centers = [
            (
                event,
                self._nearest_active(
                    target,
                    event.row,
                    event.column,
                ),
            )
            for event in self._implosions
        ]

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for row, column in target.active_cells:
            cell = (row, column)

            # User-selected readable background, unchanged.
            colour = parameters.colour1

            for event, center in centers:
                age = animation_age(
                    elapsed,
                    event.started_at,
                )
                if age < 0.0:
                    continue

                phase = animation_phase(
                    elapsed,
                    event.started_at,
                    duration,
                )
                if not 0.0 <= phase <= 1.0:
                    continue

                distance = math.hypot(
                    row - center[0],
                    column - center[1],
                )

                if phase < 0.14:
                    # Outer energy field appears quickly at ~4-5 cells.
                    radius = self.MAX_RADIUS
                    width = 1.10
                    intensity = max(
                        0.0,
                        1.0 - abs(distance - radius) / width,
                    ) * (phase / 0.14)

                elif phase < 0.72:
                    # Collapse ring inward toward the impact point.
                    collapse = (phase - 0.14) / 0.58
                    radius = self.MAX_RADIUS * (1.0 - collapse)

                    # Ring tightens as it approaches the key.
                    width = 1.15 - collapse * 0.45
                    front = max(
                        0.0,
                        1.0 - abs(distance - radius) / max(width, 0.25),
                    )

                    # A growing central pull gives the convergence a sense
                    # of energy being compressed rather than merely erased.
                    core_radius = 0.55 + collapse * 1.15
                    core = max(
                        0.0,
                        1.0 - distance / max(core_radius, 0.001),
                    ) * (0.20 + collapse * 0.58)

                    intensity = max(front, core)

                elif phase < 0.84:
                    # Short full-hue compression snap at the center.
                    snap = 1.0 - abs(phase - 0.78) / 0.06
                    snap = max(0.0, min(1.0, snap))

                    if distance <= 0.65:
                        intensity = 0.72 + 0.28 * snap
                    elif distance <= 1.55:
                        intensity = 0.25 * snap
                    else:
                        intensity = 0.0

                else:
                    # Final center afterglow fades cleanly.
                    fade = max(
                        0.0,
                        1.0 - (phase - 0.84) / 0.16,
                    )
                    intensity = (
                        fade
                        * max(
                            0.0,
                            1.0 - distance / 1.35,
                        )
                    )

                if intensity <= 0.0:
                    continue

                # Preserve exact chosen implosion hue; brightness only.
                colour = _add(
                    colour,
                    _scale(parameters.colour2, intensity),
                )

            canvas.set(
                cell,
                colour,
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="implosion",
        name="Implosion",
        description=(
            "A broad energy ring appears around the pressed key and collapses "
            "inward, concentrating into a vivid central compression snap before "
            "fading. Background and implosion colours remain user-controlled. "
            "Keyboard and mouse reactions are isolated."
        ),
        effect_class=ImplosionEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(10, 10, 16),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Implosion Colour",
                kind="colour",
                default=(170, 70, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Collapse Speed",
                kind="integer",
                default=5,
                minimum=1,
                maximum=10,
            ),
        ),
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
