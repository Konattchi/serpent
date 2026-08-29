from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import selectors
import struct
import time
from typing import Iterable


EV_KEY = 0x01
KEY_VALUE_UP = 0
KEY_VALUE_DOWN = 1
KEY_VALUE_REPEAT = 2

# Linux struct input_event:
#   struct timeval { long tv_sec; long tv_usec; }
#   unsigned short type;
#   unsigned short code;
#   signed int value;
_INPUT_EVENT = struct.Struct("@llHHi")

_INPUT_CODES_HEADER = Path("/usr/include/linux/input-event-codes.h")
_KEY_DEFINE = re.compile(
    r"^\s*#define\s+(KEY_[A-Z0-9_]+)\s+([0-9]+|0x[0-9A-Fa-f]+)\b"
)


@dataclass(frozen=True)
class LinuxKeyEvent:
    """One non-exclusive Linux EV_KEY event."""

    source: str
    timestamp: float
    code: int
    name: str
    value: int

    @property
    def pressed(self) -> bool:
        return self.value == KEY_VALUE_DOWN

    @property
    def released(self) -> bool:
        return self.value == KEY_VALUE_UP

    @property
    def repeated(self) -> bool:
        return self.value == KEY_VALUE_REPEAT


def load_key_names(
    header: Path = _INPUT_CODES_HEADER,
) -> dict[int, str]:
    names: dict[int, str] = {}

    if not header.is_file():
        return names

    for line in header.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        match = _KEY_DEFINE.match(line)
        if match is None:
            continue

        name, raw_value = match.groups()

        try:
            value = int(raw_value, 0)
        except ValueError:
            continue

        names.setdefault(value, name)

    return names


def decode_input_events(
    payload: bytes,
    *,
    source: str,
    key_names: dict[int, str] | None = None,
) -> tuple[LinuxKeyEvent, ...]:
    """Decode complete EV_KEY records from a raw input_event byte stream."""

    if len(payload) % _INPUT_EVENT.size:
        raise ValueError(
            "Input event payload does not contain complete records."
        )

    names = key_names or {}
    events: list[LinuxKeyEvent] = []

    for offset in range(0, len(payload), _INPUT_EVENT.size):
        seconds, microseconds, event_type, code, value = (
            _INPUT_EVENT.unpack_from(payload, offset)
        )

        if event_type != EV_KEY:
            continue

        if value not in (
            KEY_VALUE_UP,
            KEY_VALUE_DOWN,
            KEY_VALUE_REPEAT,
        ):
            continue

        events.append(
            LinuxKeyEvent(
                source=source,
                timestamp=seconds + microseconds / 1_000_000.0,
                code=code,
                name=names.get(code, f"KEY_{code}"),
                value=value,
            )
        )

    return tuple(events)


class KeyboardEventMonitor:
    """Read one or more evdev event nodes without grabbing them."""

    def __init__(
        self,
        paths: Iterable[Path | str],
    ) -> None:
        resolved: list[Path] = []

        for raw_path in paths:
            path = Path(raw_path).expanduser()

            if path in resolved:
                continue

            resolved.append(path)

        if not resolved:
            raise ValueError(
                "KeyboardEventMonitor requires at least one event node."
            )

        self.paths = tuple(resolved)
        self.key_names = load_key_names()
        self._selector = selectors.DefaultSelector()
        self._files: dict[int, tuple[int, Path, bytearray]] = {}

    def open(self) -> None:
        if self._files:
            return

        try:
            for path in self.paths:
                fd = os.open(
                    path,
                    os.O_RDONLY | os.O_NONBLOCK,
                )
                buffer = bytearray()
                self._files[fd] = (fd, path, buffer)
                self._selector.register(
                    fd,
                    selectors.EVENT_READ,
                    data=path,
                )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for fd in tuple(self._files):
            try:
                self._selector.unregister(fd)
            except Exception:
                pass

            try:
                os.close(fd)
            except OSError:
                pass

        self._files.clear()

    def __enter__(self) -> "KeyboardEventMonitor":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def poll(
        self,
        timeout: float = 0.25,
    ) -> tuple[LinuxKeyEvent, ...]:
        if not self._files:
            raise RuntimeError(
                "KeyboardEventMonitor is not open."
            )

        result: list[LinuxKeyEvent] = []

        for key, _mask in self._selector.select(timeout):
            fd = int(key.fd)
            _stored_fd, path, buffer = self._files[fd]

            while True:
                try:
                    chunk = os.read(fd, _INPUT_EVENT.size * 64)
                except BlockingIOError:
                    break

                if not chunk:
                    break

                buffer.extend(chunk)

                complete = (
                    len(buffer)
                    // _INPUT_EVENT.size
                    * _INPUT_EVENT.size
                )

                if complete == 0:
                    continue

                payload = bytes(buffer[:complete])
                del buffer[:complete]

                result.extend(
                    decode_input_events(
                        payload,
                        source=str(path),
                        key_names=self.key_names,
                    )
                )

                if len(chunk) < _INPUT_EVENT.size * 64:
                    break

        return tuple(result)


def default_deathstalker_event_paths() -> tuple[Path, ...]:
    """Return readable DeathStalker keyboard interfaces in stable order."""

    base = Path("/dev/input/by-id")
    candidates = (
        base / "usb-Razer_Razer_DeathStalker_V2-event-kbd",
        base / "usb-Razer_Razer_DeathStalker_V2-if01-event-kbd",
    )

    return tuple(
        path
        for path in candidates
        if path.exists() and os.access(path, os.R_OK)
    )


__all__ = [
    "EV_KEY",
    "KEY_VALUE_DOWN",
    "KEY_VALUE_REPEAT",
    "KEY_VALUE_UP",
    "KeyboardEventMonitor",
    "LinuxKeyEvent",
    "decode_input_events",
    "default_deathstalker_event_paths",
    "load_key_names",
]
