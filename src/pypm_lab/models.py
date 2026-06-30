"""Shared data models for the package manager layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .versions import Version


@dataclass(frozen=True)
class PackageVersion:
    name: str
    version: Version
    dependencies: Mapping[str, str]
    integrity: str
    archive: Path | str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def identifier(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class ResolvedPackage:
    name: str
    version: Version
    dependencies: Mapping[str, str]
    integrity: str
    archive: str = ""

    @property
    def identifier(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class ResolvedGraph:
    packages: Mapping[str, ResolvedPackage]
    roots: tuple[str, ...]

    def edges(self) -> dict[str, tuple[str, ...]]:
        return {
            name: tuple(sorted(package.dependencies))
            for name, package in sorted(self.packages.items())
        }


@dataclass(frozen=True)
class InstallPlan:
    order: tuple[str, ...]


@dataclass(frozen=True)
class StoreRecord:
    name: str
    version: str
    integrity: str
    tree_hash: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "integrity": self.integrity,
            "treeHash": self.tree_hash,
            "path": self.path,
        }
