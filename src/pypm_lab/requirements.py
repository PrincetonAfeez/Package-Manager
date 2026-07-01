"""Package name validation and requirement parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .constraints import VersionConstraint
from .errors import RequirementError

_PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class Requirement:
    name: str
    raw_constraint: str
    constraint: VersionConstraint
    raw: str
    source: str = "project manifest"

    def __str__(self) -> str:
        return f"{self.name}@{self.raw_constraint}"


def validate_package_name(text: str) -> str:
    raw = text.strip()
    if not raw:
        raise RequirementError("missing package name")
    if "/" in raw or "\\" in raw:
        raise RequirementError(f"invalid package name {text!r}: path separators are not allowed")
    normalized = raw.lower()
    # The regex forbids leading separators and the dot checks below forbid
    # leading/trailing dots, so a normalized name can never be a traversal
    # sequence; an interior ".." (as in "a..b") is just an ordinary name.
    if not _PACKAGE_RE.match(normalized) or normalized.startswith(".") or normalized.endswith("."):
        raise RequirementError(
            f"invalid package name {text!r}; use letters, numbers, dots, dashes, and underscores"
        )
    return normalized


def parse_requirement(text: str, *, source: str = "project manifest") -> Requirement:
    raw = text.strip()
    if "@" not in raw:
        raise RequirementError(f"malformed requirement {text!r}: expected name@constraint")
    name, constraint = raw.split("@", 1)
    return parse_requirement_parts(name, constraint, source=source, raw=raw)


def parse_requirement_parts(
    name: str,
    constraint: str,
    *,
    source: str = "project manifest",
    raw: str | None = None,
) -> Requirement:
    package_name = validate_package_name(name)
    constraint_text = constraint.strip()
    if not constraint_text:
        raise RequirementError(f"missing constraint for package {package_name}")
    try:
        parsed_constraint = VersionConstraint.parse(constraint_text)
    except Exception as exc:  # noqa: BLE001 - convert parser errors to requirement context.
        raise RequirementError(f"invalid constraint for {package_name}: {exc}") from exc
    return Requirement(
        name=package_name,
        raw_constraint=constraint_text,
        constraint=parsed_constraint,
        raw=raw or f"{package_name}@{constraint_text}",
        source=source,
    )
