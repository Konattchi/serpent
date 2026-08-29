#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from serpent_core.backends.base import BackendError
from serpent_core.backends.performance import (
    DpiStageProfile,
    PerformanceStatus,
)
from serpent_core.device import DeviceModel


@dataclass(frozen=True)
class DpiStage:
    number: int
    x: int
    y: int


@dataclass(frozen=True)
class DpiProfile:
    active_stage: int
    stages: tuple[DpiStage, ...]

    def stage(self, number: int) -> DpiStage:
        for stage in self.stages:
            if stage.number == number:
                return stage

        raise BackendError(
            f"DPI stage {number} does not exist."
        )

    def with_active_stage(
        self,
        number: int,
    ) -> DpiProfile:
        self.stage(number)
        return replace(
            self,
            active_stage=number,
        )

    def with_stage(
        self,
        number: int,
        x: int,
        y: int,
    ) -> DpiProfile:
        replacement = DpiStage(
            number=number,
            x=int(x),
            y=int(y),
        )

        found = False
        updated: list[DpiStage] = []

        for stage in self.stages:
            if stage.number == number:
                updated.append(replacement)
                found = True
            else:
                updated.append(stage)

        if not found:
            raise BackendError(
                f"DPI stage {number} does not exist."
            )

        return replace(
            self,
            stages=tuple(updated),
        )


@dataclass(frozen=True)
class PerformanceProfile:
    dpi: DpiProfile | None
    polling_rate: int | None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if self.dpi is not None:
            result["dpi"] = {
                "model": "staged",
                "active_stage": self.dpi.active_stage,
                "stages": [
                    {
                        "number": stage.number,
                        "x": stage.x,
                        "y": stage.y,
                    }
                    for stage in self.dpi.stages
                ],
            }

        if self.polling_rate is not None:
            result["polling_rate"] = self.polling_rate

        return result


def validate_dpi_value(
    device: DeviceModel,
    value: int,
) -> int:
    result = int(value)

    if result < 1:
        raise BackendError(
            "DPI values must be positive integers."
        )

    maximum = (
        device.capabilities
        .performance
        .dpi
        .maximum
    )

    if maximum is not None and result > maximum:
        raise BackendError(
            f"DPI must not exceed {maximum}."
        )

    return result


def build_dpi_profile(
    device: DeviceModel,
    raw: DpiStageProfile,
) -> DpiProfile:
    if raw.active_stage < 1:
        raise BackendError(
            "The active DPI stage must be at least 1."
        )

    stages = tuple(
        DpiStage(
            number=index,
            x=validate_dpi_value(device, x),
            y=validate_dpi_value(device, y),
        )
        for index, (x, y) in enumerate(
            raw.stages,
            start=1,
        )
    )

    if not stages:
        raise BackendError(
            "A staged DPI profile must contain at least one stage."
        )

    if raw.active_stage > len(stages):
        raise BackendError(
            "The active DPI stage is outside the available stages."
        )

    return DpiProfile(
        active_stage=raw.active_stage,
        stages=stages,
    )


def build_performance_profile(
    device: DeviceModel,
    status: PerformanceStatus,
) -> PerformanceProfile:
    dpi_profile: DpiProfile | None = None

    if status.dpi_stages is not None:
        dpi_profile = build_dpi_profile(
            device,
            status.dpi_stages,
        )

    return PerformanceProfile(
        dpi=dpi_profile,
        polling_rate=status.polling_rate,
    )
