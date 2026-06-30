"""Semantic-version-style version parsing and comparison."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import VersionError

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True, order=True)
class Version:
    """A strict `major.minor.patch` version."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0 or self.patch < 0:
            raise VersionError(f"version parts must be non-negative: {self!r}")

    @classmethod
    def parse(cls, text: str) -> "Version":
        value = text.strip()
        match = _VERSION_RE.match(value)
        if not match:
            raise VersionError(f"malformed semantic version {text!r}; expected major.minor.patch")
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: str) -> Version:
    """Parse a strict semantic-version-style version."""

    return Version.parse(text)
