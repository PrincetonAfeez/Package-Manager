"""Exhaustive manifest and store module tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from pypm_lab.errors import InstallError, ManifestError
from pypm_lab.manifest import (
    MANIFEST_NAME,
    add_dependency,
    init_manifest,
    load_manifest,
    manifest_path,
    remove_dependency,
    save_manifest,
)
from pypm_lab.models import StoreRecord
from pypm_lab.store import ProjectStore

DIGEST = "sha256:" + "0" * 64
TREE = "sha256:" + "1" * 64


def test_manifest_path(tmp_path):
    assert manifest_path(tmp_path) == tmp_path / MANIFEST_NAME


def test_load_manifest_missing(tmp_path):
    with pytest.raises(ManifestError, match="missing manifest"):
        load_manifest(tmp_path)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def test_load_manifest_malformed_json(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError, match="malformed manifest"):
        load_manifest(project)


def test_load_manifest_duplicate_keys(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text(
        '{"name": "demo", "dependencies": {}, "dependencies": {"a": "1.0.0"}}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="malformed manifest"):
        load_manifest(project)


def test_load_manifest_not_object(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text("[]", encoding="utf-8")
    with pytest.raises(ManifestError, match="must be a JSON object"):
        load_manifest(project)


def test_load_manifest_invalid_name(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text(
        '{"name": "Bad Name", "dependencies": {}}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="invalid package name"):
        load_manifest(project)


def test_load_manifest_dependencies_not_object(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text(
        '{"name": "demo", "dependencies": []}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="dependencies must be an object"):
        load_manifest(project)


def test_load_manifest_dependency_constraint_not_string(tmp_path):
    project = _project(tmp_path)
    manifest_path(project).write_text(
        '{"name": "demo", "dependencies": {"alpha": 1}}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="constraint must be a string"):
        load_manifest(project)


def test_init_manifest_returns_existing(tmp_path):
    init_manifest(tmp_path, name="demo")
    first = load_manifest(tmp_path)
    second = init_manifest(tmp_path, name="other")
    assert second.name == first.name


def test_init_manifest_invalid_directory_name(tmp_path):
    bad = tmp_path / "Bad Name!"
    with pytest.raises(ManifestError, match="cannot derive project name"):
        init_manifest(bad)


def test_init_manifest_invalid_explicit_name(tmp_path):
    with pytest.raises(ManifestError, match="invalid package name"):
        init_manifest(tmp_path, name="../bad")


def test_save_and_load_roundtrip(tmp_path):
    from pypm_lab.manifest import Manifest

    manifest = Manifest(name="demo", dependencies={"alpha": "^1.0.0"})
    save_manifest(tmp_path, manifest)
    loaded = load_manifest(tmp_path)
    assert loaded.name == "demo"
    assert loaded.dependencies == {"alpha": "^1.0.0"}
    assert loaded.requirements()[0].name == "alpha"


def test_add_and_remove_dependency(tmp_path):
    init_manifest(tmp_path, name="demo")
    updated = add_dependency(tmp_path, "alpha", "^1.0.0")
    assert "alpha" in updated.dependencies
    removed = remove_dependency(tmp_path, "alpha")
    assert removed.dependencies == {}


def test_remove_missing_dependency(tmp_path):
    init_manifest(tmp_path, name="demo")
    with pytest.raises(ManifestError, match="not a direct dependency"):
        remove_dependency(tmp_path, "ghost")


def test_store_read_records_missing_file(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.read_records() == {}


def test_store_read_records_malformed_json(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    store.installed_path.write_text("{", encoding="utf-8")
    with pytest.raises(InstallError, match="malformed installed record"):
        store.read_records()


def test_store_read_records_packages_not_object(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    store.installed_path.write_text('{"packages": []}', encoding="utf-8")
    with pytest.raises(InstallError, match="packages must be an object"):
        store.read_records()


def test_store_read_records_entry_not_object(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    store.installed_path.write_text('{"packages": {"alpha": []}}', encoding="utf-8")
    with pytest.raises(InstallError, match="must be an object"):
        store.read_records()


def test_store_read_records_missing_field(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    store.installed_path.write_text(
        '{"packages": {"alpha": {"version": "1.0.0"}}}',
        encoding="utf-8",
    )
    with pytest.raises(InstallError, match="missing field"):
        store.read_records()


def test_store_package_dir_and_cache_path(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.package_dir("alpha", "1.0.0") == store.store_dir / "alpha" / "1.0.0"
    assert store.cache_path(DIGEST).name.endswith(".tar.gz")


def test_store_clean_skips_non_directory_entries(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    stray = store.store_dir / "stray.txt"
    stray.write_text("orphan", encoding="utf-8")
    assert store.clean() == []


def test_store_clean_prunes_empty_name_dir_and_tmp(tmp_path):
    store = ProjectStore(tmp_path)
    store.ensure()
    orphan_name = store.store_dir / "orphan"
    orphan_version = orphan_name / "1.0.0"
    orphan_version.mkdir(parents=True)
    (orphan_version / "file.txt").write_text("x", encoding="utf-8")
    leftover = store.tmp_dir / "leftover.tmp"
    leftover.write_text("tmp", encoding="utf-8")

    removed = store.clean()
    assert any("orphan/1.0.0" in item for item in removed)
    assert any("tmp/leftover.tmp" in item for item in removed)
    assert not orphan_name.exists()
    assert not leftover.exists()


def test_store_write_records_persists(tmp_path):
    store = ProjectStore(tmp_path)
    record = StoreRecord(
        name="alpha",
        version="1.0.0",
        integrity=DIGEST,
        tree_hash=TREE,
        path="store/alpha/1.0.0",
    )
    store.write_records({"alpha": record})
    loaded = store.read_records()
    assert loaded["alpha"].to_dict() == record.to_dict()
