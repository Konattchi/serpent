from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from serpent_core.scenes import Scene, SceneValidationError, scene_from_dict, scene_to_dict

DEFAULT_SCENE_DIR = Path.home() / ".config" / "serpent" / "scenes"


class SceneRepositoryError(RuntimeError):
    """Base error for scene persistence operations."""


class SceneNotFoundError(SceneRepositoryError):
    pass


class SceneAlreadyExistsError(SceneRepositoryError):
    pass


class SceneFileError(SceneRepositoryError):
    pass


def _scene_path(scene_id: str, directory: Path) -> Path:
    # Reuse the model validator without requiring a complete caller-created Scene.
    try:
        probe = {
            "schema_version": 1,
            "id": scene_id,
            "name": "probe",
            "mode": "individual",
            "devices": {
                "probe-device": {
                    "effect": {"id": "static", "parameters": {}},
                    "brightness": 1,
                }
            },
        }
        scene_from_dict(probe)
    except SceneValidationError as exc:
        raise SceneRepositoryError(f"Invalid scene id {scene_id!r}: {exc}") from exc
    return directory / f"{scene_id}.json"


class SceneRepository:
    def __init__(self, directory: Path | str = DEFAULT_SCENE_DIR):
        self.directory = Path(directory)

    def ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, scene_id: str) -> Path:
        return _scene_path(scene_id, self.directory)

    def save(self, scene: Scene, *, overwrite: bool = False) -> Path:
        # scene_to_dict performs canonical validation.
        payload = scene_to_dict(scene)
        self.ensure_directory()
        target = self.path_for(scene.id)
        if target.exists() and not overwrite:
            raise SceneAlreadyExistsError(f"Scene already exists: {scene.id}")

        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        fd = -1
        temp_path: Path | None = None
        try:
            fd, raw_temp = tempfile.mkstemp(
                prefix=f".{scene.id}.",
                suffix=".tmp",
                dir=self.directory,
                text=True,
            )
            temp_path = Path(raw_temp)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
            temp_path = None
            try:
                dir_fd = os.open(self.directory, os.O_RDONLY)
            except OSError:
                dir_fd = -1
            if dir_fd >= 0:
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except OSError as exc:
            raise SceneFileError(f"Could not save scene {scene.id!r}: {exc}") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
        return target

    def load(self, scene_id: str) -> Scene:
        path = self.path_for(scene_id)
        if not path.is_file():
            raise SceneNotFoundError(f"Scene not found: {scene_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SceneFileError(f"Could not read scene {scene_id!r}: {exc}") from exc
        try:
            scene = scene_from_dict(raw)
        except SceneValidationError as exc:
            raise SceneFileError(f"Invalid scene file {path.name}: {exc}") from exc
        if scene.id != scene_id:
            raise SceneFileError(
                f"Scene id mismatch in {path.name}: contains {scene.id!r}."
            )
        return scene

    def delete(self, scene_id: str) -> None:
        path = self.path_for(scene_id)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise SceneNotFoundError(f"Scene not found: {scene_id}") from exc
        except OSError as exc:
            raise SceneFileError(f"Could not delete scene {scene_id!r}: {exc}") from exc

    def list_ids(self) -> tuple[str, ...]:
        if not self.directory.is_dir():
            return ()
        ids: list[str] = []
        for path in self.directory.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                scene = self.load(path.stem)
            except SceneRepositoryError:
                continue
            ids.append(scene.id)
        return tuple(sorted(ids))

    def list_scenes(self) -> tuple[Scene, ...]:
        return tuple(self.load(scene_id) for scene_id in self.list_ids())

    def invalid_files(self) -> tuple[tuple[Path, str], ...]:
        if not self.directory.is_dir():
            return ()
        failures: list[tuple[Path, str]] = []
        for path in sorted(self.directory.glob("*.json"), key=lambda p: p.name):
            if path.name.startswith("."):
                continue
            try:
                self.load(path.stem)
            except SceneRepositoryError as exc:
                failures.append((path, str(exc)))
        return tuple(failures)


__all__ = [
    "DEFAULT_SCENE_DIR",
    "SceneAlreadyExistsError",
    "SceneFileError",
    "SceneNotFoundError",
    "SceneRepository",
    "SceneRepositoryError",
]
