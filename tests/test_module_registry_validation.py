"""Additional registry_validation coverage for cumulative error paths."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pypm_lab.errors import RegistryValidationError
from pypm_lab.registry_validation import load_json_no_duplicates, validate_index_data

DIGEST = "sha256:" + "0" * 64


def test_load_json_non_object(tmp_path):
    path = tmp_path / "index.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="must contain a JSON object"):
        load_json_no_duplicates(path)


def test_validate_invalid_package_name_in_index(tmp_path):
    data = {"packages": {"Bad Name": {"versions": {"1.0.0": {}}}}}
    with pytest.raises(RegistryValidationError, match="invalid package name"):
        validate_index_data(tmp_path, data, verify_archives=False)


def test_validate_non_string_integrity_field(tmp_path, make_archive: Callable[..., Path]):

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    data = {
        "packages": {
            "alpha": {
                "versions": {
                    "1.0.0": {
                        "archive": f"archives/{archive.name}",
                        "integrity": 123,
                        "dependencies": {},
                    }
                }
            }
        }
    }
    with pytest.raises(RegistryValidationError, match="missing integrity"):
        validate_index_data(registry, data, verify_archives=False)


def test_validate_invalid_dependency_name_in_index(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.integrity import integrity_for_file

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {"Bad Dep": ">=1.0.0"},
    }
    data = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    with pytest.raises(RegistryValidationError, match="invalid dependency name"):
        validate_index_data(registry, data, verify_archives=False)


def test_validate_archive_metadata_invalid_dependency_name(
    tmp_path, make_archive: Callable[..., Path]
):
    from pypm_lab.integrity import integrity_for_file

    build_root = tmp_path / "build" / "alpha-1.0.0"
    build_root.mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps(
            {
                "name": "alpha",
                "version": "1.0.0",
                "dependencies": {"Bad Dep": ">=1.0.0"},
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "alpha-1.0.0.tar.gz"
    import tarfile

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(build_root, arcname="alpha-1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    data = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    with pytest.raises(RegistryValidationError, match="archive dependency name is invalid"):
        validate_index_data(registry, data, verify_archives=True)


def test_validate_archive_non_object_dependencies(
    tmp_path, make_archive: Callable[..., Path]
):
    from pypm_lab.integrity import integrity_for_file

    build_root = tmp_path / "build" / "alpha-1.0.0"
    build_root.mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps({"name": "alpha", "version": "1.0.0", "dependencies": []}),
        encoding="utf-8",
    )
    archive = tmp_path / "alpha-1.0.0.tar.gz"
    import tarfile

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(build_root, arcname="alpha-1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    data = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    with pytest.raises(RegistryValidationError, match="archive dependencies must be an object"):
        validate_index_data(registry, data, verify_archives=True)
