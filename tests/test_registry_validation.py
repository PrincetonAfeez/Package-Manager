"""Registry validation rejects malformed indexes and inconsistent archives."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pypm_lab.errors import RegistryValidationError
from pypm_lab.integrity import integrity_for_file
from pypm_lab.registry import LocalRegistry
from pypm_lab.registry_validation import read_archive_manifest, validate_registry

GOOD_DIGEST = "sha256:" + "0" * 64


def _write_registry(tmp_path: Path, index: Any) -> Path:
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    index_path = registry / "index.json"
    if isinstance(index, str):
        index_path.write_text(index, encoding="utf-8")
    else:
        index_path.write_text(json.dumps(index), encoding="utf-8")
    return registry


def _entry(archive: str, integrity: str = GOOD_DIGEST, dependencies: Any = None) -> dict[str, Any]:
    return {"archive": archive, "integrity": integrity, "dependencies": dependencies or {}}


def test_rejects_malformed_json(tmp_path):
    registry = _write_registry(tmp_path, "{ not valid json ")
    with pytest.raises(RegistryValidationError, match="malformed JSON"):
        validate_registry(registry)


def test_rejects_duplicate_keys(tmp_path):
    registry = _write_registry(
        tmp_path,
        '{"packages": {"alpha": {"versions": {}}, "alpha": {"versions": {}}}}',
    )
    with pytest.raises(RegistryValidationError, match="duplicate key"):
        validate_registry(registry)


def test_rejects_non_object_packages(tmp_path):
    registry = _write_registry(tmp_path, {"packages": []})
    with pytest.raises(RegistryValidationError, match="must contain a 'packages' object"):
        validate_registry(registry)


def test_rejects_invalid_package_name(tmp_path):
    registry = _write_registry(tmp_path, {"packages": {"Bad Name": {"versions": {"1.0.0": {}}}}})
    with pytest.raises(RegistryValidationError, match="invalid package name"):
        validate_registry(registry)


def test_rejects_invalid_version(tmp_path):
    registry = _write_registry(tmp_path, {"packages": {"alpha": {"versions": {"1.2": {}}}}})
    with pytest.raises(RegistryValidationError, match="invalid version"):
        validate_registry(registry)


def test_rejects_missing_versions(tmp_path):
    registry = _write_registry(tmp_path, {"packages": {"alpha": {}}})
    with pytest.raises(RegistryValidationError, match="missing or empty versions"):
        validate_registry(registry)


def test_rejects_missing_archive(tmp_path):
    index = {"packages": {"alpha": {"versions": {"1.0.0": {"integrity": GOOD_DIGEST, "dependencies": {}}}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="missing archive path"):
        validate_registry(registry)


def test_rejects_missing_integrity(tmp_path):
    version = {"archive": "archives/alpha-1.0.0.tar.gz", "dependencies": {}}
    index = {"packages": {"alpha": {"versions": {"1.0.0": version}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="missing integrity"):
        validate_registry(registry)


def test_rejects_invalid_integrity_prefix(tmp_path):
    index = {"packages": {"alpha": {"versions": {"1.0.0": _entry("archives/a.tar.gz", "sha1:abc")}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="invalid integrity"):
        validate_registry(registry)


def test_rejects_unsupported_hash_algorithm(tmp_path):
    index = {"packages": {"alpha": {"versions": {"1.0.0": _entry("archives/a.tar.gz", "md5:" + "0" * 32)}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="invalid integrity"):
        validate_registry(registry)


def test_rejects_archive_path_traversal(tmp_path):
    index = {"packages": {"alpha": {"versions": {"1.0.0": _entry("../outside.tar.gz")}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="must stay inside the registry"):
        validate_registry(registry)


def test_rejects_malformed_dependency_constraint(tmp_path):
    entry = _entry("archives/a.tar.gz", dependencies={"alpha": ">>1.0"})
    index = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="malformed dependency constraint"):
        validate_registry(registry)


def test_rejects_dependency_on_missing_package(tmp_path):
    entry = _entry("archives/a.tar.gz", dependencies={"ghost": ">=1.0.0"})
    index = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    registry = _write_registry(tmp_path, index)
    with pytest.raises(RegistryValidationError, match="dependency on missing package ghost"):
        validate_registry(registry)


def test_rejects_archive_hash_mismatch(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    (registry / "archives" / archive.name).write_bytes(archive.read_bytes())
    index = {"packages": {"alpha": {"versions": {"1.0.0": _entry(f"archives/{archive.name}", GOOD_DIGEST)}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="archive hash mismatch"):
        validate_registry(registry)


def test_rejects_archive_metadata_name_disagreement(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = _entry(f"archives/{archive.name}", integrity_for_file(placed))
    index = {"packages": {"beta": {"versions": {"1.0.0": entry}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="archive metadata name"):
        validate_registry(registry)


def test_read_archive_manifest_prefers_root_over_decoy(tmp_path, make_archive: Callable[..., Path]):
    # Regression: a nested decoy package.json must not shadow the archive root manifest.
    decoy = json.dumps({"name": "aaa", "version": "9.9.9", "dependencies": {}})
    archive = make_archive("zebra", "1.0.0", extra_files={"aaa/package.json": decoy})

    manifest = read_archive_manifest(archive)

    assert manifest["name"] == "zebra"
    assert manifest["version"] == "1.0.0"


def test_validate_disabled_registry_reports_structural_error(tmp_path):
    # With validation disabled, a malformed index raises a RegistryError rather than KeyError.
    from pypm_lab.errors import RegistryError

    registry = _write_registry(tmp_path, {"packages": {"alpha": {}}})
    with pytest.raises(RegistryError, match="missing a 'versions' object"):
        LocalRegistry(registry, validate=False)
