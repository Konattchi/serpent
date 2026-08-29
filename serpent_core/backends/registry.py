#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any

from serpent_core.backends.base import (
    BackendError,
    LightingBackend,
)
from serpent_core.backends.software_rgb import (
    SoftwareRgbSysfsBackend,
)
from serpent_core.backends.generic_software_rgb import (
    GenericSoftwareRgbSysfsBackend,
)
from serpent_core.backends.sysfs_hardware import (
    SysfsHardwareEffectsBackend,
)
from serpent_core.fixtures import Fixture


DEFAULT_MOUSE_PROFILE = (
    Path.home()
    / ".config"
    / "serpent"
    / "profile.json"
)


def create_backend(
    fixture: Fixture,
    sysfs_path: Path,
    *,
    openrazer_device: Any | None = None,
) -> LightingBackend:
    backend = fixture.data["backend"]
    backend_type = backend["type"]

    if backend_type == "hardware-effects-sysfs":
        return SysfsHardwareEffectsBackend(
            fixture,
            sysfs_path,
            openrazer_device=openrazer_device,
        )

    if backend_type == "software-rgb-sysfs":
        service_name = backend.get("service")

        if service_name:
            return SoftwareRgbSysfsBackend(
                fixture,
                sysfs_path,
                profile_path=DEFAULT_MOUSE_PROFILE,
                service_name=str(service_name),
                openrazer_device=openrazer_device,
            )

        return GenericSoftwareRgbSysfsBackend(
            fixture,
            sysfs_path,
            openrazer_device=openrazer_device,
        )

    raise BackendError(
        f"No registered backend supports {backend_type!r}."
    )
