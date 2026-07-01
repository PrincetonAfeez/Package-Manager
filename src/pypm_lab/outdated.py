"""Find installed packages that have newer releases in the registry."""

from __future__ import annotations

from dataclasses import dataclass

from .lockfile import Lockfile
from .manifest import Manifest
from .resolver import RegistryReader
from .versions import Version


@dataclass(frozen=True)
class OutdatedPackage:
    name: str
    current: Version
    latest: Version
    # Newest registry version still allowed by the direct manifest constraint,
    # or None when the package is not a direct dependency.
    latest_compatible: Version | None

    def describe(self) -> str:
        line = f"{self.name}: {self.current} -> {self.latest}"
        if self.latest_compatible is not None and self.latest_compatible != self.latest:
            line += f" (latest compatible: {self.latest_compatible})"
        return line


@dataclass(frozen=True)
class MissingRegistryPackage:
    name: str
    locked_version: Version

    def describe(self) -> str:
        return f"{self.name}@{self.locked_version}: missing from registry"


@dataclass(frozen=True)
class OutdatedReport:
    outdated: tuple[OutdatedPackage, ...]
    missing: tuple[MissingRegistryPackage, ...]


def find_outdated(
    lockfile: Lockfile,
    manifest: Manifest,
    registry: RegistryReader,
) -> OutdatedReport:
    direct = {requirement.name: requirement.constraint for requirement in manifest.requirements()}
    outdated: list[OutdatedPackage] = []
    missing: list[MissingRegistryPackage] = []
    for name, locked in sorted(lockfile.packages.items()):
        available = registry.available_versions(name)
        if not available:
            missing.append(MissingRegistryPackage(name, locked.version))
            continue
        latest = max(available)
        if latest <= locked.version:
            continue
        latest_compatible: Version | None = None
        if name in direct:
            allowed = [version for version in available if direct[name].allows(version)]
            if allowed:
                latest_compatible = max(allowed)
        outdated.append(OutdatedPackage(name, locked.version, latest, latest_compatible))
    return OutdatedReport(outdated=tuple(outdated), missing=tuple(missing))
