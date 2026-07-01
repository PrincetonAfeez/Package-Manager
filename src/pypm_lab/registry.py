"""Registry interfaces and local/in-memory implementations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import RegistryError
from .fsio import atomic_write_json
from .models import PackageVersion
from .registry_validation import load_json_no_duplicates, validate_registry
from .requirements import validate_package_name
from .versions import Version


class InMemoryRegistry:
    """Small structured registry useful for pure resolver tests."""

    def __init__(self, packages: Mapping[str, Mapping[str, Mapping[str, Any] | PackageVersion]]):
        self._packages: dict[str, dict[Version, PackageVersion]] = {}
        for raw_name, versions in packages.items():
            name = validate_package_name(raw_name)
            self._packages[name] = {}
            for raw_version, data in versions.items():
                version = Version.parse(str(raw_version))
                if isinstance(data, PackageVersion):
                    package_version = data
                else:
                    dependencies = dict(sorted(data.get("dependencies", {}).items()))
                    package_version = PackageVersion(
                        name=name,
                        version=version,
                        dependencies=dependencies,
                        integrity=str(data.get("integrity", "sha256:" + "0" * 64)),
                        archive=str(data.get("archive", f"{name}-{version}.tar.gz")),
                        metadata=dict(data.get("metadata", {})),
                    )
                self._packages[name][version] = package_version

    def available_versions(self, name: str) -> list[Version]:
        normalized = validate_package_name(name)
        return sorted(self._packages.get(normalized, {}))

    def get_package_version(self, name: str, version: Version) -> PackageVersion:
        normalized = validate_package_name(name)
        try:
            return self._packages[normalized][version]
        except KeyError as exc:
            raise RegistryError(f"missing package version {normalized}@{version}") from exc


class LocalRegistry:
    """A local directory registry backed by `index.json` and archives."""

    def __init__(self, root: Path | str, *, validate: bool = True, verify_archives: bool = True):
        self.root = Path(root)
        if validate:
            self.index = validate_registry(self.root, verify_archives=verify_archives)
        else:
            self.index = load_json_no_duplicates(self.root / "index.json")
        self._packages = self._build_packages(self.index)

    def available_versions(self, name: str) -> list[Version]:
        normalized = validate_package_name(name)
        return sorted(self._packages.get(normalized, {}))

    def get_package_version(self, name: str, version: Version) -> PackageVersion:
        normalized = validate_package_name(name)
        try:
            return self._packages[normalized][version]
        except KeyError as exc:
            raise RegistryError(f"missing package version {normalized}@{version}") from exc

    def package_exists(self, name: str, version: Version) -> bool:
        normalized = validate_package_name(name)
        return version in self._packages.get(normalized, {})

    def _build_packages(self, data: dict[str, Any]) -> dict[str, dict[Version, PackageVersion]]:
        packages: dict[str, dict[Version, PackageVersion]] = {}
        for raw_name, package_data in data.get("packages", {}).items():
            name = validate_package_name(raw_name)
            packages[name] = {}
            versions = package_data.get("versions") if isinstance(package_data, dict) else None
            if not isinstance(versions, dict):
                raise RegistryError(f"{name}: registry entry is missing a 'versions' object")
            for raw_version, version_data in versions.items():
                version = Version.parse(raw_version)
                if not isinstance(version_data, dict) or not {"integrity", "archive"} <= set(version_data):
                    raise RegistryError(f"{name}@{version}: registry entry is missing 'integrity' or 'archive'")
                dependencies = {
                    validate_package_name(dep_name): raw_constraint
                    for dep_name, raw_constraint in sorted(version_data.get("dependencies", {}).items())
                }
                packages[name][version] = PackageVersion(
                    name=name,
                    version=version,
                    dependencies=dependencies,
                    integrity=version_data["integrity"],
                    archive=(self.root / version_data["archive"]).resolve(),
                    metadata={"registryArchive": version_data["archive"]},
                )
        return packages


def init_registry(root: Path | str) -> Path:
    registry_root = Path(root)
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "archives").mkdir(parents=True, exist_ok=True)
    index_path = registry_root / "index.json"
    if not index_path.exists():
        atomic_write_json(index_path, {"packages": {}})
    return index_path
