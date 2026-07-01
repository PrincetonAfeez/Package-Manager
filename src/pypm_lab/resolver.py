"""Pure deterministic dependency resolver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .conflicts import CandidateRejection, Conflict, ConstraintEvidence
from .constraints import VersionConstraint
from .errors import ResolutionError
from .graph import detect_cycle
from .models import PackageVersion, ResolvedGraph, ResolvedPackage
from .requirements import Requirement, validate_package_name
from .versions import Version


class RegistryReader(Protocol):
    """The resolver's narrow view of a package registry."""

    def available_versions(self, name: str) -> Sequence[Version]:
        ...

    def get_package_version(self, name: str, version: Version) -> PackageVersion:
        ...


@dataclass(frozen=True)
class Resolution:
    graph: ResolvedGraph
    trace: tuple[str, ...]


class ResolutionFailed(ResolutionError):
    def __init__(self, conflict: Conflict):
        self.conflict = conflict
        super().__init__(conflict.explain())


class _BacktrackFailure(Exception):
    def __init__(self, conflict: Conflict):
        self.conflict = conflict
        super().__init__(conflict.summary())


class Resolver:
    """Deterministic backtracking resolver over package/version constraints."""

    def __init__(self, registry: RegistryReader, *, trace: bool = False):
        self.registry = registry
        self.trace_enabled = trace
        self._trace: list[str] = []

    def resolve(self, requirements: Sequence[Requirement]) -> Resolution:
        constraints: dict[str, list[ConstraintEvidence]] = {}
        roots = tuple(sorted({requirement.name for requirement in requirements}))
        for requirement in sorted(requirements, key=lambda item: (item.name, item.raw_constraint)):
            constraints.setdefault(requirement.name, []).append(
                ConstraintEvidence(requirement.name, requirement.constraint, requirement.source)
            )

        if self.trace_enabled:
            direct = ", ".join(str(requirement) for requirement in sorted(requirements, key=str))
            self._trace.append(f"initial direct dependencies: {direct or '(none)'}")

        try:
            packages = self._search(assignments={}, constraints=constraints, edges={})
        except _BacktrackFailure as failure:
            raise ResolutionFailed(failure.conflict) from failure

        graph = ResolvedGraph(packages=dict(sorted(packages.items())), roots=roots)
        if self.trace_enabled:
            final = ", ".join(graph.packages[name].identifier for name in sorted(graph.packages))
            self._trace.append(f"final resolved graph: {final or '(empty)'}")
        return Resolution(graph=graph, trace=tuple(self._trace))

    def _search(
        self,
        *,
        assignments: Mapping[str, ResolvedPackage],
        constraints: Mapping[str, list[ConstraintEvidence]],
        edges: Mapping[str, tuple[str, ...]],
    ) -> dict[str, ResolvedPackage]:
        self._check_assigned_constraints(assignments, constraints)
        unresolved = sorted(name for name in constraints if name not in assignments)
        if not unresolved:
            return dict(assignments)

        package, candidates, initial_rejections = self._select_package(unresolved, constraints)
        evidence = tuple(constraints[package])
        self._record(
            f"selecting {package}: constraints "
            + ", ".join(str(item.constraint) for item in evidence)
        )

        attempted = list(initial_rejections)
        last_child_conflict: Conflict | None = None
        detected_cycle: list[str] | None = None

        for version in candidates:
            self._record(f"trying {package}@{version}")
            package_version = self.registry.get_package_version(package, version)
            resolved_package = ResolvedPackage(
                name=package_version.name,
                version=package_version.version,
                dependencies=dict(sorted(package_version.dependencies.items())),
                integrity=package_version.integrity,
                archive=str(package_version.archive),
            )

            next_assignments = dict(assignments)
            next_assignments[package] = resolved_package
            next_constraints = {name: list(items) for name, items in constraints.items()}
            dependency_names: list[str] = []
            rejected_reason: str | None = None

            for dependency_name, raw_constraint in sorted(package_version.dependencies.items()):
                normalized_dependency = validate_package_name(dependency_name)
                dependency_names.append(normalized_dependency)
                dependency_constraint = VersionConstraint.parse(raw_constraint)
                source = resolved_package.identifier
                self._record(
                    f"adding constraint {normalized_dependency} {dependency_constraint} "
                    f"from {source}"
                )
                next_constraints.setdefault(normalized_dependency, []).append(
                    ConstraintEvidence(normalized_dependency, dependency_constraint, source)
                )
                assigned_dependency = next_assignments.get(normalized_dependency)
                if assigned_dependency and not dependency_constraint.allows(assigned_dependency.version):
                    rejected_reason = (
                        f"{assigned_dependency.identifier} does not satisfy "
                        f"{dependency_constraint} from {source}"
                    )
                    break

            if rejected_reason:
                self._record(f"rejecting {package}@{version}: {rejected_reason}")
                attempted.append(CandidateRejection(version, rejected_reason))
                continue

            next_edges = dict(edges)
            next_edges[package] = tuple(sorted(dependency_names))
            cycle = detect_cycle(next_edges)
            if cycle:
                reason = f"cycle detected: {' -> '.join(cycle)}"
                detected_cycle = cycle
                self._record(f"rejecting {package}@{version}: {reason}")
                attempted.append(CandidateRejection(version, reason))
                continue

            try:
                return self._search(
                    assignments=next_assignments,
                    constraints=next_constraints,
                    edges=next_edges,
                )
            except _BacktrackFailure as failure:
                last_child_conflict = failure.conflict
                reason = failure.conflict.summary()
                self._record(f"backtracking from {package}@{version}: {reason}")
                attempted.append(CandidateRejection(version, reason))

        if last_child_conflict is not None:
            raise _BacktrackFailure(last_child_conflict)
        if detected_cycle is not None:
            message = f"Dependency cycle detected: {' -> '.join(detected_cycle)}."
        else:
            message = "No available version satisfies all accumulated constraints."
        raise _BacktrackFailure(
            Conflict(
                package=package,
                constraints=tuple(evidence),
                attempted=tuple(attempted),
                message=message,
            )
        )

    def _check_assigned_constraints(
        self,
        assignments: Mapping[str, ResolvedPackage],
        constraints: Mapping[str, list[ConstraintEvidence]],
    ) -> None:
        for package, resolved in sorted(assignments.items()):
            for evidence in constraints.get(package, ()):
                if not evidence.constraint.allows(resolved.version):
                    raise _BacktrackFailure(
                        Conflict(
                            package=package,
                            constraints=tuple(constraints.get(package, ())),
                            attempted=(
                                CandidateRejection(
                                    resolved.version,
                                    f"selected version violates {evidence.constraint} from {evidence.source}",
                                ),
                            ),
                        )
                    )

    def _select_package(
        self,
        unresolved: Sequence[str],
        constraints: Mapping[str, list[ConstraintEvidence]],
    ) -> tuple[str, list[Version], list[CandidateRejection]]:
        choices: list[tuple[int, str, list[Version], list[CandidateRejection]]] = []
        for package in unresolved:
            candidates, rejected = self._candidates(package, tuple(constraints[package]))
            if not candidates:
                raise _BacktrackFailure(
                    Conflict(
                        package=package,
                        constraints=tuple(constraints[package]),
                        attempted=tuple(rejected),
                        message=(
                            f"{package} is not present in the registry."
                            if not self.registry.available_versions(package)
                            else "No available version satisfies all accumulated constraints."
                        ),
                    )
                )
            choices.append((len(candidates), package, candidates, rejected))
        _, package, candidates, rejected = min(choices, key=lambda item: (item[0], item[1]))
        return package, candidates, rejected

    def _candidates(
        self,
        package: str,
        constraints: tuple[ConstraintEvidence, ...],
    ) -> tuple[list[Version], list[CandidateRejection]]:
        available = sorted(self.registry.available_versions(package), reverse=True)
        candidates: list[Version] = []
        rejected: list[CandidateRejection] = []
        for version in available:
            failed = next(
                (evidence for evidence in constraints if not evidence.constraint.allows(version)),
                None,
            )
            if failed:
                rejected.append(
                    CandidateRejection(
                        version,
                        f"does not satisfy {failed.constraint} from {failed.source}",
                    )
                )
            else:
                candidates.append(version)
        self._record(
            f"candidates for {package}: "
            + (", ".join(str(candidate) for candidate in candidates) or "(none)")
        )
        return candidates, rejected

    def _record(self, line: str) -> None:
        if self.trace_enabled:
            self._trace.append(line)


def resolve(
    requirements: Sequence[Requirement],
    registry: RegistryReader,
    *,
    trace: bool = False,
) -> Resolution:
    return Resolver(registry, trace=trace).resolve(requirements)
