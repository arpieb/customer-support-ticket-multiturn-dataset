"""The record contract's version (FR-002)."""

import re
from typing import NamedTuple

#: The version every record declares. A field removal, a type narrowing, or a tightened
#: constraint is breaking and requires a MAJOR bump (Constitution I).
SCHEMA_VERSION = "1.0.0"

_SEMVER = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


class Semver(NamedTuple):
    major: int
    minor: int
    patch: int


def parse_semver(value: str) -> Semver:
    """Parse a ``MAJOR.MINOR.PATCH`` string, raising ``ValueError`` on anything else."""
    match = _SEMVER.match(value)
    if match is None:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {value!r}")
    return Semver(
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
    )


def is_supported_version(value: str) -> bool:
    """True when ``value`` is the version this code writes and reads."""
    return value == SCHEMA_VERSION
