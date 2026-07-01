"""End-to-end workflow behavior: publish order, cycles, lockfile reuse, integrity."""

from collections.abc import Callable
from pathlib import Path

import pytest

from pypm_lab import cli
from pypm_lab.errors import RegistryValidationError
from pypm_lab.installer import install_from_lockfile, install_resolved
from pypm_lab.lockfile import Lockfile, LockPackage, load_lockfile, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest, remove_dependency
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
    locked = LockPackage(version=Version.parse("1.0.0"), integrity=pinned.integrity, dependencies={})
    write_lockfile(project, Lockfile(packages={"shared": locked}, roots=("shared",)))

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


def test_install_report_exposes_topological_plan(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry(
        {"alpha": {"1.0.0": {"shared": ">=1.0.0,<2.0.0"}}, "shared": {"1.0.0": {}}}
    )
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    resolution = Resolver(registry).resolve(load_manifest(project).requirements())

    report = install_resolved(project, resolution.graph, registry)

    # The plan records the topological install order: dependencies before dependents.
    assert report.plan.order == ("shared", "alpha")


def test_remove_then_install_prunes_orphan(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    add_dependency(project, "bravo", "1.0.0")
    assert _run(project, registry_dir, "install") == 0

    remove_dependency(project, "bravo")
    assert _run(project, registry_dir, "install") == 0

    records = ProjectStore(project).read_records()
    assert set(records) == {"alpha"}
    assert not (project / ".pypm" / "store" / "bravo").exists()
    assert _run(project, registry_dir, "verify") == 0  # no orphan -> verify is clean


def test_outdated_reports_capped_package(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"widget": {"1.0.0": {}, "2.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "widget", "~1.0.0")  # caps below the newer 2.0.0
    _run(project, registry_dir, "install")
    capsys.readouterr()

    assert _run(project, registry_dir, "outdated") == 0
    out = capsys.readouterr().out
    assert "widget: 1.0.0 -> 2.0.0" in out


def test_clean_prunes_unreferenced_cache(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    add_dependency(project, "bravo", "1.0.0")
    _run(project, registry_dir, "install")
    store = ProjectStore(project)
    assert len(list(store.cache_dir.glob("*.tar.gz"))) == 2

    remove_dependency(project, "bravo")
    _run(project, registry_dir, "install")  # prunes bravo's store + record, not its cache

    removed = store.clean()
    assert any("cache/sha256" in item for item in removed)
    assert len(list(store.cache_dir.glob("*.tar.gz"))) == 1


def test_why_all_shows_more_paths_than_default(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {"shared": ">=1.0.0"}}, "shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    add_dependency(project, "shared", "1.0.0")  # shared is both a root and a transitive dep
    _run(project, registry_dir, "install")

    capsys.readouterr()
    _run(project, registry_dir, "why", "shared")
    default_out = capsys.readouterr().out
    _run(project, registry_dir, "why", "shared", "--all")
    all_out = capsys.readouterr().out

    # Default shows only the shortest path (direct), --all also shows alpha -> shared.
    assert all_out.count("->") > default_out.count("->")


def test_clean_dry_run_previews_without_deleting(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    add_dependency(project, "bravo", "1.0.0")
    _run(project, registry_dir, "install")
    remove_dependency(project, "bravo")
    _run(project, registry_dir, "install")  # prunes bravo's store + record, keeps its cache
    store = ProjectStore(project)
    cache_before = sorted(store.cache_dir.glob("*.tar.gz"))

    preview = store.clean(dry_run=True)
    assert preview  # bravo's cache would be removed
    assert sorted(store.cache_dir.glob("*.tar.gz")) == cache_before  # nothing deleted

    removed = store.clean()  # real run removes the same set
    assert removed == preview
    assert len(list(store.cache_dir.glob("*.tar.gz"))) == len(cache_before) - 1


def test_readme_quickstart_example_archives_resolve(tmp_path):
    import importlib.util

    from pypm_lab.publish import publish_archive

    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "build_archives", repo_root / "examples" / "build_archives.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    archives = module.build_archives(tmp_path / "dist")
    assert {archive.name for archive in archives} >= {"shared-1.5.0.tar.gz", "alpha-1.2.4.tar.gz"}

    registry_dir = tmp_path / "registry"
    for archive in archives:
        publish_archive(registry_dir, archive)

    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "^1.2.0")
    registry = LocalRegistry(registry_dir)
    resolution = Resolver(registry).resolve(load_manifest(project).requirements())

    assert str(resolution.graph.packages["shared"].version) == "1.5.0"
    assert str(resolution.graph.packages["alpha"].version) == "1.2.4"
