from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from serpent_core.effects.base import EffectEvent
from serpent_core.input_events import KeyboardEventMonitor, LinuxKeyEvent
from serpent_core.keyboard_layout import effect_event_from_linux_key


@dataclass(frozen=True)
class ReactiveSourceHealth:
    source_id: str
    active: bool
    last_error: str | None = None


class ReactiveEventSource:
    source_id = "unknown"
    input_capability = "unknown"

    def __init__(self) -> None:
        self._monitor = None
        self._last_error: str | None = None

    @property
    def active(self) -> bool:
        return self._monitor is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def health(self) -> ReactiveSourceHealth:
        return ReactiveSourceHealth(
            self.source_id,
            self.active,
            self.last_error,
        )

    def open(self) -> bool:
        raise NotImplementedError

    def poll(
        self,
        *,
        elapsed: float,
        rows: int,
        columns: int,
    ) -> tuple[EffectEvent, ...]:
        raise NotImplementedError

    def close(self) -> None:
        monitor = self._monitor
        self._monitor = None
        if monitor is None:
            return
        try:
            monitor.close()
        except Exception:
            pass


class KeyboardEventSource(ReactiveEventSource):
    input_capability = "keyboard"

    def __init__(
        self,
        *,
        source_id: str,
        event_paths: tuple[Path, ...],
        matrix_rows: int,
        matrix_columns: int,
        row_offset: int = 0,
        column_offset: int = 0,
        monitor_factory=KeyboardEventMonitor,
        translator=effect_event_from_linux_key,
        duplicate_window: float = 0.005,
    ) -> None:
        super().__init__()
        self.source_id = source_id
        self._event_paths = tuple(event_paths)
        self._matrix_rows = int(matrix_rows)
        self._matrix_columns = int(matrix_columns)
        self._row_offset = int(row_offset)
        self._column_offset = int(column_offset)
        self._monitor_factory = monitor_factory
        self._translator = translator
        self._duplicate_window = max(0.0, float(duplicate_window))
        self._last_event: dict[tuple[int, int], float] = {}

    def _duplicate(self, event: LinuxKeyEvent) -> bool:
        key = (int(event.code), int(event.value))
        previous = self._last_event.get(key)
        self._last_event[key] = float(event.timestamp)
        if previous is None:
            return False
        delta = float(event.timestamp) - previous
        return 0.0 <= delta <= self._duplicate_window

    def open(self) -> bool:
        self.close()
        self._last_event.clear()
        self._last_error = None

        paths = tuple(path for path in self._event_paths if path.exists())
        if not paths:
            self._last_error = (
                f"{self.source_id}: no readable/configured keyboard "
                "event interfaces were found."
            )
            return False

        monitor = self._monitor_factory(paths)
        try:
            monitor.open()
        except Exception as exc:
            self._last_error = (
                f"{self.source_id}: could not open keyboard input: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        self._monitor = monitor
        return True

    def poll(
        self,
        *,
        elapsed: float,
        rows: int,
        columns: int,
    ) -> tuple[EffectEvent, ...]:
        del rows, columns

        if self._monitor is None:
            return ()

        try:
            pending = self._monitor.poll(0.0)
        except Exception as exc:
            self._last_error = (
                f"{self.source_id}: keyboard input poll failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self.close()
            return ()

        result = []
        for linux_event in pending:
            if self._duplicate(linux_event):
                continue

            try:
                event = self._translator(
                    linux_event,
                    rows=self._matrix_rows,
                    columns=self._matrix_columns,
                    row_offset=self._row_offset,
                    column_offset=self._column_offset,
                )
            except Exception as exc:
                self._last_error = (
                    f"{self.source_id}: keyboard event translation failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            if event is None:
                continue

            result.append(
                replace(
                    event,
                    timestamp=float(elapsed),
                    source=(
                        f"keyboard:{self.source_id}:"
                        f"{linux_event.source}"
                    ),
                )
            )

        return tuple(result)

    def close(self) -> None:
        super().close()
        self._last_event.clear()


class MouseEventSource(ReactiveEventSource):
    input_capability = "mouse"

    def __init__(
        self,
        *,
        source_id: str,
        event_paths: tuple[Path, ...],
        button_minimum: int,
        button_maximum: int,
        macro_interface: str | None = None,
        macro_policy: str | None = None,
        macro_event_code: str = "MACRO_BUTTON",
        monitor_factory=KeyboardEventMonitor,
        duplicate_window: float = 0.005,
    ) -> None:
        super().__init__()
        self.source_id = source_id
        self._event_paths = tuple(event_paths)
        self._button_minimum = int(button_minimum)
        self._button_maximum = int(button_maximum)
        self._macro_interface = macro_interface
        self._macro_policy = macro_policy
        self._macro_event_code = macro_event_code
        self._monitor_factory = monitor_factory
        self._duplicate_window = max(0.0, float(duplicate_window))
        self._last_event: dict[tuple[int, int], float] = {}
        self._macro_down: set[int] = set()
        self._macro_active = False

    def _duplicate(self, event: LinuxKeyEvent) -> bool:
        key = (int(event.code), int(event.value))
        previous = self._last_event.get(key)
        self._last_event[key] = float(event.timestamp)
        if previous is None:
            return False
        delta = float(event.timestamp) - previous
        return 0.0 <= delta <= self._duplicate_window

    def open(self) -> bool:
        self.close()
        self._last_event.clear()
        self._macro_down.clear()
        self._macro_active = False
        self._last_error = None

        paths = tuple(path for path in self._event_paths if path.exists())
        if not paths:
            self._last_error = (
                f"{self.source_id}: no readable/configured mouse "
                "event interfaces were found."
            )
            return False

        monitor = self._monitor_factory(paths)
        try:
            monitor.open()
        except Exception as exc:
            self._last_error = (
                f"{self.source_id}: could not open mouse input: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        self._monitor = monitor
        return True

    def _is_macro_interface(self, source: str) -> bool:
        if not self._macro_interface:
            return False
        return source.endswith(self._macro_interface)

    def _mouse_press_event(
        self,
        *,
        elapsed: float,
        linux_event: LinuxKeyEvent,
        code: str,
    ) -> EffectEvent:
        return EffectEvent(
            kind="mouse-press",
            timestamp=float(elapsed),
            source=f"mouse:{self.source_id}:{linux_event.source}",
            code=code,
            value=1,
            row=None,
            column=None,
        )

    def poll(
        self,
        *,
        elapsed: float,
        rows: int,
        columns: int,
    ) -> tuple[EffectEvent, ...]:
        del rows, columns

        if self._monitor is None:
            return ()

        try:
            pending = self._monitor.poll(0.0)
        except Exception as exc:
            self._last_error = (
                f"{self.source_id}: mouse input poll failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self.close()
            return ()

        result = []
        for linux_event in pending:
            if self._duplicate(linux_event):
                continue

            event = None

            if (
                self._macro_policy == "collapse-chord"
                and self._is_macro_interface(linux_event.source)
            ):
                if linux_event.value == 1:
                    self._macro_down.add(linux_event.code)
                    if not self._macro_active:
                        self._macro_active = True
                        event = self._mouse_press_event(
                            elapsed=elapsed,
                            linux_event=linux_event,
                            code=self._macro_event_code,
                        )
                elif linux_event.value == 0:
                    self._macro_down.discard(linux_event.code)
                    if not self._macro_down:
                        self._macro_active = False

            elif (
                linux_event.value == 1
                and self._button_minimum
                <= linux_event.code
                <= self._button_maximum
            ):
                event = self._mouse_press_event(
                    elapsed=elapsed,
                    linux_event=linux_event,
                    code=linux_event.name,
                )

            if event is not None:
                result.append(event)

        return tuple(result)

    def close(self) -> None:
        super().close()
        self._last_event.clear()
        self._macro_down.clear()
        self._macro_active = False


__all__ = [
    "KeyboardEventSource",
    "MouseEventSource",
    "ReactiveEventSource",
    "ReactiveSourceHealth",
]
