from __future__ import annotations

from dataclasses import dataclass
import math
import random

from serpent_core.effect_sdk import (
    Cell,
    Colour,
    EffectCanvas,
    animation_age,
    animation_phase,
    prune_expired,
    active_cell_set,
    cell_distance,
    clamp_colour,
    event_cell,
    event_matches,
    event_seed,
    event_timestamp,
    nearest_active_cell,
    scale_colour,
)
from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec


@dataclass(frozen=True)
class _Heart:
    row: int
    column: int
    started_at: float
    seed: int
    serial: int


@dataclass(frozen=True)
class _MouseHeart:
    started_at: float
    seed: int
    serial: int


def _add(a: Colour, b: Colour) -> Colour:
    # Additive composition remains effect-local in M9.3.  M9.2 owns only the
    # byte-range normalization; one effect is not enough evidence to publish
    # a general additive compositor yet.
    return clamp_colour(
        (
            a[0] + b[0],
            a[1] + b[1],
            a[2] + b[2],
        )
    )


class FlyingHeartsEffect(Effect):
    """Three-LED heart balloons rise from keyboard presses."""

    definition = EffectDefinition(
        id="flying-hearts",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=3,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    def __init__(self) -> None:
        self._hearts: list[_Heart] = []
        self._mouse_hearts: list[_MouseHeart] = []
        self._serial = 0
        self._mouse_serial = 0

    @staticmethod
    def _duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # Enough time to visibly cross all six DeathStalker rows.
        return 2.15 - (speed - 1) * 0.115

    @staticmethod
    def _mouse_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.92 - (speed - 1) * 0.045

    @staticmethod
    def _drift(seed: int, phase: float) -> float:
        """Small deterministic balloon drift; some hearts remain near-vertical."""
        rng = random.Random(seed ^ 0x4845415254)
        style = rng.randrange(5)

        # Two out of five are almost perfectly vertical.
        if style in (0, 1):
            amplitude = 0.0
            direction = 0.0
        else:
            amplitude = rng.choice((0.75, 1.0, 1.25))
            direction = rng.choice((-1.0, 1.0))

        # Gentle sideways travel plus a tiny wobble.  Rounding to physical
        # columns turns this into occasional one-cell diagonal movement.
        wobble = math.sin(
            phase * math.pi * 2.0 + rng.random() * math.pi
        ) * 0.22
        return direction * amplitude * phase + wobble

    @classmethod
    def _heart_cells(
        cls,
        heart: _Heart,
        elapsed: float,
        duration: float,
        target: EffectTarget,
    ) -> tuple[Cell, ...]:
        age = animation_age(
            elapsed,
            heart.started_at,
        )
        if age < 0.0 or age > duration:
            return ()

        phase = animation_phase(
            elapsed,
            heart.started_at,
            duration,
        )

        # The bottom point begins exactly at the pressed key.  The heart then
        # rises far enough that it naturally exits beyond row zero.
        travel = (target.rows + 2.0) * phase
        point_row = heart.row - travel
        center_column = heart.column + cls._drift(heart.seed, phase)

        # Canonical three-LED heart:
        #
        #   ● ●
        #    ●   <- bottom point / pressed-key anchor at birth
        #
        raw = (
            (point_row - 1.0, center_column - 0.5),
            (point_row - 1.0, center_column + 0.5),
            (point_row, center_column),
        )

        active = active_cell_set(target)
        cells: list[Cell] = []

        for row, column in raw:
            if row < -0.55 or row > target.rows - 0.45:
                continue
            if column < -0.55 or column > target.columns - 0.45:
                continue

            cell = nearest_active_cell(target, row, column)
            if cell is None:
                continue

            # Do not snap a balloon across large fixture holes.
            if cell_distance(cell, (row, column)) > 1.05:
                continue

            if cell in active and cell not in cells:
                cells.append(cell)

        return tuple(cells)

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
            self._hearts.append(
                _Heart(
                    row=cell[0],
                    column=cell[1],
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="flying-hearts-keyboard",
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
            self._mouse_hearts.append(
                _MouseHeart(
                    started_at=event_timestamp(event),
                    seed=event_seed(
                        event,
                        serial=serial,
                        namespace="flying-hearts-mouse",
                    ),
                    serial=serial,
                )
            )

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        duration = self._mouse_duration(parameters.speed)

        self._mouse_hearts = prune_expired(
            self._mouse_hearts,
            elapsed,
            lambda heart: duration,
        )

        active_cells = tuple(sorted(target.active_cells))
        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell in active_cells:
            colour = canvas.get(cell)

            for heart in self._mouse_hearts:
                age = animation_age(
                    elapsed,
                    heart.started_at,
                )
                if age < 0.0:
                    continue

                phase = animation_phase(
                    elapsed,
                    heart.started_at,
                    duration,
                )
                if not 0.0 <= phase <= 1.0:
                    continue

                # A tiny companion "heart beat": both zones bloom, then
                # alternate gently before fading.  It never spawns keyboard
                # balloons and keyboard presses never trigger this.
                index = active_cells.index(cell)
                if phase < 0.22:
                    intensity = phase / 0.22
                elif phase < 0.72:
                    pulse = 0.72 + 0.28 * math.sin(
                        (phase - 0.22) / 0.50 * math.pi
                        + index * math.pi * 0.45
                    )
                    intensity = max(0.35, pulse)
                else:
                    intensity = max(
                        0.0,
                        1.0 - (phase - 0.72) / 0.28,
                    )

                colour = _add(
                    colour,
                    scale_colour(parameters.colour2, intensity),
                )

            canvas.set(cell, colour)

        return canvas.frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if len(target.active_cells) < 3 or target.rows < 2:
            return self._render_mouse(elapsed, parameters, target)

        duration = self._duration(parameters.speed)

        self._hearts = prune_expired(
            self._hearts,
            elapsed,
            lambda heart: duration,
        )

        heart_cells: list[tuple[_Heart, tuple[Cell, ...], float]] = []

        for heart in self._hearts:
            age = animation_age(
                elapsed,
                heart.started_at,
            )
            phase = animation_phase(
                elapsed,
                heart.started_at,
                duration,
            )
            cells = self._heart_cells(
                heart,
                elapsed,
                duration,
                target,
            )

            # Keep balloons vivid throughout flight. Only soften them during
            # the final portion as they leave the top edge.
            intensity = 1.0
            if phase > 0.88:
                intensity = max(0.0, 1.0 - (phase - 0.88) / 0.12)

            heart_cells.append((heart, cells, intensity))

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell in target.active_cells:
            # Youngest heart wins naturally for overlapping sprites; no
            # whitening or additive washout between heart events.
            covering = [
                (heart, intensity)
                for heart, cells, intensity in heart_cells
                if cell in cells
            ]

            if not covering:
                continue

            heart, intensity = max(
                covering,
                key=lambda item: (
                    item[0].started_at,
                    item[0].serial,
                ),
            )

            canvas.set(
                cell,
                _add(
                    parameters.colour1,
                    scale_colour(parameters.colour2, intensity),
                ),
            )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="flying-hearts",
        name="Flying Hearts",
        description=(
            "Each keyboard press releases a compact three-LED heart balloon "
            "whose bottom point begins on the pressed key, then rises toward "
            "the top with gentle deterministic sideways drift. Multiple hearts "
            "can coexist. Mouse clicks use an isolated two-zone companion pulse."
        ),
        effect_class=FlyingHeartsEffect,
        input_capabilities=("keyboard", "mouse"),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(8, 6, 12),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Heart Colour",
                kind="colour",
                default=(255, 40, 120),
            ),
            EffectParameterSpec(
                id="speed",
                label="Flight Speed",
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
