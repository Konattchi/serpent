#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path.home() / ".local" / "share" / "serpent"
sys.path.insert(0, str(ROOT))


def emit(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


class Worker:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="serpent-effect-lab-")
        self.path = Path(self.temp.name) / "candidate.py"
        self.loaded = None
        self.spec = None
        self.effect = None

    def close(self) -> None:
        self.temp.cleanup()

    def _spec_payload(self, spec) -> dict:
        return {
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "input_capabilities": list(spec.input_capabilities or ()),
            "render_targets": list(spec.render_targets),
            "parameters": [
                {
                    "id": parameter.id,
                    "label": parameter.label,
                    "kind": parameter.kind,
                    "default": parameter.default,
                    "minimum": parameter.minimum,
                    "maximum": parameter.maximum,
                    "choices": list(parameter.choices),
                }
                for parameter in spec.parameters
            ],
        }

    def load(self, request: dict) -> dict:
        from effect_dev import validate_file

        self.path.write_text(str(request.get("source", "")), encoding="utf-8")
        loaded, result = validate_file(self.path, allow_installed_id=True)

        if result.errors:
            self.loaded = self.spec = self.effect = None
            return {
                "ok": False,
                "stage": "validation",
                "errors": list(result.errors),
                "warnings": list(result.warnings),
            }

        requested = request.get("effect_id")
        spec = next(
            (item for item in loaded.specs if item.id == requested),
            None,
        )
        if spec is None and len(loaded.specs) == 1:
            spec = loaded.specs[0]

        self.loaded = loaded
        self.spec = spec
        self.effect = spec.effect_class() if spec is not None else None

        return {
            "ok": True,
            "stage": "loaded",
            "warnings": list(result.warnings),
            "specs": [self._spec_payload(item) for item in loaded.specs],
            "effect_id": spec.id if spec is not None else None,
        }

    def select(self, request: dict) -> dict:
        if self.loaded is None:
            raise RuntimeError("No candidate source is loaded.")

        effect_id = request.get("effect_id")
        spec = next(
            (item for item in self.loaded.specs if item.id == effect_id),
            None,
        )
        if spec is None:
            raise RuntimeError(
                f"Effect id {effect_id!r} is not declared by the loaded source."
            )

        self.spec = spec
        self.effect = spec.effect_class()
        return {"ok": True, "stage": "selected", "effect_id": spec.id}

    def reset(self, request: dict) -> dict:
        if self.spec is None:
            raise RuntimeError("No effect is selected.")
        self.effect = self.spec.effect_class()
        return {"ok": True, "stage": "reset", "effect_id": self.spec.id}

    def event(self, request: dict) -> dict:
        if self.effect is None:
            raise RuntimeError("No effect instance is active.")

        from serpent_core.effects.base import EffectEvent

        raw = request["event"]
        self.effect.handle_event(
            EffectEvent(
                kind=str(raw["kind"]),
                timestamp=float(raw["timestamp"]),
                source=str(raw["source"]),
                code=str(raw["code"]),
                value=int(raw.get("value", 1)),
                row=raw.get("row"),
                column=raw.get("column"),
            )
        )
        return {"ok": True, "stage": "event"}

    def _effect_target(self, request):
        from serpent_core.effects.base import EffectTarget

        raw = request.get("target")
        if not isinstance(raw, dict):
            raise RuntimeError("Effect Lab render target must be an object.")

        rows = int(raw["rows"])
        columns = int(raw["columns"])
        active_cells = tuple(
            (int(cell[0]), int(cell[1]))
            for cell in raw.get("active_cells", ())
        )

        if rows <= 0 or columns <= 0:
            raise RuntimeError(
                "Effect Lab render target dimensions must be positive."
            )

        if not active_cells:
            active_cells = tuple(
                (row, column)
                for row in range(rows)
                for column in range(columns)
            )

        return EffectTarget(
            rows=rows,
            columns=columns,
            active_cells=active_cells,
            device_class=(
                str(raw["device_class"])
                if raw.get("device_class") is not None
                else None
            ),
        )

    @staticmethod
    def _mask_inactive(frame, target):
        from serpent_core.effects.base import EffectFrame

        active = set(target.active_cells)
        pixels = tuple(
            tuple(
                frame.pixels[row][column]
                if (row, column) in active
                else (0, 0, 0)
                for column in range(frame.columns)
            )
            for row in range(frame.rows)
        )
        result = EffectFrame(
            rows=frame.rows,
            columns=frame.columns,
            pixels=pixels,
        )
        result.validate()
        return result

    def render(self, request: dict) -> dict:
        if self.spec is None or self.effect is None:
            raise RuntimeError("No effect instance is active.")

        from effect_dev import default_effect_parameters
        from serpent_core.effects.base import EffectParameters

        defaults = default_effect_parameters(self.spec)
        values = {
            "brightness": defaults.brightness,
            "colour1": defaults.colour1,
            "colour2": defaults.colour2,
            "speed": defaults.speed,
            "direction": defaults.direction,
        }

        for key, value in dict(request.get("parameters") or {}).items():
            if key in values:
                values[key] = (
                    tuple(value)
                    if key in {"colour1", "colour2"}
                    else value
                )

        parameters = EffectParameters(**values)
        target = self._effect_target(request)

        frame = self.effect.render(
            float(request.get("elapsed", 0.0)),
            parameters,
            target,
        )
        frame.validate()

        if frame.rows != target.rows or frame.columns != target.columns:
            raise RuntimeError(
                "Effect returned a frame with dimensions "
                f"{frame.rows}×{frame.columns}; "
                f"preview fixture requires {target.rows}×{target.columns}."
            )

        frame = self._mask_inactive(frame, target)

        return {
            "ok": True,
            "stage": "render",
            "frame": {
                "rows": frame.rows,
                "columns": frame.columns,
                "pixels": frame.pixels,
            },
        }

    def handle(self, request: dict) -> dict:
        action = request.get("action")
        if action == "load":
            return self.load(request)
        if action == "select":
            return self.select(request)
        if action == "reset":
            return self.reset(request)
        if action == "event":
            return self.event(request)
        if action == "render":
            return self.render(request)
        if action == "ping":
            return {"ok": True, "stage": "pong"}
        raise RuntimeError(f"Unknown Effect Lab worker action: {action!r}")


def main() -> int:
    worker = Worker()
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            request_id = None
            try:
                request = json.loads(line)
                request_id = request.get("request_id")
                payload = worker.handle(request)
            except Exception as exc:
                payload = {
                    "ok": False,
                    "stage": "worker",
                    "errors": [f"{type(exc).__name__}: {exc}"],
                    "traceback": traceback.format_exc(limit=12),
                }

            payload["request_id"] = request_id
            emit(payload)
    finally:
        worker.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
