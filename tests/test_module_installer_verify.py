"""Exhaustive installer, verify, registry, and integrity tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab.errors import InstallError, IntegrityError, RegistryError
from pypm_lab.installer import (
    _archive_content_root,
    _replace_directory,
    graph_from_lockfile,
    install_resolved,
)
from pypm_lab.integrity import hash_directory
from pypm_lab.lockfile import Lockfile, LockPackage, load_lockfile, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.models import PackageVersion, ResolvedGraph, ResolvedPackage
from pypm_lab.registry import InMemoryRegistry, LocalRegistry
from pypm_lab.resolver import Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.verify import (
    check_manifest_lockfile_alignment,
    verify_project,
)
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def test_graph_from_lockfile_integrity_mismatch():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {"integrity": DIGEST}}})
    lockfile = Lockfile(
        roots=("alpha",),
        packages={
            "alpha": LockPackage(
                Version.parse("1.0.0"),
                "sha256:" + "f" * 64,
                {},
            )
        },
    )
    with pytest.raises(IntegrityError, match="does not match registry"):
        graph_from_lockfile(lockfile, registry)


def test_install_references_missing_graph_package(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    from pypm_lab.integrity import integrity_for_file

    integrity = integrity_for_file(archive)
    registry = InMemoryRegistry(
        {
            "alpha": {
                "1.0.0": PackageVersion(
                    name="alpha",
                    version=Version.parse("1.0.0"),
                    dependencies={},
                    integrity=integrity,
                    archive=archive,
                )
            }
        }
    )
    graph = ResolvedGraph(
        roots=("alpha", "ghost"),
        packages={
            "alpha": ResolvedPackage(
                name="alpha",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity=integrity,
                archive=str(archive),
            )
        },
    )
    with mock.patch("pypm_lab.installer.topological_sort", return_value=["ghost", "alpha"]):
        with pytest.raises(InstallError, match="missing package ghost"):
            install_resolved(tmp_path / "project", graph, registry)


def test_install_resolved_integrity_mismatch_with_registry(
    tmp_path, make_archive: Callable[..., Path]
):
    archive = make_archive("alpha", "1.0.0")
    bad = "sha256:" + "f" * 64
    registry = InMemoryRegistry(
        {
            "alpha": {
                "1.0.0": PackageVersion(
                    name="alpha",
                    version=Version.parse("1.0.0"),
                    dependencies={},
                    integrity=bad,
                    archive=archive,
                )
            }
        }
    )
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={
            "alpha": ResolvedPackage(
                name="alpha",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity=DIGEST,
                archive=str(archive),
            )
        },
    )
    with pytest.raises(IntegrityError, match="does not match registry"):
        install_resolved(tmp_path / "project", graph, registry)


def test_archive_content_root_flat_layout(tmp_path):
    root = tmp_path / "flat"
    root.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    assert _archive_content_root(root) == root


def test_replace_directory_success_removes_backup(tmp_path):
    final = tmp_path / "final"
    final.mkdir()
    (final / "old.txt").write_text("old", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    _replace_directory(source, final, tmp_root)
    assert (final / "new.txt").exists()
    assert not (tmp_root / "backup-final").exists()


def test_replace_directory_cleans_new_final_on_failure(tmp_path):
    final = tmp_path / "final"
    source = tmp_path / "source"
    source.mkdir()
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    real_rename = Path.rename

    def fail_first(self, target):
        if self == source:
            raise OSError("fail")
        return real_rename(self, target)

    with mock.patch.object(Path, "rename", fail_first):
        with pytest.raises(OSError, match="fail"):
            _replace_directory(source, final, tmp_root)
    assert not final.exists()


def test_hash_directory_missing_path(tmp_path):
    with pytest.raises(IntegrityError, match="cannot hash missing directory"):
        hash_directory(tmp_path / "missing")


def test_in_memory_registry_missing_version():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {}}})
    with pytest.raises(RegistryError, match="missing package version"):
        registry.get_package_version("alpha", Version.parse("9.9.9"))


def test_local_registry_package_exists(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.publish import publish_archive

    registry_dir = tmp_path / "registry"
    publish_archive(registry_dir, make_archive("alpha", "1.0.0"))
    registry = LocalRegistry(registry_dir)
    assert registry.package_exists("alpha", Version.parse("1.0.0"))
    assert not registry.package_exists("alpha", Version.parse("9.9.9"))


def test_local_registry_validate_false_malformed_version_entry(tmp_path):
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    (registry / "index.json").write_text(
        json.dumps({"packages": {"alpha": {"versions": {"1.0.0": {"archive": "a.tar.gz"}}}}}),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="missing 'integrity' or 'archive'"):
        LocalRegistry(registry, validate=False)


def test_verify_manifest_version_mismatch(tmp_path, build_registry: Callable[..., Path]):
    build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "^2.0.0")
    write_lockfile(
        project,
        Lockfile(
            roots=("alpha",),
            packages={
                "alpha": LockPackage(Version.parse("1.0.0"), DIGEST, {}),
            },
        ),
    )
    problems = check_manifest_lockfile_alignment(load_manifest(project), load_lockfile(project))
    assert any("manifest requires" in problem for problem in problems)


def test_verify_missing_installed_record(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    write_lockfile(project, Lockfile.from_graph(graph))
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("missing installed record" in message for message in messages)


def test_verify_installed_version_mismatch(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))
    store = ProjectStore(project)
    records = store.read_records()
    alpha = records["alpha"]
    records["alpha"] = alpha.__class__(
        name="alpha",
        version="9.9.9",
        integrity=alpha.integrity,
        tree_hash=alpha.tree_hash,
        path="store/alpha/9.9.9",
    )
    store.package_dir("alpha", "9.9.9").mkdir(parents=True)
    store.write_records(records)
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("installed version" in message for message in messages)


def test_verify_installed_integrity_mismatch(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))
    store = ProjectStore(project)
    records = store.read_records()
    record = records["alpha"]
    records["alpha"] = record.__class__(
        name=record.name,
        version=record.version,
        integrity="sha256:" + "f" * 64,
        tree_hash=record.tree_hash,
        path=record.path,
    )
    store.write_records(records)
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("installed integrity differs" in message for message in messages)


def test_verify_missing_installed_directory(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))
    import shutil

    shutil.rmtree(project / ".pypm" / "store" / "alpha" / "1.0.0")
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("missing installed package directory" in message for message in messages)


def test_verify_registry_integrity_mismatch(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    lock = Lockfile.from_graph(graph)
    locked = lock.packages["alpha"]
    lock = Lockfile(
        packages={
            "alpha": LockPackage(
                locked.version,
                "sha256:" + "f" * 64,
                locked.dependencies,
            )
        },
        roots=lock.roots,
    )
    write_lockfile(project, lock)
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("registry integrity differs" in message for message in messages)


def test_verify_registry_archive_failure(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))
    archive_path = registry_dir / "archives" / "alpha-1.0.0.tar.gz"
    archive_path.write_bytes(b"tampered")
    structural = LocalRegistry(registry_dir, validate=False)
    ok, messages = verify_project(project, structural)
    assert not ok
    assert any(
        "registry archive verification failed" in message or "hash mismatch" in message
        for message in messages
    )


def test_verify_project_reports_invalid_installed_records(
    tmp_path, build_registry: Callable[..., Path]
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))

    store = ProjectStore(project)
    store.installed_path.write_text(
        json.dumps(
            {
                "packages": {
                    "alpha": {
                        "version": "1.0.0",
                        "integrity": DIGEST,
                        "treeHash": "sha256:" + "1" * 64,
                        "path": "store/alpha/1.0.0/../../cache/sha256/evil",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("installed records invalid" in message for message in messages)
