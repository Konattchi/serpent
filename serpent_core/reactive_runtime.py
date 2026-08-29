from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from serpent_core.effects import (
    Effect,
    get_effect,
    get_effect_plugin_spec,
)
from serpent_core.input_source_factory import build_reactive_sources
from serpent_core.reactive_input import (
    ReactiveEventSource,
    ReactiveSourceHealth,
)


@dataclass(frozen=True)
class ReactiveRuntimeHealth:
    active: bool
    effect_id: str | None
    sources: tuple[ReactiveSourceHealth, ...]
    handler_error: str | None = None


class ReactiveRuntime:
    """Metadata-driven reactive lifecycle and event dispatcher.

    M8.4 makes reconciliation incremental and recoverable:
    * unchanged active sources are never duplicated;
    * missing requested sources are retried;
    * no-longer-requested sources are closed;
    * force=True gives an in-process reload a clean source boundary.
    """

    def __init__(
        self,
        *,
        sources: Iterable[ReactiveEventSource] | None = None,
        effect_provider=get_effect,
        plugin_provider=get_effect_plugin_spec,
    ) -> None:
        self._sources = tuple(
            sources if sources is not None
            else build_reactive_sources()
        )
        self._effect_provider = effect_provider
        self._plugin_provider = plugin_provider
        self._effect_id: str | None = None
        self._handler_error: str | None = None
        self._requested_inputs: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return any(source.active for source in self._sources)

    @property
    def effect_id(self) -> str | None:
        return self._effect_id

    @property
    def requested_inputs(self) -> tuple[str, ...]:
        return self._requested_inputs

    @property
    def health(self) -> ReactiveRuntimeHealth:
        return ReactiveRuntimeHealth(
            active=self.active,
            effect_id=self.effect_id,
            sources=tuple(source.health for source in self._sources),
            handler_error=self._handler_error,
        )

    @property
    def last_error(self) -> str | None:
        messages = [
            source.last_error
            for source in self._sources
            if source.last_error
        ]
        if self._handler_error:
            messages.append(self._handler_error)
        return "; ".join(messages) if messages else None

    def _requested_for(self, effect_id: str) -> tuple[str, ...]:
        plugin = self._plugin_provider(effect_id)

        if plugin.input_capabilities is not None:
            return plugin.input_capabilities

        # Plugin API 1 compatibility mode for older external plugins.
        effect = self._effect_provider(effect_id)
        if type(effect).handle_event is not Effect.handle_event:
            return tuple(
                dict.fromkeys(
                    source.input_capability
                    for source in self._sources
                    if source.input_capability != "unknown"
                )
            )

        return ()

    def reconcile(
        self,
        effect_id: str,
        *,
        force: bool = False,
    ) -> bool:
        requested = self._requested_for(effect_id)
        changed = (
            self._effect_id != effect_id
            or requested != self._requested_inputs
        )

        if force:
            # A forced in-process reload is a true transient-state boundary:
            # discard monitor-local duplicate suppression, macro chord state,
            # pending handles, and stale source errors before reopening.
            self.close()

        if force or changed:
            self._handler_error = None

        self._effect_id = effect_id
        self._requested_inputs = requested

        for source in self._sources:
            wanted = source.input_capability in requested

            if not wanted:
                if source.active:
                    source.close()
                continue

            # Incremental recovery: keep healthy monitors exactly as they are,
            # but retry any requested source that is currently unavailable.
            if source.active:
                continue

            try:
                source.open()
            except Exception:
                try:
                    source.close()
                except Exception:
                    pass

        return any(
            source.active
            for source in self._sources
            if source.input_capability in requested
        )

    def drain(
        self,
        effect_id: str,
        *,
        elapsed: float,
        rows: int,
        columns: int,
    ) -> int:
        requested = self._requested_for(effect_id)

        if (
            self._effect_id != effect_id
            or requested != self._requested_inputs
        ):
            self.reconcile(effect_id)

        if not self.active:
            return 0

        effect = self._effect_provider(effect_id)
        delivered = 0

        for source in self._sources:
            if source.input_capability not in self._requested_inputs:
                continue

            try:
                events = source.poll(
                    elapsed=elapsed,
                    rows=rows,
                    columns=columns,
                )
            except Exception:
                try:
                    source.close()
                except Exception:
                    pass
                continue

            for event in events:
                try:
                    effect.handle_event(event)
                except Exception as exc:
                    self._handler_error = (
                        "Reactive effect handler failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue

                delivered += 1

        return delivered

    def close(self) -> None:
        for source in self._sources:
            try:
                source.close()
            except Exception:
                pass


__all__ = ["ReactiveRuntime", "ReactiveRuntimeHealth"]
