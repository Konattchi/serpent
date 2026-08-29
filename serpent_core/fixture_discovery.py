from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os, re, stat

RAZER_VENDOR_ID = "1532"
KNOWN_ENDPOINTS = (
    "matrix_brightness","matrix_custom_frame","matrix_effect_custom",
    "matrix_effect_none","matrix_effect_static","matrix_effect_spectrum",
    "matrix_effect_breath","matrix_effect_reactive","matrix_effect_wave",
    "matrix_effect_starlight","matrix_reactive_trigger",
)

@dataclass(frozen=True)
class EndpointEvidence:
    name: str
    path: Path
    readable: bool
    writable: bool
    mode: str

@dataclass(frozen=True)
class DiscoveredDevice:
    name: str
    vendor_id: str
    product_id: str
    driver: str | None
    serial: str | None
    hid_paths: tuple[Path, ...]
    endpoints: tuple[EndpointEvidence, ...]
    input_paths: tuple[Path, ...]

    @property
    def endpoint_names(self):
        return frozenset(e.name for e in self.endpoints)

    @property
    def brightness_supported(self):
        return "matrix_brightness" in self.endpoint_names

    @property
    def custom_frame_supported(self):
        n=self.endpoint_names
        return "matrix_custom_frame" in n and "matrix_effect_custom" in n

    @property
    def native_effect_endpoints(self):
        return tuple(sorted(n for n in self.endpoint_names
            if n.startswith("matrix_effect_") and n!="matrix_effect_custom"))

    @property
    def required_endpoint(self):
        if "matrix_effect_static" in self.endpoint_names:
            return "matrix_effect_static"
        return self.native_effect_endpoints[0] if self.native_effect_endpoints else None

    @property
    def clean_model_name(self):
        n=self.name.strip()
        if n.startswith("Razer Razer "): return n[len("Razer Razer "):]
        if n.startswith("Razer "): return n[len("Razer "):]
        return n

    @property
    def suggested_fixture_id(self):
        return re.sub(r"[^a-z0-9]+","-",("razer-"+self.clean_model_name).casefold()).strip("-")

    @property
    def suggested_device_class(self):
        d=(self.driver or "").casefold()
        m=self.clean_model_name.casefold()
        if "kbd" in d: return "keyboard"
        if "mouse" in d: return "mouse"
        if "accessory" in d and "goliathus" in m: return "mousepad"
        return "other"

    @property
    def suggested_backend(self):
        if self.custom_frame_supported and (self.driver or "").casefold()=="razeraccessory":
            return "software-rgb-sysfs"
        return "hardware-effects-sysfs"

    @property
    def review_items(self):
        items=[
            "Confirm device class","Confirm backend policy",
            "Confirm matrix rows/columns","Confirm zones",
            "Confirm input semantics","Confirm serial policy",
        ]
        if self.input_paths:
            items.append("Input nodes detected; do not assume semantic relevance")
        return tuple(items)

def _read_uevent(path):
    out={}
    try: text=path.read_text(encoding="utf-8",errors="replace")
    except OSError: return out
    for line in text.splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def _vid_pid(hid_id):
    m=re.search(r":([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})$",hid_id)
    if not m: return None,None
    return m.group(1)[-4:].upper(),m.group(2)[-4:].upper()

def _driver(path):
    try: return (path/"driver").resolve().name
    except OSError: return None

def _endpoints(hid_path):
    out=[]
    for name in KNOWN_ENDPOINTS:
        p=hid_path/name
        if not p.exists(): continue
        try: mode=stat.filemode(p.stat().st_mode)
        except OSError: mode="?"
        out.append(EndpointEvidence(name,p,os.access(p,os.R_OK),os.access(p,os.W_OK),mode))
    return out

def _inputs(model,root):
    if not root.is_dir(): return ()
    token=model.replace(" ","_").casefold()
    return tuple(p for p in sorted(root.iterdir())
        if "razer" in p.name.casefold() and token in p.name.casefold()
        and ("-event-" in p.name.casefold() or p.name.casefold().endswith("-mouse")))

def discover_razer_devices(hid_root=Path("/sys/bus/hid/devices"),input_root=Path("/dev/input/by-id")):
    if not hid_root.is_dir(): return ()
    grouped={}
    for hp in sorted(hid_root.iterdir()):
        u=_read_uevent(hp/"uevent")
        vid,pid=_vid_pid(u.get("HID_ID",""))
        if vid!=RAZER_VENDOR_ID or not pid: continue
        name=u.get("HID_NAME","").strip() or f"Razer {vid}:{pid}"
        key=(vid,pid,name)
        g=grouped.setdefault(key,{"paths":[],"eps":{},"driver":None,"serial":None})
        g["paths"].append(hp)
        g["driver"]=g["driver"] or _driver(hp)
        uniq=u.get("HID_UNIQ","").strip()
        g["serial"]=g["serial"] or (uniq if uniq else None)
        for ep in _endpoints(hp): g["eps"].setdefault(ep.name,ep)
    result=[]
    for (vid,pid,name),g in sorted(grouped.items()):
        clean=name
        if clean.startswith("Razer Razer "): clean=clean[len("Razer Razer "):]
        elif clean.startswith("Razer "): clean=clean[len("Razer "):]
        result.append(DiscoveredDevice(name,vid,pid,g["driver"],g["serial"],
            tuple(g["paths"]),tuple(sorted(g["eps"].values(),key=lambda x:x.name)),
            _inputs(clean,input_root)))
    return tuple(result)
