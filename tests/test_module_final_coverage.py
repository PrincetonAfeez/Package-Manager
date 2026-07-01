"""Final coverage gaps: verify reachability, store tmp cleanup, constraints."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from pypm_lab.constraints import VersionConstraint
from pypm_lab.errors import ConstraintError
from pypm_lab.lockfile import Lockfile, LockPackage, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.registry import LocalRegistry
from pypm_lab.resolver import Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.verify import check_lockfile_consistency, verify_project
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def test_caret_empty_version():
    with pytest.raises(ConstraintError, match="missing version"):
        VersionConstraint.parse("^")


def test_verify_lockfile_reachability_missing_root_package(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    write_lockfile(
        project,
        Lockfile(
            roots=("alpha",),
            packages={
                "alpha": LockPackage(Version.parse("1.0.0"), DIGEST, {}),
                "ghost": LockPackage(Version.parse("9.9.9"), DIGEST, {}),
            },
        ),
    )
    ok, messages = verify_project(project, LocalRegistry(registry_dir))
    assert not ok
    assert any("not reachable" in message for message in messages)


def test_verify_lockfile_consistency_problems_surface():
    lockfile = Lockfile(
        roots=("alpha",),
        packages={
            "alpha": LockPackage(
                Version.parse("1.0.0"),
                DIGEST,
                {"shared": ">=9.0.0"},
            ),
            "shared": LockPackage(Version.parse("1.0.0"), DIGEST, {}),
        },
    )
    problems = check_lockfile_consistency(lockfile)
    assert any("requires shared" in problem for problem in problems)


def test_store_clean_removes_tmp_file(tmp_path):
    store = ProjectStore(tmp_path / "project")
    store.ensure()
    tmp_file = store.tmp_dir / "note.txt"
    tmp_file.write_text("leftover", encoding="utf-8")
    removed = store.clean()
    assert "tmp/note.txt" in removed
    assert not tmp_file.exists()


def test_verify_hash_directory_failure(tmp_path, build_registry: Callable[..., Path], monkeypatch):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    from pypm_lab.installer import install_resolved

    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))

    def fail_hash(path):
        raise OSError("cannot read tree")

    monkeypatch.setattr("pypm_lab.verify.hash_directory", fail_hash)
    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("cannot verify installed contents" in message for message in messages)
