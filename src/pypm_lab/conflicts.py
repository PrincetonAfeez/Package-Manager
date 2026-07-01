"""Structured conflict objects for deterministic resolver explanations."""
 
from __future__ import annotations

from dataclasses import dataclass

from .constraints import VersionConstraint
from .versions import Version


@dataclass(frozen=True)
class ConstraintEvidence:
    package: str
    constraint: VersionConstraint
    source: str

    def format(self) -> str:
        return f"{self.constraint} by {self.source}"


@dataclass(frozen=True)
class CandidateRejection:
    version: Version
    reason: str


@dataclass(frozen=True)
class Conflict:
    package: str
    constraints: tuple[ConstraintEvidence, ...]
    attempted: tuple[CandidateRejection, ...]
    message: str = "No available version satisfies all accumulated constraints."

    def summary(self) -> str:
        return f"Could not resolve {self.package}."

    def explain(self) -> str:
        lines = [self.summary()]
        if self.constraints:
            lines.extend(["", f"{self.package} is required as:"])
            for evidence in sorted(
                self.constraints,
                key=lambda item: (item.source, str(item.constraint)),
            ):
                lines.append(f"  - {evidence.format()}")
        if self.attempted:
            lines.extend(["", "Candidate versions rejected:"])
            for rejection in self.attempted:
                lines.append(f"  - {self.package}@{rejection.version}: {rejection.reason}")
        if self.message:
            lines.extend(["", self.message])
        return "\n".join(lines)
