#!/usr/bin/env python3
from __future__ import annotations
from typing import Any
from serpent_core.effects import get_effect_definition, get_effect_plugin_spec

def effect_support_mode(fixture: Any, effect_id: str) -> str | None:
    native = fixture.data.get("effects", {}).get(effect_id)
    if isinstance(native, dict):
        return "native"
    try:
        spec = get_effect_plugin_spec(effect_id)
    except (KeyError, ValueError):
        return None
    device_class = str(getattr(fixture, "device_class", "") or "")
    if device_class and device_class in tuple(spec.render_targets or ()):
        return "software"
    return None

def effect_parameter_contract(fixture: Any, effect_id: str) -> dict[str, Any] | None:
    native = fixture.data.get("effects", {}).get(effect_id)
    if isinstance(native, dict):
        return {
            "mode":"native",
            "colours":int(native.get("colours",0)),
            "speed":bool(native.get("speed") or native.get("speeds")),
            "speeds":tuple(native.get("speeds") or ()),
            "directions":tuple(native.get("directions") or ()),
        }
    if effect_support_mode(fixture,effect_id)!="software":
        return None
    definition=get_effect_definition(effect_id)
    return {
        "mode":"software",
        "colours":int(definition.colours),
        "speed":bool(definition.speed),
        "speeds":(),
        "directions":tuple(definition.directions or ()),
    }
