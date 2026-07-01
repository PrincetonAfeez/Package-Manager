"""Round 2 regression tests for install rollback, JSON parity, and verify reachability."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab.errors import InstallError
from pypm_lab.installer import install_resolved
from pypm_lab.lockfile import Lockfile, LockPackage, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest, remove_dependency
from pypm_lab.registry import LocalRegistry
from pypm_lab.resolver import Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.verify import check_lockfile_reachability, verify_project
from pypm_lab.versions import Version


def test_write_records_failure_preserves_orphan_directories(
    tmp_path, build_registry: Callable[..., Path]
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    registry = LocalRegistry(registry_dir)

    add_dependency(project, "alpha", "1.0.0")
    add_dependency(project, "bravo", "1.0.0")
    resolution = Resolver(registry).resolve(load_manifest(project).requirements())
    install_resolved(project, resolution.graph, registry)
    bravo_dir = project / ".pypm" / "store" / "bravo" / "1.0.0"
    assert bravo_dir.exists()

    remove_dependency(project, "bravo")
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    store = ProjectStore(project)
    original_write = store.write_records

    def fail_write(records):
        if "bravo" not in records:
            raise OSError("simulated write failure")
        original_write(records)

    with mock.patch.object(ProjectStore, "write_records", side_effect=fail_write):
        with pytest.raises(OSError, match="simulated write failure"):
            install_resolved(project, graph, registry)

    assert bravo_dir.exists()
    assert "bravo" in store.read_records()


def test_rollback_reports_restore_failures(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)

    with mock.patch(
        "pypm_lab.installer._place_package",
        side_effect=InstallError("simulated placement failure"),
    ):
        with pytest.raises(InstallError, match="rollback incomplete"):
            install_resolved(project, graph, registry)

    records = ProjectStore(project).read_records()
    assert records["shared"].version == "1.0.0"


def test_installed_json_rejects_duplicate_keys(tmp_path):
    store = ProjectStore(tmp_path / "project")
    store.ensure()
    store.installed_path.write_text(
        '{"packages": {"alpha": {"version": "1.0.0", "integrity": "sha256:' + "0" * 64
        + '", "treeHash": "sha256:' + "1" * 64 + '", "path": "store/a/1.0.0"}, '
        '"alpha": {"version": "2.0.0", "integrity": "sha256:' + "0" * 64
        + '", "treeHash": "sha256:' + "1" * 64 + '", "path": "store/a/2.0.0"}}}',
        encoding="utf-8",
    )
    with pytest.raises(InstallError, match="duplicate key"):
        store.read_records()


def test_check_lockfile_reachability_flags_unreachable_package():
    digest = "sha256:" + "0" * 64
    lockfile = Lockfile(
        packages={
            "alpha": LockPackage(Version.parse("1.0.0"), digest, {}),
            "ghost": LockPackage(Version.parse("9.9.9"), digest, {}),
        },
        roots=("alpha",),
    )
    problems = check_lockfile_reachability(lockfile)
    assert any("ghost" in problem and "not reachable" in problem for problem in problems)


def test_verify_reports_unreachable_lockfile_package(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    digest = "sha256:" + "0" * 64
    write_lockfile(
        project,
        Lockfile(
            packages={
                "shared": LockPackage(Version.parse("1.0.0"), digest, {}),
                "ghost": LockPackage(Version.parse("9.9.9"), digest, {}),
            },
            roots=("shared",),
        ),
    )
    registry = LocalRegistry(registry_dir)
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("ghost" in message and "not reachable" in message for message in messages)
