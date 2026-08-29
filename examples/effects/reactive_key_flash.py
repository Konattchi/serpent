from __future__ import annotations

from dataclasses import dataclass
import math

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
)
from serpent_core.effects.plugin import (
    EffectParameterSpec,
    EffectPluginSpec,
)


@dataclass(frozen=True)
class _Flash:
    row: int
    column: int
    started_at: float


class ReactiveKeyFlashEffect(Effect):
    """Minimal M8.5 reactive SDK example.

    Keyboard input is the only monitored source. The keyboard gets a spatial
    key flash; low-resolution targets get a short companion pulse generated
    from the same keyboard event.
    """

    definition = EffectDefinition(
        id="reactive-key-flash",
        colours=1,
        animated=True,
        speed=True,
        spatial=True,
        minimum_spatial_positions=1,
        recommended_spatial_positions=8,
        spatial_metric="cells",
        degradation_policy="spatial",
    )

    def __init__(self) -> None:
        self._flashes: list[_Flash] = []
        self._companion_pulses: list[float] = []

    @property
    def active_flash_count(self) -> int:
        return len(self._flashes)

    def handle_event(self, event: EffectEvent) -> None:
        if event.kind != "key-press":
            return

        if event.row is None or event.column is None:
            return

        self._flashes.append(
            _Flash(
                row=int(event.row),
                column=int(event.column),
                started_at=float(event.timestamp),
            )
        )
        self._companion_pulses.append(float(event.timestamp))

    @staticmethod
    def _duration(speed: int) -> float:
        speed = max(1, min(10, int(speed)))
        return 0.72 - (speed - 1) * 0.045

    @staticmethod
    def _scale_colour(
        colour: tuple[int, int, int],
        intensity: float,
    ) -> tuple[int, int, int]:
        intensity = max(0.0, min(1.0, intensity))
        return tuple(
            max(0, min(255, round(channel * intensity)))
            for channel in colour
        )

    def _render_companion(
        self,
        elapsed: float,
        parameters,
        target,
    ) -> EffectFrame:
        duration = self._duration(parameters.speed)

        self._companion_pulses = [
            started
            for started in self._companion_pulses
            if 0.0 <= elapsed - started <= duration
        ]

        strongest = 0.0

        for started in self._companion_pulses:
            phase = (elapsed - started) / duration
            # Fast ignition with a smooth tail.
            intensity = math.sin(min(1.0, phase) * math.pi)
            strongest = max(strongest, intensity)

        colour = self._scale_colour(
            parameters.colour1,
            strongest,
        )

        frame = EffectFrame(
            rows=target.rows,
            columns=target.columns,
            pixels=tuple(
                tuple(colour for _ in range(target.columns))
                for _ in range(target.rows)
            ),
        )
        frame.validate()
        return frame

    def render(self, elapsed, parameters, target):
        target.validate()

        if target.rows < 3 or target.columns < 3:
            return self._render_companion(
                elapsed,
                parameters,
                target,
            )

        duration = self._duration(parameters.speed)

        self._flashes = [
            flash
            for flash in self._flashes
            if 0.0 <= elapsed - flash.started_at <= duration
        ]

        active = set(target.active_cells)
        pixels = []

        for row in range(target.rows):
            rendered = []

            for column in range(target.columns):
                if (row, column) not in active:
                    rendered.append((0, 0, 0))
                    continue

                intensity = 0.0

                for flash in self._flashes:
                    age = elapsed - flash.started_at
                    if age < 0.0:
                        continue

                    phase = age / duration
                    fade = max(0.0, 1.0 - phase)

                    distance = math.hypot(
                        row - flash.row,
                        column - flash.column,
                    )

                    # Bright pressed key plus a tiny local halo. Multiple
                    # flashes coexist; strongest one wins at a cell.
                    local = max(
                        0.0,
                        1.0 - distance / 1.75,
                    ) * fade

                    intensity = max(intensity, local)

                rendered.append(
                    self._scale_colour(
                        parameters.colour1,
                        intensity,
                    )
                )

            pixels.append(tuple(rendered))

        frame = EffectFrame(
            rows=target.rows,
            columns=target.columns,
            pixels=tuple(pixels),
        )
        frame.validate()
        return frame


SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id="reactive-key-flash",
        name="Reactive Key Flash",
        description=(
            "M8.5 SDK example: keyboard presses briefly illuminate the "
            "pressed key while synchronized low-resolution targets receive "
            "a matching companion pulse."
        ),
        effect_class=ReactiveKeyFlashEffect,
        input_capabilities=("keyboard",),
        render_targets=("keyboard", "mouse"),
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Flash Colour",
                kind="colour",
                default=(80, 200, 255),
            ),
            EffectParameterSpec(
                id="speed",
                label="Fade Speed",
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
