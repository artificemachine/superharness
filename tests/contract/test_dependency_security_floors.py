"""Security floors for runtime packages with audited fixes."""

from __future__ import annotations

import tomllib
from pathlib import Path


_LOCKFILE = Path(__file__).resolve().parents[2] / "uv.lock"

_SECURITY_FLOORS = {
    "click": (8, 3, 3),
    "cryptography": (50, 0, 0),
    "idna": (3, 15, 0),
    "joserfc": (1, 6, 8),
    "mcp": (1, 28, 1),
    "pydantic-settings": (2, 14, 2),
    "pygments": (2, 20, 0),
    "pyjwt": (2, 13, 0),
}


def _version_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split(".")[:3])


def test_locked_runtime_dependencies_meet_security_floors() -> None:
    lock = tomllib.loads(_LOCKFILE.read_text())
    versions = {
        package["name"]: _version_tuple(package["version"])
        for package in lock["package"]
    }

    below_floor = {
        name: {"locked": versions.get(name), "required": floor}
        for name, floor in _SECURITY_FLOORS.items()
        if versions.get(name, (0, 0, 0)) < floor
    }

    assert not below_floor, f"runtime dependency security floors unmet: {below_floor}"
