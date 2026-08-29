#!/usr/bin/env python3
from __future__ import annotations
from serpent_core.effect_sdk import EffectCanvas

import hashlib
import math
import random

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

Colour = tuple[int, int, int]


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(a: Colour, b: Colour, amount: float) -> Colour:
    t = max(0.0, min(1.0, amount))
    return tuple(
        _clamp(a[i] * (1.0 - t) + b[i] * t)
        for i in range(3)
    )


class RainEffect(Effect):
    """Autonomous vertical rain with lightweight independent droplets."""

    definition = EffectDefinition(
        id="rain",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=2,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    BASE_SEED = "serpent-e9-rain-v1"

    @staticmethod
    def _spawn_interval(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return max(0.12, 0.34 - (speed - 1) * 0.018)

    @staticmethod
    def _fall_duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return max(0.42, 1.18 - (speed - 1) * 0.065)

    @classmethod
    def _rng(cls, index: int) -> random.Random:
        digest = hashlib.sha256(
            f"{cls.BASE_SEED}:{index}".encode("utf-8")
        ).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    @classmethod
    def _drop(cls, index: int, target: EffectTarget) -> dict[str, float | int]:
        rng = cls._rng(index)
        return {
            "column": rng.randrange(max(1, target.columns)),
            "delay": rng.uniform(0.0, 0.08),
            "speed_scale": rng.uniform(0.86, 1.14),
            "tail_strength": rng.uniform(0.34, 0.52),
        }

    def _active_indices(
        self,
        elapsed: float,
        parameters: EffectParameters,
    ) -> range:
        interval = self._spawn_interval(parameters.speed)
        duration = self._fall_duration(parameters.speed)
        newest = max(0, math.floor(max(0.0, elapsed) / interval))
        lookback = math.ceil(duration / interval) + 3
        return range(max(0, newest - lookback), newest + 1)

    @staticmethod
    def _is_mouse(target: EffectTarget) -> bool:
        return target.rows <= 1 or len(target.active_cells) <= 3

    @staticmethod
    def _mouse_drop_interval(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # The mouse represents a dramatically smaller physical area than the
        # keyboard, so only an occasional logical raindrop should cross it.
        # Keep substantial quiet background time between pulses.
        return max(1.35, 2.45 - (speed - 1) * 0.09)

    @classmethod
    def _mouse_drop_start(
        cls,
        index: int,
        parameters: EffectParameters,
    ) -> float:
        interval = cls._mouse_drop_interval(parameters.speed)
        rng = cls._rng(100000 + index)
        # Small deterministic jitter stops the mouse pulse from feeling like
        # a metronome while retaining reproducible offline tests.
        jitter = rng.uniform(-0.24, 0.24)
        return max(0.0, index * interval + jitter)

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        interval = self._mouse_drop_interval(parameters.speed)
        duration = min(
            0.42,
            self._fall_duration(parameters.speed) * 0.44,
        )

        active_cells = tuple(sorted(target.active_cells))
        active = set(active_cells)

        # Search the current/previous occasional mouse-drop slots. Most of the
        # time no drop is active, so the mouse rests entirely on Background Colour.
        newest = max(0, math.floor(max(0.0, elapsed) / interval) + 1)
        phase = None

        for index in range(max(0, newest - 2), newest + 1):
            drop_start = self._mouse_drop_start(index, parameters)
            candidate = (elapsed - drop_start) / max(duration, 0.001)

            if 0.0 <= candidate <= 1.0:
                phase = candidate
                break

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        if phase is not None and active_cells:
            count = max(1, len(active_cells))
            center = phase * count

            for index, cell in enumerate(active_cells):
                # First zone brightens, then the next one, like a tiny falling
                # droplet passing across the two controllable mouse LEDs.
                distance = abs(index - center)
                intensity = max(0.0, 1.0 - distance / 0.75)

                if intensity > 0.0:
                    canvas.set(
                        cell,
                        _mix(
                            parameters.colour1,
                            parameters.colour2,
                            intensity,
                        ),
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

        active = set(target.active_cells)
        interval = self._spawn_interval(parameters.speed)
        duration = self._fall_duration(parameters.speed)

        overlays: dict[tuple[int, int], float] = {}

        def paint(row: int, column: int, intensity: float) -> None:
            cell = (row, column)
            if cell not in active or intensity <= 0.0:
                return
            overlays[cell] = max(
                overlays.get(cell, 0.0),
                intensity,
            )

        for index in self._active_indices(elapsed, parameters):
            drop = self._drop(index, target)
            started_at = index * interval + float(drop["delay"])
            age = elapsed - started_at

            if age < 0.0:
                continue

            local_duration = duration / float(drop["speed_scale"])
            phase = age / max(local_duration, 0.001)

            if not 0.0 <= phase <= 1.0:
                continue

            column = int(drop["column"])

            # Start just above row zero and leave just beyond the bottom.
            head_position = -0.55 + phase * (target.rows + 1.10)
            head_row = round(head_position)

            if 0 <= head_row < target.rows:
                paint(head_row, column, 1.0)

            tail_position = head_position - 1.0
            tail_row = round(tail_position)

            if 0 <= tail_row < target.rows:
                paint(
                    tail_row,
                    column,
                    float(drop["tail_strength"]),
                )

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for cell, intensity in overlays.items():
            if intensity > 0.0:
                canvas.set(
                    cell,
                    _mix(
                        parameters.colour1,
                        parameters.colour2,
                        intensity,
                    ),
                )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="rain",
        name="Rain",
        description=(
            "Autonomous vertical rain. Independent droplets spawn across random "
            "top-edge columns, fall straight downward with slightly varied timing, "
            "use bright heads with dim tails, and leave naturally below the matrix. "
            "Low-resolution mouse targets receive occasional, widely spaced "
            "two-zone falling-drop pulses with quiet background intervals."
        ),
        effect_class=RainEffect,
        input_capabilities=(),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(5, 8, 14),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Rain Colour",
                kind="colour",
                default=(80, 150, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Rain Speed",
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
