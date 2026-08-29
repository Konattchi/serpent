from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serpent_core.fixtures import Fixture, FixtureError, load_fixture


class FixtureEditorError(RuntimeError):
    """Raised when an editor document cannot be loaded, edited, or validated."""


@dataclass
class ValidationResult:
    fixture: Fixture
    path: Path


class FixtureDocument:
    """In-memory Fixture Schema v1 document with unknown-field preservation."""

    def __init__(self, data: dict[str, Any], *, source_path: Path | None = None):
        if not isinstance(data, dict):
            raise FixtureEditorError("Fixture document root must be a JSON object.")
        self._data = copy.deepcopy(data)
        self.source_path = source_path

    @classmethod
    def open(cls, path: Path) -> "FixtureDocument":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise FixtureEditorError(f"Could not read {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FixtureEditorError(
                f"{path.name}: invalid JSON at line {exc.lineno}, column {exc.colno}."
            ) from exc
        return cls(data, source_path=path)

    @classmethod
    def new(
        cls,
        *,
        fixture_id: str,
        manufacturer: str,
        model: str,
        device_class: str,
        vendor_id: str,
        product_id: str,
        backend_type: str,
        rows: int,
        columns: int,
    ) -> "FixtureDocument":
        data: dict[str, Any] = {
            "schema_version": 1,
            "id": fixture_id,
            "manufacturer": manufacturer,
            "model": model,
            "device_class": device_class,
            "usb": {
                "vendor_id": vendor_id.upper(),
                "product_id": product_id.upper(),
            },
            "backend": {
                "type": backend_type,
            },
            "capabilities": {
                "matrix": {
                    "rows": int(rows),
                    "columns": int(columns),
                },
            },
            "effects": {
                "static": {
                    "backend": "software"
                }
                if backend_type == "software-rgb-sysfs"
                else {
                    "endpoint": "matrix_effect_static",
                    "payload": "rgb",
                    "colours": 1,
                },
            },
        }
        return cls(data)

    @property
    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self._data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return copy.deepcopy(default)
            current = current[part]
        return copy.deepcopy(current)

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        if not all(parts):
            raise FixtureEditorError("Field path may not be empty.")
        current: dict[str, Any] = self._data
        for part in parts[:-1]:
            child = current.get(part)
            if child is None:
                child = {}
                current[part] = child
            if not isinstance(child, dict):
                raise FixtureEditorError(
                    f"Cannot descend through non-object field {part!r} in {path!r}."
                )
            current = child
        current[parts[-1]] = copy.deepcopy(value)

    def remove(self, path: str) -> bool:
        parts = path.split(".")
        current: Any = self._data
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        if not isinstance(current, dict):
            return False
        return current.pop(parts[-1], None) is not None

    def ensure_render_only(self) -> None:
        self._data.pop("input", None)

    def set_matrix(self, rows: int, columns: int) -> None:
        if rows < 1 or columns < 1:
            raise FixtureEditorError("Matrix rows and columns must be positive integers.")
        capabilities = self._data.setdefault("capabilities", {})
        if not isinstance(capabilities, dict):
            raise FixtureEditorError("capabilities must be an object.")
        capabilities["matrix"] = {"rows": int(rows), "columns": int(columns)}

    def clear_zones(self) -> None:
        self._data.pop("zones", None)

    def set_zone(
        self,
        zone_id: str,
        *,
        name: str,
        zone_type: str,
        columns: list[int],
        visible: bool = True,
        confirmed: bool = True,
        controllable: bool = True,
        notes: str | None = None,
    ) -> None:
        zones = self._data.setdefault("zones", {})
        if not isinstance(zones, dict):
            raise FixtureEditorError("zones must be an object.")
        definition: dict[str, Any] = {
            "name": name,
            "type": zone_type,
            "mapping": {
                "type": "matrix-columns",
                "columns": [int(column) for column in columns],
            },
            "visible": bool(visible),
            "confirmed": bool(confirmed),
            "controllable": bool(controllable),
        }
        if notes:
            definition["notes"] = notes
        zones[zone_id] = definition

    def set_backend(
        self,
        backend_type: str,
        *,
        sysfs_required_endpoint: str | None = None,
        service: str | None = None,
        linked_source_zone: str | None = None,
    ) -> None:
        backend: dict[str, Any] = {"type": backend_type}
        if sysfs_required_endpoint:
            backend["sysfs_required_endpoint"] = sysfs_required_endpoint
        if service:
            backend["service"] = service
        if linked_source_zone:
            backend["linked_source_zone"] = linked_source_zone
        self._data["backend"] = backend

    def validate(self) -> ValidationResult:
        with tempfile.TemporaryDirectory(prefix="serpent-fixture-editor-") as temp_dir:
            path = Path(temp_dir) / f"{self._data.get('id', 'candidate')}.json"
            path.write_text(self.to_json(), encoding="utf-8")
            fixture = load_fixture(path)
            # Return a fixture object detached from the temporary file by
            # reconstructing it from the validated data through a stable temp copy.
            return ValidationResult(fixture=fixture, path=path)

    def validate_data(self) -> Fixture:
        with tempfile.TemporaryDirectory(prefix="serpent-fixture-editor-") as temp_dir:
            path = Path(temp_dir) / f"{self._data.get('id', 'candidate')}.json"
            path.write_text(self.to_json(), encoding="utf-8")
            fixture = load_fixture(path)
            return Fixture(path=self.source_path or Path("<fixture-editor>"), data=copy.deepcopy(fixture.data))

    def to_json(self) -> str:
        return json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"

    def export(self, path: Path, *, validate: bool = True) -> Path:
        if validate:
            self.validate_data()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def semantically_equal(self, other: "FixtureDocument") -> bool:
        return self._data == other._data

    def set_zone_sync_groupable(
        self,
        zone_id: str,
        enabled: bool,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("sync_groupable must be boolean.")
        zones = self._data.setdefault("zones", {})
        if not isinstance(zones, dict):
            raise ValueError("Fixture zones must be an object.")
        zone = zones.setdefault(zone_id, {})
        if not isinstance(zone, dict):
            raise ValueError(
                f"Fixture zone {zone_id!r} must be an object."
            )
        zone["sync_groupable"] = enabled

    def apply_reference_sync_groupability(self) -> None:
        zones = self._data.get("zones", {})
        if not isinstance(zones, dict):
            return
        for definition in zones.values():
            if not isinstance(definition, dict):
                continue
            confirmed = bool(definition.get("confirmed", True))
            controllable = bool(
                definition.get("controllable", confirmed)
            )
            definition.setdefault(
                "sync_groupable",
                confirmed and controllable,
            )
