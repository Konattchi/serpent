#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import random

from serpent_core.effect_sdk import (
    Cell,
    Colour,
    EffectCanvas,
    animation_age,
    animation_phase,
    prune_expired,
    cell_distance,
    event_cell,
    event_matches,
    event_seed,
    event_timestamp,
    hsv_colour,
    mix_colour,
)
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec


@dataclass(frozen=True)
class _Ripple:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int
    colour: Colour


@dataclass(frozen=True)
class _MouseRipple:
    started_at: float
    seed: int
    serial: int
    colour: Colour


def _event_colour(seed: int) -> Colour:
    rng = random.Random(seed ^ 0x535045435452554D)
    return hsv_colour(
        rng.random(),
        rng.uniform(0.88, 1.0),
        rng.uniform(0.92, 1.0),
    )


class SpectrumRipplesEffect(Effect):
    """Continuous spectrum base with youngest-wins random-colour ripples."""

    definition = EffectDefinition(
        id="spectrum-ripples",
        colours=0,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    def __init__(self) -> None:
        self._ripples: list[_Ripple] = []
        self._mouse_ripples: list[_MouseRipple] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _spectrum_colour(
        elapsed: float,
        speed: int,
        row: int,
        column: int,
        target: EffectTarget,
    ) -> Colour:
        speed = max(1, min(10, int(speed)))

        # True Spectrum base: every active cell shares the same hue at a given
        # instant, and the whole device smoothly cycles through the hue wheel.
        # row/column/target remain in the signature so keyboard/mouse render
        # paths can use one helper without introducing topology-specific code.
        time_phase = elapsed * (0.045 + speed * 0.014)

        return hsv_colour(
            time_phase,
            1.0,
            1.0,
        )

    @staticmethod
    def _ripple_speed(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 7.2 + speed * 0.95

    @staticmethod
    def _ring_width(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return max(0.62, 1.05 - speed * 0.022)

    @classmethod
    def _max_radius(
        cls,
        ripple: _Ripple,
        target: EffectTarget,
    ) -> float:
        # Lifetime is origin-aware: the ripple is retained until its farthest
        # possible arc has actually left the fixture.
        corners = (
            (0, 0),
            (0, target.columns - 1),
            (target.rows - 1, 0),
            (target.rows - 1, target.columns - 1),
        )

        origin = (ripple.row, ripple.column)

        return max(
            cell_distance(origin, corner)
            for corner in corners
        ) + 1.6

    @classmethod
    def _duration(
        cls,
        ripple: _Ripple,
        target: EffectTarget,
        speed: int,
    ) -> float:
        return (
            cls._max_radius(ripple, target)
            / cls._ripple_speed(speed)
        )

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

            seed = event_seed(
                event,
                serial=serial,
                namespace="spectrum-ripples-keyboard",
            )

            self._ripples.append(
                _Ripple(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=seed,
                    serial=serial,
                    colour=_event_colour(seed),
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

            seed = event_seed(
                event,
                serial=serial,
                namespace="spectrum-ripples-mouse",
            )

            self._mouse_ripples.append(
                _MouseRipple(
                    started_at=event_timestamp(event),
                    seed=seed,
                    serial=serial,
                    colour=_event_colour(seed),
                )
            )

    @staticmethod
    def _is_mouse(target: EffectTarget) -> bool:
        return (
            target.rows <= 1
            or len(target.active_cells) <= 3
        )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        speed = max(1, min(10, int(parameters.speed)))
        duration = max(
            0.36,
            0.82 - (speed - 1) * 0.042,
        )

        self._mouse_ripples = prune_expired(
            self._mouse_ripples,
            elapsed,
            lambda ripple: duration,
        )

        active_cells = tuple(
            sorted(target.active_cells)
        )

        # Youngest mouse ripple owns the companion overlay too.
        youngest = (
            max(
                self._mouse_ripples,
                key=lambda ripple: (
                    ripple.started_at,
                    ripple.serial,
                ),
            )
            if self._mouse_ripples
            else None
        )

        base = self._spectrum_colour(
            elapsed,
            parameters.speed,
            0,
            0,
            target,
        )

        canvas = EffectCanvas(
            target,
            background=base,
        )

        if (
            youngest is not None
            and active_cells
        ):
            phase = animation_phase(
                elapsed,
                youngest.started_at,
                duration,
            )

            for index, cell in enumerate(active_cells):
                center = phase * (
                    len(active_cells) + 0.75
                )

                distance = abs(
                    index - center
                )

                intensity = max(
                    0.0,
                    1.0 - distance / 0.82,
                )

                if phase > 0.68:
                    intensity *= max(
                        0.0,
                        1.0 - (phase - 0.68) / 0.32,
                    )

                if intensity > 0.0:
                    canvas.mix(
                        cell,
                        youngest.colour,
                        intensity,
                    )

        return canvas.frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if self._is_mouse(target):
            return self._render_mouse(
                elapsed,
                parameters,
                target,
            )

        speed = max(1, min(10, int(parameters.speed)))

        # Expire only once each ripple has had enough time to leave the matrix
        # from its own origin.
        self._ripples = prune_expired(
            self._ripples,
            elapsed,
            lambda ripple: self._duration(
                ripple,
                target,
                speed,
            ),
        )

        ripple_speed = self._ripple_speed(speed)
        ring_width = self._ring_width(speed)

        base = self._spectrum_colour(
            elapsed,
            speed,
            0,
            0,
            target,
        )

        canvas = EffectCanvas(
            target,
            background=base,
        )

        for cell in target.active_cells:
            row, column = cell

            winner: tuple[
                float,
                int,
                float,
                Colour,
            ] | None = None

            for ripple in self._ripples:
                age = animation_age(
                    elapsed,
                    ripple.started_at,
                )

                if age < 0.0:
                    continue

                radius = age * ripple_speed

                distance = cell_distance(
                    (ripple.row, ripple.column),
                    cell,
                )

                delta = abs(
                    distance - radius
                )

                if delta > ring_width:
                    continue

                # Crest profile: center of ring is vivid, shoulders soften
                # into the underlying spectrum.
                intensity = max(
                    0.0,
                    1.0 - delta / ring_width,
                )

                # IMPORTANT compositor rule:
                # newest ripple wins the cell outright; intensity is not
                # compared across ripples and colours are never added.
                candidate = (
                    ripple.started_at,
                    ripple.serial,
                    intensity,
                    ripple.colour,
                )

                if (
                    winner is None
                    or candidate[0] > winner[0]
                    or (
                        candidate[0] == winner[0]
                        and candidate[1] > winner[1]
                    )
                ):
                    winner = candidate

            if winner is None:
                continue

            _, _, intensity, colour = winner
            canvas.mix(
                cell,
                colour,
                intensity,
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="spectrum-ripples",
        name="Spectrum Ripples",
        description=(
            "A continuously animated whole-device spectrum forms the base layer. "
            "Each keyboard or mouse press creates a vivid deterministic random-"
            "colour ripple. Multiple ripples coexist, but at intersections the "
            "youngest ripple owns the cell instead of additive colour blending."
        ),
        effect_class=SpectrumRipplesEffect,
        input_capabilities=(
            "keyboard",
            "mouse",
        ),
        render_targets=(
            "keyboard",
            "mouse",
        ),
        parameters=(
            EffectParameterSpec(
                id="speed",
                label="Speed",
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
