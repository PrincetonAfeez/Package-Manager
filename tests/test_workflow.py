"""End-to-end workflow behavior: publish order, cycles, lockfile reuse, integrity."""

from pathlib import Path
from typing import Callable

import pytest

from pypm_lab import cli
from pypm_lab.errors import RegistryValidationError
from pypm_lab.installer import install_from_lockfile, install_resolved
from pypm_lab.lockfile import LockPackage, Lockfile, load_lockfile, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.registry import LocalRegistry
from pypm_lab.requirements import parse_requirement
from pypm_lab.resolver import ResolutionFailed, Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.verify import verify_project
from pypm_lab.versions import Version


def _run(project: Path, registry: Path, *args: str) -> int:
    return cli.main(["--project-dir", str(project), "--registry", str(registry), *args])


def test_publish_allows_dependent_before_dependency(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.publish import publish_archive

    registry_dir = tmp_path / "registry"
    # Publish the dependent (alpha) before its dependency (shared); order is now free.
    publish_archive(registry_dir, make_archive("alpha", "1.0.0", {"shared": ">=1.0.0,<2.0.0"}))
    publish_archive(registry_dir, make_archive("shared", "1.0.0"))

    registry = LocalRegistry(registry_dir)
    result = Resolver(registry).resolve([parse_requirement("alpha@1.0.0")])

    assert str(result.graph.packages["shared"].version) == "1.0.0"


def test_registry_load_rejects_dangling_dependency(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.publish import publish_archive

    registry_dir = tmp_path / "registry"
    publish_archive(registry_dir, make_archive("alpha", "1.0.0", {"ghost": ">=1.0.0"}))

    # Publish succeeds, but loading the registry enforces dependency existence.
    with pytest.raises(RegistryValidationError, match="dependency on missing package ghost"):
        LocalRegistry(registry_dir)


def test_cyclic_packages_publish_and_resolve_reports_cycle(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.publish import publish_archive

    registry_dir = tmp_path / "registry"
    publish_archive(registry_dir, make_archive("aa", "1.0.0", {"bb": "1.0.0"}))
    publish_archive(registry_dir, make_archive("bb", "1.0.0", {"aa": "1.0.0"}))

    registry = LocalRegistry(registry_dir)
    with pytest.raises(ResolutionFailed) as exc:
        Resolver(registry).resolve([parse_requirement("aa@1.0.0")])

    explanation = exc.value.conflict.explain()
    assert "Dependency cycle detected:" in explanation


def test_install_honors_existing_lockfile(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}, "1.1.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "^1.0.0")

    # Resolve picks the newest compatible (1.1.0).
    assert _run(project, registry_dir, "resolve") == 0
    assert str(load_lockfile(project).packages["shared"].version) == "1.1.0"

    # Repin the lockfile to 1.0.0 (still satisfies ^1.0.0) and install.
    registry = LocalRegistry(registry_dir)
    pinned = registry.get_package_version("shared", Version.parse("1.0.0"))
    write_lockfile(
        project,
        Lockfile(
            packages={"shared": LockPackage(version=Version.parse("1.0.0"), integrity=pinned.integrity, dependencies={})},
            roots=("shared",),
        ),
    )

    assert _run(project, registry_dir, "install") == 0
    records = ProjectStore(project).read_records()
    assert records["shared"].version == "1.0.0"  # honored the lockfile, did not re-resolve


def test_install_reresolves_when_lockfile_is_stale(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}, "extra": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "1.0.0")
    assert _run(project, registry_dir, "install") == 0

    # Add a new direct dependency: the lockfile no longer satisfies the manifest.
    add_dependency(project, "extra", "1.0.0")
    assert _run(project, registry_dir, "install") == 0

    records = ProjectStore(project).read_records()
    assert set(records) == {"shared", "extra"}
    assert "extra" in load_lockfile(project).packages


def test_installed_record_path_is_posix(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "1.0.0")
    assert _run(project, registry_dir, "install") == 0

    record = ProjectStore(project).read_records()["shared"]
    assert record.path == "store/shared/1.0.0"
    assert "\\" not in record.path


def test_verify_reports_registry_tamper_without_load_failure(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "shared", "1.0.0")
    assert _run(project, registry_dir, "install") == 0

    archive = registry_dir / "archives" / "shared-1.0.0.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"tamper")

    # Full validation refuses to load; structural load succeeds so verify can report it.
    with pytest.raises(RegistryValidationError, match="archive hash mismatch"):
        LocalRegistry(registry_dir)

    structural = LocalRegistry(registry_dir, verify_archives=False)
    ok, messages = verify_project(project, structural)
    assert not ok
    assert any("registry archive verification failed" in message for message in messages)


def test_locked_install_is_deterministic(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry(
        {"alpha": {"1.0.0": {"shared": ">=1.0.0,<2.0.0"}}, "shared": {"1.0.0": {}}}
    )
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    resolution = Resolver(registry).resolve(load_manifest(project).requirements())
    lockfile = Lockfile.from_graph(resolution.graph)
    write_lockfile(project, lockfile)

    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    install_from_lockfile(project_a, lockfile, registry)
    install_from_lockfile(project_b, lockfile, registry)

    records_a = {name: record.to_dict() for name, record in ProjectStore(project_a).read_records().items()}
    records_b = {name: record.to_dict() for name, record in ProjectStore(project_b).read_records().items()}
    assert records_a == records_b
