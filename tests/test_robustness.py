"""Regression tests for cross-platform reproducibility, safe extraction, and parsing."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
from typing import Callable

import pytest

from pypm_lab.errors import (
    InstallError,
    LockfileError,
    ManifestError,
    RegistryValidationError,
)
from pypm_lab.installer import install_resolved
from pypm_lab.integrity import hash_directory, integrity_for_file
from pypm_lab.lockfile import load_lockfile
from pypm_lab.manifest import load_manifest
from pypm_lab.models import PackageVersion, ResolvedGraph, ResolvedPackage
from pypm_lab.registry import InMemoryRegistry
from pypm_lab.registry_validation import validate_new_entry
from pypm_lab.store import ProjectStore
from pypm_lab.versions import Version


def test_hash_directory_orders_by_posix_path(tmp_path):
    # The digest must order files by case-sensitive POSIX path on every OS, so a
    # Windows tree hash matches a POSIX one for archives with mixed-case names.
    root = tmp_path / "pkg"
    (root / "src").mkdir(parents=True)
    files = {"README.md": b"r", "package.json": b"p", "src/x.txt": b"x"}
    for relative, content in files.items():
        (root / relative).write_bytes(content)

    reference = hashlib.sha256()
    for relative in sorted(files):
        reference.update(relative.encode("utf-8"))
        reference.update(b"\0")
        reference.update(files[relative])
        reference.update(b"\0")

    assert hash_directory(root) == f"sha256:{reference.hexdigest()}"


def test_install_rejects_archive_member_escape(tmp_path):
    archive = tmp_path / "evil-1.0.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"escape"
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    integrity = integrity_for_file(archive)
    version = Version.parse("1.0.0")
    registry = InMemoryRegistry(
        {"evil": {"1.0.0": PackageVersion("evil", version, {}, integrity, archive)}}
    )
    graph = ResolvedGraph(
        roots=("evil",),
        packages={"evil": ResolvedPackage("evil", version, {}, integrity, str(archive))},
    )
    project = tmp_path / "project"

    with pytest.raises(InstallError, match="escapes install root"):
        install_resolved(project, graph, registry)

    assert ProjectStore(project).read_records() == {}


def test_read_records_reports_missing_field(tmp_path):
    store = ProjectStore(tmp_path / "project")
    store.ensure()
    store.installed_path.write_text(
        json.dumps({"packages": {"alpha": {"version": "1.0.0", "integrity": "sha256:" + "0" * 64}}}),
        encoding="utf-8",
    )

    with pytest.raises(InstallError, match="missing field treeHash"):
        store.read_records()


def test_manifest_rejects_duplicate_keys(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name": "demo", "dependencies": {"alpha": "1.0.0", "alpha": "2.0.0"}}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="duplicate key"):
        load_manifest(tmp_path)


def test_lockfile_rejects_duplicate_keys(tmp_path):
    (tmp_path / "pypm-lock.json").write_text(
        '{"lockfileVersion": 1, "roots": [], "packages": {"alpha": {}, "alpha": {}}}',
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="duplicate key"):
        load_lockfile(tmp_path)


def test_lockfile_rejects_malformed_integrity(tmp_path):
    (tmp_path / "pypm-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": {"version": "1.0.0", "integrity": "not-a-hash", "dependencies": {}}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="invalid integrity"):
        load_lockfile(tmp_path)


def test_lockfile_rejects_malformed_version(tmp_path):
    (tmp_path / "pypm-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": {"version": "1.2", "integrity": "sha256:" + "0" * 64, "dependencies": {}}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="invalid version"):
        load_lockfile(tmp_path)


def _place_archive(tmp_path: Path, archive: Path) -> Path:
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    (registry / "archives" / archive.name).write_bytes(archive.read_bytes())
    return registry


def test_validate_new_entry_checks_integrity_prefix(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    registry = _place_archive(tmp_path, archive)
    entry = {"archive": f"archives/{archive.name}", "integrity": "sha1:abc", "dependencies": {}}

    with pytest.raises(RegistryValidationError, match="invalid integrity"):
        validate_new_entry(registry, "alpha", Version.parse("1.0.0"), entry)


def test_validate_new_entry_allows_forward_dependency(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0", {"ghost": ">=1.0.0"})
    registry = _place_archive(tmp_path, archive)
    placed = registry / "archives" / archive.name
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {"ghost": ">=1.0.0"},
    }

    # Validates the entry without requiring the dependency to exist yet.
    validate_new_entry(registry, "alpha", Version.parse("1.0.0"), entry)
