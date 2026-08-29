#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path


SERPENT_DIR = Path.home() / ".local" / "share" / "serpent"
sys.path.insert(0, str(SERPENT_DIR))

from serpent_core.fixtures import FixtureError, load_all_fixtures  # noqa: E402


def main() -> int:
    try:
        fixtures = load_all_fixtures()
    except FixtureError as exc:
        print(f"Fixture error: {exc}", file=sys.stderr)
        return 1

    seen: set[str] = set()

    for fixture in fixtures:
        usb_id = fixture.usb_id.lower()

        if usb_id in seen:
            continue

        seen.add(usb_id)
        print(usb_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
