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
Cell = tuple[int, int]


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _mix(a: Colour, b: Colour, amount: float) -> Colour:
    t = max(0.0, min(1.0, amount))
    return tuple(
        _clamp(a[i] * (1.0 - t) + b[i] * t)
        for i in range(3)
    )


class PixelEyesEffect(Effect):
    """Autonomous procedural pixel-art eyes for tiny RGB matrices."""

    definition = EffectDefinition(
        id="pixel-eyes",
        colours=2,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=8,
        recommended_spatial_positions=32,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    BASE_SEED = "serpent-e12-pixel-eyes-v1"

    # Logical 6x8 eye silhouette. Pupils are drawn separately so gaze can move.
    OPEN_MASK = (
        "00111100",
        "01111110",
        "11111111",
        "11111111",
        "01111110",
        "00111100",
    )

    WIDE_MASK = (
        "01111110",
        "11111111",
        "11111111",
        "11111111",
        "11111111",
        "01111110",
    )

    SQUINT_MASK = (
        "00000000",
        "00111100",
        "11111111",
        "11111111",
        "00111100",
        "00000000",
    )

    BLINK_MASK = (
        "00000000",
        "00000000",
        "01111110",
        "01111110",
        "00000000",
        "00000000",
    )

    @classmethod
    def _rng(cls, slot: int, namespace: str) -> random.Random:
        digest = hashlib.sha256(
            f"{cls.BASE_SEED}:{namespace}:{slot}".encode("utf-8")
        ).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    @staticmethod
    def _tempo(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        # Higher speed => shorter behavior episodes.
        return max(1.7, 4.2 - (speed - 1) * 0.22)

    @classmethod
    def _episode(cls, elapsed: float, speed: int) -> dict[str, object]:
        tempo = cls._tempo(speed)
        slot = max(0, int(elapsed // tempo))
        local = (elapsed - slot * tempo) / tempo
        rng = cls._rng(slot, "episode")

        # Most episodes are normal idle/gaze; rarer expressions punctuate them.
        roll = rng.random()
        if roll < 0.08:
            expression = "wide"
        elif roll < 0.16:
            expression = "squint"
        else:
            expression = "normal"

        gaze_choices = (-2, -1, 0, 0, 0, 1, 2)
        gaze = rng.choice(gaze_choices)

        # Sometimes the pupils glance toward each other instead of moving together.
        cross_eyed = rng.random() < 0.10

        # One or occasionally two blink moments per episode.
        blink_a = rng.uniform(0.26, 0.68)
        double = rng.random() < 0.18
        blink_b = blink_a + rng.uniform(0.08, 0.15) if double else None

        return {
            "slot": slot,
            "local": local,
            "expression": expression,
            "gaze": gaze,
            "cross_eyed": cross_eyed,
            "blink_a": blink_a,
            "blink_b": blink_b,
        }

    @staticmethod
    def _blink_amount(local: float, center: float | None) -> float:
        if center is None:
            return 0.0
        distance = abs(local - center)
        half_width = 0.045
        if distance >= half_width:
            return 0.0
        return 1.0 - distance / half_width

    @classmethod
    def _state(cls, elapsed: float, speed: int) -> dict[str, object]:
        episode = cls._episode(elapsed, speed)
        local = float(episode["local"])

        blink = max(
            cls._blink_amount(local, float(episode["blink_a"])),
            cls._blink_amount(
                local,
                None if episode["blink_b"] is None else float(episode["blink_b"]),
            ),
        )

        expression = str(episode["expression"])
        if blink > 0.55:
            expression = "blink"

        return {
            **episode,
            "blink": blink,
            "expression": expression,
        }

    @staticmethod
    def _eye_regions(target: EffectTarget) -> tuple[tuple[int, int], tuple[int, int]]:
        # Split the fixture into left and right visual regions with a central gap.
        # Regions are deliberately derived from current topology dimensions.
        eye_width = min(8, max(4, (target.columns - 4) // 2))
        left_start = max(0, 1)
        right_start = max(left_start + eye_width + 2, target.columns - eye_width - 1)
        return (
            (left_start, eye_width),
            (right_start, eye_width),
        )

    @staticmethod
    def _mask_for(expression: str) -> tuple[str, ...]:
        if expression == "blink":
            return PixelEyesEffect.BLINK_MASK
        if expression == "wide":
            return PixelEyesEffect.WIDE_MASK
        if expression == "squint":
            return PixelEyesEffect.SQUINT_MASK
        return PixelEyesEffect.OPEN_MASK

    @staticmethod
    def _sample_mask(
        mask: tuple[str, ...],
        logical_row: int,
        logical_column: int,
        region_width: int,
        target_rows: int,
    ) -> bool:
        # Map the canonical 6x8 design into the available region with nearest-cell
        # sampling so taller/wider future fixtures remain usable.
        src_row = round(
            logical_row
            * (len(mask) - 1)
            / max(1, target_rows - 1)
        )
        src_col = round(
            logical_column
            * (len(mask[0]) - 1)
            / max(1, region_width - 1)
        )
        src_row = max(0, min(len(mask) - 1, src_row))
        src_col = max(0, min(len(mask[0]) - 1, src_col))
        return mask[src_row][src_col] == "1"

    @staticmethod
    def _pupil_cells(
        target: EffectTarget,
        region_start: int,
        region_width: int,
        gaze: int,
        *,
        mirror_gaze: bool = False,
    ) -> set[Cell]:
        if target.rows < 2:
            return set()

        direction = -gaze if mirror_gaze else gaze
        center_col = region_start + region_width // 2 + direction
        center_col = max(
            region_start + 1,
            min(region_start + region_width - 2, center_col),
        )

        mid_a = max(0, target.rows // 2 - 1)
        mid_b = min(target.rows - 1, target.rows // 2)

        return {
            (mid_a, center_col),
            (mid_b, center_col),
        }

    def _render_mouse(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        state = self._state(elapsed, parameters.speed)
        blink = float(state["blink"])
        expression = str(state["expression"])

        # Mouse companion: normally eye colour, dim/fall back to background during
        # blinks, and briefly brighten together for wide-eye episodes.
        if expression == "blink":
            intensity = max(0.0, 1.0 - blink)
        elif expression == "wide":
            intensity = 1.0
        elif expression == "squint":
            intensity = 0.62
        else:
            intensity = 0.82

        current = _mix(
            parameters.colour1,
            parameters.colour2,
            intensity,
        )

        return EffectCanvas(
            target,
            background=current,
        ).frame()

    def render(
        self,
        elapsed: float,
        parameters: EffectParameters,
        target: EffectTarget,
    ) -> EffectFrame:
        target.validate()

        if target.rows <= 1 or len(target.active_cells) <= 3:
            return self._render_mouse(elapsed, parameters, target)

        state = self._state(elapsed, parameters.speed)
        expression = str(state["expression"])
        gaze = int(state["gaze"])
        cross_eyed = bool(state["cross_eyed"])
        mask = self._mask_for(expression)

        left, right = self._eye_regions(target)
        regions = (left, right)

        pupil_sets: list[set[Cell]] = []

        for eye_index, (start, width) in enumerate(regions):
            pupil_sets.append(
                self._pupil_cells(
                    target,
                    start,
                    width,
                    gaze,
                    mirror_gaze=(cross_eyed and eye_index == 1),
                )
            )

        canvas = EffectCanvas(
            target,
            background=parameters.colour1,
        )

        for row, column in target.active_cells:
            cell = (row, column)
            eye_pixel = False
            pupil_pixel = False

            for eye_index, (start, width) in enumerate(regions):
                if not (start <= column < start + width):
                    continue

                logical_column = column - start

                if self._sample_mask(
                    mask,
                    row,
                    logical_column,
                    width,
                    target.rows,
                ):
                    eye_pixel = True

                if (
                    expression != "blink"
                    and cell in pupil_sets[eye_index]
                ):
                    pupil_pixel = True

            if eye_pixel and not pupil_pixel:
                canvas.set(
                    cell,
                    parameters.colour2,
                )

        return canvas.frame()


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="pixel-eyes",
        name="Pixel Eyes",
        description=(
            "Autonomous procedural pixel-art eyes inhabit the lighting matrix. "
            "They glance around, blink, sometimes double-blink, occasionally "
            "squint or widen, and use topology-derived left/right regions rather "
            "than a fixed device model. Low-resolution mouse targets act as a "
            "synchronized eyelid/status companion."
        ),
        effect_class=PixelEyesEffect,
        input_capabilities=(),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Background Colour",
                kind="colour",
                default=(2, 2, 5),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Eye Colour",
                kind="colour",
                default=(70, 220, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Animation Speed",
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
