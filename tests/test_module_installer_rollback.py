"""Installer rollback and prune edge-case tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab.errors import InstallError
from pypm_lab.installer import install_resolved
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.registry import LocalRegistry
from pypm_lab.resolver import Resolver
from pypm_lab.store import ProjectStore


def test_rollback_removes_attempted_package_and_prunes_parent(
    tmp_path, build_registry: Callable[..., Path]
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph

    with mock.patch(
        "pypm_lab.installer._place_package",
        side_effect=InstallError("simulated placement failure"),
    ):
        with pytest.raises(InstallError):
            install_resolved(project, graph, registry)

    assert not ProjectStore(project).read_records()


def test_rollback_restores_previous_record(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}, "2.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph_v1 = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph_v1, registry)
    original = ProjectStore(project).read_records()["alpha"]

    add_dependency(project, "alpha", "2.0.0")
    graph_v2 = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    with mock.patch(
        "pypm_lab.installer._place_package",
        side_effect=InstallError("simulated failure"),
    ):
        with pytest.raises(InstallError):
            install_resolved(project, graph_v2, registry)

    restored = ProjectStore(project).read_records()["alpha"]
    assert restored.version == original.version


def test_rollback_reports_write_records_failure(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    original_write = ProjectStore.write_records
    calls = {"count": 0}

    def flaky_write(self, records):
        calls["count"] += 1
        if calls["count"] > 1:
            raise OSError("disk full")
        return original_write(self, records)

    with mock.patch(
        "pypm_lab.installer._place_package",
        side_effect=InstallError("simulated failure"),
    ):
        with mock.patch.object(ProjectStore, "write_records", flaky_write):
            with pytest.raises(InstallError, match="rollback incomplete"):
                install_resolved(project, graph, registry)
