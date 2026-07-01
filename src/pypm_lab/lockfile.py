"""Stable lockfile serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import IntegrityError, LockfileError, VersionError
from .fsio import atomic_write_text
from .integrity import parse_integrity
from .jsonio import loads_no_duplicate_keys
from .models import ResolvedGraph, ResolvedPackage
from .requirements import validate_package_name
from .versions import Version

LOCKFILE_NAME = "pypm-lock.json"
LOCKFILE_VERSION = 1


@dataclass(frozen=True)
class LockPackage:
    version: Version
    integrity: str
    dependencies: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": str(self.version),
            "integrity": self.integrity,
            "dependencies": dict(sorted(self.dependencies.items())),
        }


@dataclass(frozen=True)
class Lockfile:
    packages: dict[str, LockPackage]
    roots: tuple[str, ...]

    @classmethod
    def from_graph(cls, graph: ResolvedGraph) -> Lockfile:
        packages = {
            name: LockPackage(
                version=package.version,
                integrity=package.integrity,
                dependencies=dict(sorted(package.dependencies.items())),
            )
            for name, package in sorted(graph.packages.items())
        }
        return cls(packages=packages, roots=tuple(sorted(graph.roots)))

    def to_graph(self) -> ResolvedGraph:
        packages = {
            name: ResolvedPackage(
                name=name,
                version=package.version,
                dependencies=dict(sorted(package.dependencies.items())),
                integrity=package.integrity,
            )
            for name, package in sorted(self.packages.items())
        }
        return ResolvedGraph(packages=packages, roots=tuple(sorted(self.roots)))

    def to_dict(self) -> dict[str, object]:
        return {
            "lockfileVersion": LOCKFILE_VERSION,
            "roots": sorted(self.roots),
            "packages": {
                name: package.to_dict()
                for name, package in sorted(self.packages.items())
            },
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def lockfile_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / LOCKFILE_NAME


def write_lockfile(project_dir: Path | str, lockfile: Lockfile) -> Path:
    path = lockfile_path(project_dir)
    atomic_write_text(path, lockfile.dumps())
    return path


def load_lockfile(project_dir: Path | str) -> Lockfile:
    path = lockfile_path(project_dir)
    if not path.exists():
        raise LockfileError(f"missing lockfile {path}")
    try:
        data = loads_no_duplicate_keys(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockfileError(f"malformed lockfile {path}: {exc.msg}") from exc
    except ValueError as exc:
        raise LockfileError(f"malformed lockfile {path}: {exc}") from exc
    return parse_lockfile(data)


def parse_lockfile(data: dict[str, Any]) -> Lockfile:
    if not isinstance(data, dict):
        raise LockfileError("lockfile must be a JSON object")
    if data.get("lockfileVersion") != LOCKFILE_VERSION:
        raise LockfileError(f"unsupported lockfileVersion {data.get('lockfileVersion')!r}")
    roots_data = data.get("roots", [])
    if not isinstance(roots_data, list):
        raise LockfileError("lockfile roots must be a list")
    roots = tuple(sorted(validate_package_name(str(root)) for root in roots_data))
    packages_data = data.get("packages")
    if not isinstance(packages_data, dict):
        raise LockfileError("lockfile packages must be an object")
    packages: dict[str, LockPackage] = {}
    for raw_name, package_data in packages_data.items():
        name = validate_package_name(raw_name)
        if not isinstance(package_data, dict):
            raise LockfileError(f"{name}: lockfile package must be an object")
        if "version" not in package_data:
            raise LockfileError(f"{name}: missing lockfile field version")
        if "integrity" not in package_data:
            raise LockfileError(f"{name}: missing lockfile field integrity")
        try:
            version = Version.parse(str(package_data["version"]))
        except VersionError as exc:
            raise LockfileError(f"{name}: invalid version {package_data['version']!r}: {exc}") from exc
        integrity = str(package_data["integrity"])
        try:
            parse_integrity(integrity)
        except IntegrityError as exc:
            raise LockfileError(f"{name}: {exc}") from exc
        dependencies_data = package_data.get("dependencies", {})
        if not isinstance(dependencies_data, dict):
            raise LockfileError(f"{name}: dependencies must be an object")
        dependencies = {
            validate_package_name(dep_name): str(raw_constraint)
            for dep_name, raw_constraint in sorted(dependencies_data.items())
        }
        packages[name] = LockPackage(version=version, integrity=integrity, dependencies=dependencies)

    # Referential integrity: every root and every dependency edge must point to a
    # package that exists in the lockfile, so the lockfile describes a complete,
    # self-contained resolved graph. This keeps `tree`, `why`, `graph`, and
    # `install` consistent rather than letting a dangling edge crash `why`.
    known = set(packages)
    for root in roots:
        if root not in known:
            raise LockfileError(f"lockfile root {root} has no package entry")
    for name, locked in sorted(packages.items()):
        for dependency in sorted(locked.dependencies):
            if dependency not in known:
                raise LockfileError(
                    f"{name}: dependency {dependency} has no package entry in the lockfile"
                )

    return Lockfile(packages=dict(sorted(packages.items())), roots=roots)
