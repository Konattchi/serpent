#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serpent_core.backends.base import BackendError
from serpent_core.device import DeviceModel


@dataclass(frozen=True)
class DpiStageProfile:
    active_stage: int
    stages: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PerformanceStatus:
    dpi: tuple[int, int] | None
    dpi_stages: DpiStageProfile | None
    polling_rate: int | None
    device_mode: tuple[int, int] | None


class PerformanceBackend:
    """Capability-oriented interface for device performance controls."""

    def get_dpi(self) -> tuple[int, int]:
        raise NotImplementedError

    def get_dpi_stages(self) -> DpiStageProfile:
        raise NotImplementedError

    def get_polling_rate(self) -> int:
        raise NotImplementedError

    def get_device_mode(self) -> tuple[int, int]:
        raise NotImplementedError

    def get_status(self) -> PerformanceStatus:
        raise NotImplementedError


class SysfsPerformanceBackend(PerformanceBackend):
    """Read and eventually write fixture-declared sysfs controls."""

    def __init__(
        self,
        device: DeviceModel,
        sysfs_path: Path,
    ) -> None:
        self.device = device
        self.sysfs_path = Path(sysfs_path)
        self.definition = self._performance_definition()

    def _performance_definition(self) -> dict[str, Any]:
        raw = self.device.fixture.data.get("performance", {})

        if not isinstance(raw, dict):
            raise BackendError(
                f"{self.device.id}: performance must be an object."
            )

        return raw

    def _section(
        self,
        name: str,
    ) -> dict[str, Any]:
        raw = self.definition.get(name)

        if not isinstance(raw, dict):
            raise BackendError(
                f"{self.device.id}: performance.{name} "
                "is not declared."
            )

        return raw

    def _endpoint(
        self,
        section_name: str,
        *,
        key: str = "endpoint",
    ) -> Path:
        section = self._section(section_name)
        endpoint_name = section.get(key)

        if not isinstance(endpoint_name, str) or not endpoint_name:
            raise BackendError(
                f"{self.device.id}: performance.{section_name}.{key} "
                "is missing."
            )

        endpoint = self.sysfs_path / endpoint_name

        if not endpoint.exists():
            raise BackendError(
                f"Performance endpoint is unavailable: {endpoint}"
            )

        return endpoint

    @staticmethod
    def _read_ascii(endpoint: Path) -> str:
        try:
            return endpoint.read_text(
                encoding="ascii"
            ).strip()
        except OSError as exc:
            raise BackendError(
                f"Could not read {endpoint.name}: {exc}"
            ) from exc

    @staticmethod
    def _read_bytes(endpoint: Path) -> bytes:
        try:
            return endpoint.read_bytes()
        except OSError as exc:
            raise BackendError(
                f"Could not read {endpoint.name}: {exc}"
            ) from exc

    def get_dpi(self) -> tuple[int, int]:
        endpoint = self._endpoint("dpi")
        raw = self._read_ascii(endpoint)

        pieces = raw.split(":")

        if len(pieces) != 2:
            raise BackendError(
                f"Unexpected DPI value from {endpoint.name}: {raw!r}"
            )

        try:
            x = int(pieces[0])
            y = int(pieces[1])
        except ValueError as exc:
            raise BackendError(
                f"Invalid DPI value from {endpoint.name}: {raw!r}"
            ) from exc

        return x, y

    def get_dpi_stages(self) -> DpiStageProfile:
        endpoint = self._endpoint(
            "dpi",
            key="stages_endpoint",
        )
        raw = self._read_bytes(endpoint)

        if len(raw) < 5 or (len(raw) - 1) % 4 != 0:
            raise BackendError(
                f"Unexpected DPI-stage payload length: {len(raw)}"
            )

        active_stage = int(raw[0])
        stages: list[tuple[int, int]] = []

        for offset in range(1, len(raw), 4):
            x = int.from_bytes(
                raw[offset:offset + 2],
                byteorder="big",
            )
            y = int.from_bytes(
                raw[offset + 2:offset + 4],
                byteorder="big",
            )
            stages.append((x, y))

        return DpiStageProfile(
            active_stage=active_stage,
            stages=tuple(stages),
        )

    def get_polling_rate(self) -> int:
        endpoint = self._endpoint("polling_rate")
        raw = self._read_ascii(endpoint)

        try:
            return int(raw)
        except ValueError as exc:
            raise BackendError(
                f"Invalid polling-rate value from "
                f"{endpoint.name}: {raw!r}"
            ) from exc

    def get_device_mode(self) -> tuple[int, int]:
        endpoint = self._endpoint("device_mode")
        raw = self._read_bytes(endpoint)

        if len(raw) != 2:
            raise BackendError(
                f"Unexpected device-mode payload length: {len(raw)}"
            )

        return int(raw[0]), int(raw[1])

    def get_status(self) -> PerformanceStatus:
        return PerformanceStatus(
            dpi=(
                self.get_dpi()
                if self.device.capabilities.performance.dpi
                else None
            ),
            dpi_stages=(
                self.get_dpi_stages()
                if self.device.capabilities.performance.dpi
                else None
            ),
            polling_rate=(
                self.get_polling_rate()
                if self.device.capabilities.performance.polling_rate
                else None
            ),
            device_mode=(
                self.get_device_mode()
                if "device_mode" in self.definition
                else None
            ),
        )
