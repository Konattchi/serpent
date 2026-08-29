from __future__ import annotations
from pathlib import Path
from typing import Any
from serpent_core.backends.base import BackendError, LightingBackend

class GenericSoftwareRgbSysfsBackend(LightingBackend):
    # Profile/service-free custom-frame sysfs transport.
    FRAME_ENDPOINT="matrix_custom_frame"
    CUSTOM_ENDPOINT="matrix_effect_custom"

    def __init__(self,fixture,sysfs_path:Path,*,openrazer_device:Any|None=None):
        super().__init__(fixture,sysfs_path)
        self.openrazer_device=openrazer_device

    def transport_endpoints(self):
        return (self.sysfs_path/self.FRAME_ENDPOINT,self.sysfs_path/self.CUSTOM_ENDPOINT)

    def validate_transport(self):
        missing=[p.name for p in self.transport_endpoints() if not p.exists()]
        if missing:
            raise BackendError(
                f"{self.fixture.display_name} is missing required software-RGB "
                f"transport endpoint(s): {', '.join(missing)}."
            )

    def write_frame_payload(self,payload:bytes):
        if not isinstance(payload,(bytes,bytearray)):
            raise BackendError("Custom-frame payload must be bytes.")
        self.validate_transport()
        frame,custom=self.transport_endpoints()
        try:
            frame.write_bytes(bytes(payload))
            custom.write_bytes(b"\x01")
        except PermissionError as exc:
            raise BackendError("Permission denied while writing software RGB frame.") from exc
        except OSError as exc:
            raise BackendError(f"Could not write software RGB frame: {exc}") from exc

    def set_brightness(self,brightness:int):
        if not isinstance(brightness,int) or isinstance(brightness,bool) or not 0<=brightness<=100:
            raise BackendError("Brightness must be an integer between 0 and 100.")
        if self.openrazer_device is None:
            raise BackendError("Brightness control requires a matched OpenRazer device.")
        try:
            self.openrazer_device.brightness=brightness
        except Exception as exc:
            raise BackendError(f"Could not set brightness: {exc}") from exc

    def apply(self,effect:str,settings:dict[str,Any]):
        raise BackendError(
            "Generic software-RGB fixtures are frame-rendered by Serpent's renderer; "
            "persistent profile/service effect application is not owned by this transport."
        )
