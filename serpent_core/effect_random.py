from __future__ import annotations

import hashlib
import random

from serpent_core.effects.base import EffectEvent


def event_seed(
    event: EffectEvent,
    *,
    serial: int = 0,
    namespace: str = "",
) -> int:
    """Return a stable 64-bit seed derived from an EffectEvent.

    Unlike Python's built-in hash(), this value is stable across processes.
    The serial allows two otherwise-identical events to intentionally produce
    different procedural geometry while remaining reproducible in tests.
    """

    parts = (
        str(namespace),
        str(event.kind),
        f"{float(event.timestamp):.6f}",
        str(event.source),
        str(event.code),
        str(event.value),
        str(event.row),
        str(event.column),
        str(int(serial)),
    )

    digest = hashlib.blake2b(
        "\x1f".join(parts).encode("utf-8"),
        digest_size=8,
        person=b"serpentfx",
    ).digest()

    return int.from_bytes(digest, "big", signed=False)


def event_rng(
    event: EffectEvent,
    *,
    serial: int = 0,
    namespace: str = "",
) -> random.Random:
    """Create a deterministic local RNG for one event."""

    return random.Random(
        event_seed(
            event,
            serial=serial,
            namespace=namespace,
        )
    )


__all__ = ["event_rng", "event_seed"]
