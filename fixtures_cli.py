#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SERPENT_DIR = Path.home() / ".local" / "share" / "serpent"
sys.path.insert(0, str(SERPENT_DIR))

from serpent_core.discovery import detect_all_fixtures  # noqa: E402
from serpent_core.fixtures import (  # noqa: E402
    FixtureError,
    find_fixture_by_id,
    load_all_fixtures,
)


def list_fixtures() -> None:
    fixtures = load_all_fixtures()

    if not fixtures:
        print("No Serpent fixtures are installed.")
        return

    print("Installed Serpent fixtures")
    print("==========================")

    for fixture in fixtures:
        print()
        print(f"ID: {fixture.id}")
        print(f"Device: {fixture.display_name}")
        print(f"Class: {fixture.device_class}")
        print(f"USB ID: {fixture.usb_id}")
        print(
            "Effects: "
            + ", ".join(sorted(fixture.data["effects"]))
        )


def show_fixture(fixture_id: str) -> None:
    fixture = find_fixture_by_id(fixture_id)

    print(fixture.display_name)
    print("=" * len(fixture.display_name))
    print(f"Fixture ID: {fixture.id}")
    print(f"Class: {fixture.device_class}")
    print(f"USB ID: {fixture.usb_id}")
    print(f"Backend: {fixture.data['backend']['type']}")
    print()

    print("Effects")

    for effect_name, effect in fixture.data["effects"].items():
        details = []

        if "colours" in effect:
            details.append(f"colours={effect['colours']}")

        if "speeds" in effect:
            details.append(
                "speeds="
                + ",".join(
                    str(value)
                    for value in effect["speeds"]
                )
            )

        if "directions" in effect:
            details.append(
                "directions="
                + ",".join(
                    str(value)
                    for value in effect["directions"]
                )
            )

        suffix = f" ({'; '.join(details)})" if details else ""
        print(f"  {effect_name}{suffix}")


def detect_fixtures() -> None:
    detected = detect_all_fixtures()

    if not detected:
        print("No supported Serpent devices were detected.")
        return

    print("Connected supported devices")
    print("===========================")

    for item in detected:
        fixture = item.fixture

        print()
        print(f"✓ {fixture.id}")
        print(f"  Device: {fixture.display_name}")
        print(f"  Class: {fixture.device_class}")
        print(f"  USB ID: {fixture.usb_id}")
        print(f"  Sysfs: {item.sysfs_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serpent fixtures",
        description="Inspect installed Serpent device fixtures.",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser("list")
    commands.add_parser("detect")

    show = commands.add_parser("show")
    show.add_argument("fixture_id")

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "list":
            list_fixtures()
        elif args.command == "show":
            show_fixture(args.fixture_id)
        elif args.command == "detect":
            detect_fixtures()

    except (FixtureError, ValueError) as exc:
        print(f"Fixture error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
