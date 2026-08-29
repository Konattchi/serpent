#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_OWNER = "normal"
OWNER_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class OwnershipError(RuntimeError):
    """Raised when lighting ownership cannot be changed safely."""


def state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")

    if configured:
        return Path(configured).expanduser()

    return Path.home() / ".local" / "state"


def ownership_dir() -> Path:
    return state_root() / "serpent"


def owner_path() -> Path:
    return ownership_dir() / "lighting-owner"


def lock_path() -> Path:
    return ownership_dir() / "lighting-owner.lock"


def validate_owner(owner: str) -> str:
    value = str(owner).strip().lower()

    if not OWNER_PATTERN.fullmatch(value):
        raise OwnershipError(
            "Lighting owner names must use lowercase letters, "
            "numbers, and single hyphens."
        )

    return value


@contextmanager
def ownership_lock() -> Iterator[None]:
    directory = ownership_dir()
    directory.mkdir(parents=True, exist_ok=True)

    with lock_path().open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_unlocked() -> str:
    path = owner_path()

    if not path.exists():
        return DEFAULT_OWNER

    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise OwnershipError(
            f"Could not read lighting ownership state: {exc}"
        ) from exc

    if not value:
        return DEFAULT_OWNER

    return validate_owner(value)


def current_owner() -> str:
    with ownership_lock():
        return _read_unlocked()


def _write_unlocked(owner: str) -> None:
    owner = validate_owner(owner)
    directory = ownership_dir()
    directory.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=".lighting-owner-",
        dir=directory,
        text=True,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(owner + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, owner_path())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def claim_owner(
    owner: str,
    *,
    expected: str = DEFAULT_OWNER,
) -> str:
    owner = validate_owner(owner)
    expected = validate_owner(expected)

    with ownership_lock():
        current = _read_unlocked()

        if current not in {expected, owner}:
            raise OwnershipError(
                f"Lighting is owned by {current!r}; "
                f"cannot claim it for {owner!r}."
            )

        _write_unlocked(owner)
        return owner


def release_owner(
    owner: str,
    *,
    fallback: str = DEFAULT_OWNER,
) -> str:
    owner = validate_owner(owner)
    fallback = validate_owner(fallback)

    with ownership_lock():
        current = _read_unlocked()

        if current != owner:
            raise OwnershipError(
                f"Lighting is owned by {current!r}, not {owner!r}."
            )

        _write_unlocked(fallback)
        return fallback


def set_owner(owner: str) -> str:
    """Administrative override used for recovery and diagnostics."""

    owner = validate_owner(owner)

    with ownership_lock():
        _write_unlocked(owner)

    return owner


def owner_is(owner: str) -> bool:
    return current_owner() == validate_owner(owner)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Serpent lighting ownership.",
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser("get")

    is_parser = commands.add_parser("is")
    is_parser.add_argument("owner")

    allow_parser = commands.add_parser("allow")
    allow_parser.add_argument("owner")

    claim_parser = commands.add_parser("claim")
    claim_parser.add_argument("owner")
    claim_parser.add_argument(
        "--expected",
        default=DEFAULT_OWNER,
    )

    release_parser = commands.add_parser("release")
    release_parser.add_argument("owner")
    release_parser.add_argument(
        "--fallback",
        default=DEFAULT_OWNER,
    )

    set_parser = commands.add_parser("set")
    set_parser.add_argument("owner")

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "get":
            print(current_owner())
            return 0

        if args.command in {"is", "allow"}:
            return 0 if owner_is(args.owner) else 1

        if args.command == "claim":
            print(
                claim_owner(
                    args.owner,
                    expected=args.expected,
                )
            )
            return 0

        if args.command == "release":
            print(
                release_owner(
                    args.owner,
                    fallback=args.fallback,
                )
            )
            return 0

        if args.command == "set":
            print(set_owner(args.owner))
            return 0

    except OwnershipError as exc:
        print(
            f"Serpent ownership error: {exc}",
            file=sys.stderr,
        )
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
