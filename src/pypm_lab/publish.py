"""Local-only publish support."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .errors import RegistryError, RegistryValidationError
from .fsio import atomic_write_json
from .integrity import integrity_for_file
from .models import PackageVersion
from .registry import init_registry
from .registry_validation import (
    load_json_no_duplicates,
    parse_archive_manifest_fields,
    read_archive_manifest,
    validate_new_entry,
)


def publish_archive(registry_dir: Path | str, archive_path: Path | str) -> PackageVersion:
    registry_root = Path(registry_dir)
    init_registry(registry_root)
    source_archive = Path(archive_path)
    if not source_archive.exists():
        raise RegistryError(f"archive does not exist: {source_archive}")

    manifest = read_archive_manifest(source_archive)
    name, version, dependencies = parse_archive_manifest_fields(manifest)

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
            "dependencies": dependencies,
        }
        versions[str(version)] = new_entry
        validate_new_entry(registry_root, name, version, new_entry)
        atomic_write_json(index_path, data)
    except RegistryValidationError:
        destination.unlink(missing_ok=True)
        raise
    except Exception:
        destination.unlink(missing_ok=True)
        tmp_archive.unlink(missing_ok=True)
        raise

    return PackageVersion(
        name=name,
        version=version,
        dependencies=dependencies,
        integrity=integrity,
        archive=destination,
        metadata={"registryArchive": destination_relative.as_posix()},
    )
