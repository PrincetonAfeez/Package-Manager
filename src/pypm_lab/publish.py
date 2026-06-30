"""Local-only publish support."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from .constraints import VersionConstraint
from .errors import RegistryError, RegistryValidationError
from .integrity import integrity_for_file
from .models import PackageVersion
from .registry import init_registry
from .registry_validation import (
    load_json_no_duplicates,
    read_archive_manifest,
    validate_new_entry,
)
from .requirements import validate_package_name
from .versions import Version


def publish_archive(registry_dir: Path | str, archive_path: Path | str) -> PackageVersion:
    registry_root = Path(registry_dir)
    init_registry(registry_root)
    source_archive = Path(archive_path)
    if not source_archive.exists():
        raise RegistryError(f"archive does not exist: {source_archive}")

    manifest = read_archive_manifest(source_archive)
    name = validate_package_name(str(manifest.get("name", "")))
    version = Version.parse(str(manifest.get("version", "")))
    dependencies_data = manifest.get("dependencies", {})
    if not isinstance(dependencies_data, dict):
        raise RegistryError("archive dependencies must be an object")
    dependencies: dict[str, str] = {}
    for raw_name, raw_constraint in dependencies_data.items():
        dependency_name = validate_package_name(raw_name)
        if not isinstance(raw_constraint, str):
            raise RegistryError(f"dependency {dependency_name} constraint must be a string")
        VersionConstraint.parse(raw_constraint)
        dependencies[dependency_name] = raw_constraint

    index_path = registry_root / "index.json"
    data = load_json_no_duplicates(index_path)
    packages = data.setdefault("packages", {})
    package_entry = packages.setdefault(name, {"versions": {}})
    versions = package_entry.setdefault("versions", {})
    if str(version) in versions:
        raise RegistryError(f"{name}@{version} already exists in the registry")

    destination_relative = Path("archives") / f"{name}-{version}.tar.gz"
    destination = registry_root / destination_relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_archive = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source_archive, tmp_archive)
        os.replace(tmp_archive, destination)
        integrity = integrity_for_file(destination)
        new_entry = {
            "archive": destination_relative.as_posix(),
            "integrity": integrity,
            "dependencies": dict(sorted(dependencies.items())),
        }
        versions[str(version)] = new_entry
        # Validate only the newly added entry: its archive metadata must agree
        # with the index, but dependencies need not already exist, so packages
        # (including cyclic pairs) can be published in any order. Cross-package
        # dependency existence is enforced later, at registry load time.
        validate_new_entry(registry_root, name, version, new_entry)
        _write_index_atomic(index_path, data)
    except RegistryValidationError:
        destination.unlink(missing_ok=True)
        raise
    except Exception:
        # The archive may already have been moved into place; remove either the
        # staged temp file or the placed archive so a failed publish leaves no
        # orphan behind.
        destination.unlink(missing_ok=True)
        tmp_archive.unlink(missing_ok=True)
        raise

    return PackageVersion(
        name=name,
        version=version,
        dependencies=dict(sorted(dependencies.items())),
        integrity=integrity,
        archive=destination,
        metadata={"registryArchive": destination_relative.as_posix()},
    )


def _write_index_atomic(index_path: Path, data: dict[str, object]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix="index-", suffix=".json", dir=str(index_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, index_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
