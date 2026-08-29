from __future__ import annotations

import hashlib
from pathlib import Path


def _read_attr(path: Path, name: str) -> str | None:
    target = path / name
    if not target.exists():
        return None
    try:
        value = target.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()
    except OSError:
        return None
    return value or None


def physical_usb_parent(sysfs_path: Path) -> Path | None:
    current = Path(sysfs_path).resolve(strict=False)
    while current != current.parent:
        if (
            (current / "idVendor").exists()
            and (current / "idProduct").exists()
        ):
            return current
        current = current.parent
    return None


def physical_identity_basis(sysfs_path: Path) -> str:
    endpoint = Path(sysfs_path)
    parent = physical_usb_parent(endpoint)

    if parent is None:
        canonical = str(endpoint.resolve(strict=False))
        return f"v1:sysfs-fallback:{canonical}"

    vid = (_read_attr(parent, "idVendor") or "").lower()
    pid = (_read_attr(parent, "idProduct") or "").lower()
    serial = _read_attr(parent, "serial")

    if serial:
        return f"v1:serial:{vid}:{pid}:{serial}"

    return f"v1:usb-topology:{vid}:{pid}:{parent.name}"


def stable_instance_id(
    fixture_id: str,
    sysfs_path: Path | None,
) -> str:
    if sysfs_path is None:
        return fixture_id

    basis = physical_identity_basis(Path(sysfs_path))
    digest = hashlib.sha256(
        basis.encode("utf-8")
    ).hexdigest()[:16]

    return f"{fixture_id}@{digest}"
