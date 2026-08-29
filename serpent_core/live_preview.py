from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

from serpent_core.sync import SyncSettings, load_sync_settings


@dataclass(frozen=True)
class LivePreviewRequest:
    effect: str
    parameters: dict[str, object]
    owner_pid: int | None


def runtime_root() -> Path:
    return Path(
        os.environ.get(
            "XDG_RUNTIME_DIR",
            f"/run/user/{os.getuid()}",
        )
    )


def preview_path() -> Path:
    return runtime_root() / "serpent-effect-lab-preview.json"


def _owner_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_preview_request() -> LivePreviewRequest | None:
    path = preview_path()
    if not path.exists():
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Effect Lab live-preview request must be an object.")

    effect = raw.get("effect")
    if not isinstance(effect, str) or not effect:
        raise ValueError("Effect Lab live-preview request has no effect id.")

    parameters = raw.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("Effect Lab live-preview parameters must be an object.")

    owner_pid = raw.get("owner_pid")
    if owner_pid is not None:
        owner_pid = int(owner_pid)

    return LivePreviewRequest(
        effect=effect,
        parameters=dict(parameters),
        owner_pid=owner_pid,
    )


def write_preview_request(
    effect: str,
    parameters: dict[str, object],
    *,
    owner_pid: int | None,
) -> LivePreviewRequest:
    request = LivePreviewRequest(
        effect=str(effect),
        parameters=dict(parameters),
        owner_pid=owner_pid,
    )

    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = preview_path()

    fd, temporary = tempfile.mkstemp(
        prefix=destination.name + ".",
        dir=str(root),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "effect": request.effect,
                    "parameters": request.parameters,
                    "owner_pid": request.owner_pid,
                },
                handle,
                separators=(",", ":"),
            )
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

    return request


def clear_preview_request() -> LivePreviewRequest | None:
    try:
        request = read_preview_request()
    except Exception:
        request = None
    preview_path().unlink(missing_ok=True)
    return request


def resolve_preview_settings(
    base: SyncSettings,
) -> tuple[SyncSettings, LivePreviewRequest | None, str | None]:
    try:
        request = read_preview_request()
    except Exception as exc:
        preview_path().unlink(missing_ok=True)
        return (
            base,
            None,
            f"discarded malformed Effect Lab preview: "
            f"{type(exc).__name__}: {exc}",
        )

    if request is None:
        return base, None, None

    if not _owner_alive(request.owner_pid):
        preview_path().unlink(missing_ok=True)
        return (
            base,
            None,
            "discarded stale Effect Lab preview because its owner process exited",
        )

    raw: dict[str, object] = {
        "effect": base.effect,
        "speed": base.speed,
        "colour1": list(base.colour1),
        "colour2": list(base.colour2),
        "keyboard_brightness": base.keyboard_brightness,
        "mouse_brightness": base.mouse_brightness,
        "member_brightness": dict(base.member_brightness),
        "frame_interval": base.frame_interval,
        "direction": base.direction,
    }

    raw["effect"] = request.effect

    for key in ("colour1", "colour2", "speed", "direction"):
        if key in request.parameters:
            raw[key] = request.parameters[key]

    try:
        effective = load_sync_settings({"sync": raw})
    except Exception as exc:
        preview_path().unlink(missing_ok=True)
        return (
            base,
            None,
            f"discarded invalid Effect Lab preview: "
            f"{type(exc).__name__}: {exc}",
        )

    return effective, request, None


__all__ = [
    "LivePreviewRequest",
    "clear_preview_request",
    "preview_path",
    "read_preview_request",
    "resolve_preview_settings",
    "runtime_root",
    "write_preview_request",
]
