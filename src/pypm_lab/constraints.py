"""Version constraints and satisfaction checks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import ConstraintError
from .versions import Version

_COMPARATOR_RE = re.compile(
    r"^(>=|<=|>|<|==|=)?\s*((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"
)


@dataclass(frozen=True)
class Comparator:
    op: str
    version: Version

    def allows(self, version: Version) -> bool:
        if self.op == "==":
            return version == self.version
        if self.op == ">=":
            return version >= self.version
        if self.op == ">":
            return version > self.version
        if self.op == "<=":
            return version <= self.version
        if self.op == "<":
            return version < self.version
        raise ConstraintError(f"unsupported comparator {self.op!r}")

    def __str__(self) -> str:
        if self.op == "==":
            return str(self.version)
        return f"{self.op}{self.version}"


@dataclass(frozen=True)
class VersionConstraint:
    """An AND-combined list of version comparators."""

    raw: str
    comparators: tuple[Comparator, ...]

    @classmethod
    def any(cls) -> VersionConstraint:
        return cls("*", (Comparator(">=", Version(0, 0, 0)),))

    @classmethod
    def parse(cls, text: str) -> VersionConstraint:
        raw = text.strip()
        if not raw:
            raise ConstraintError("missing version constraint")
        if raw == "*":
            return cls.any()
        if raw.startswith("^"):
            base = _parse_single_version(raw[1:], raw)
            upper = _caret_upper_bound(base)
            return cls(raw, (Comparator(">=", base), Comparator("<", upper)))
        if raw.startswith("~"):
            base = _parse_single_version(raw[1:], raw)
            upper = Version(base.major, base.minor + 1, 0)
            return cls(raw, (Comparator(">=", base), Comparator("<", upper)))

        pieces = raw.split(",")
        if any(not piece.strip() for piece in pieces):
            raise ConstraintError(f"malformed constraint {text!r}: empty comparator")
        comparators = tuple(_parse_comparator(piece.strip()) for piece in pieces)
        return cls(raw, comparators)

    def allows(self, version: Version) -> bool:
        return all(comparator.allows(version) for comparator in self.comparators)

    def allows_all(self, versions: Iterable[Version]) -> list[Version]:
        return [version for version in versions if self.allows(version)]

    def __str__(self) -> str:
        return self.raw


def parse_constraint(text: str) -> VersionConstraint:
    return VersionConstraint.parse(text)


def _parse_single_version(text: str, raw: str) -> Version:
    if not text:
        raise ConstraintError(f"missing version in constraint {raw!r}")
    try:
        return Version.parse(text)
    except Exception as exc:  # noqa: BLE001 - normalize parser errors for callers.
        raise ConstraintError(f"malformed version in constraint {raw!r}: {exc}") from exc


def _parse_comparator(piece: str) -> Comparator:
    match = _COMPARATOR_RE.match(piece)
    if not match:
        raise ConstraintError(f"malformed comparator {piece!r}")
    op = match.group(1) or "=="
    if op == "=":
        op = "=="
    return Comparator(op, Version.parse(match.group(2)))


def _caret_upper_bound(version: Version) -> Version:
    if version.major > 0:
        return Version(version.major + 1, 0, 0)
    if version.minor > 0:
        return Version(0, version.minor + 1, 0)
    return Version(0, 0, version.patch + 1)
