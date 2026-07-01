"""Round 3 polish: error-path coverage, CLI exceptions, and edge-case hardening."""

from __future__ import annotations

import json
import tarfile
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab import cli
from pypm_lab.constraints import VersionConstraint
from pypm_lab.errors import (
    ConstraintError,
    InstallError,
    RegistryError,
    RegistryValidationError,
)
from pypm_lab.fsio import atomic_write_text
from pypm_lab.installer import install_resolved
from pypm_lab.lockfile import Lockfile, LockPackage, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.publish import publish_archive
from pypm_lab.registry import LocalRegistry
from pypm_lab.registry_validation import load_json_no_duplicates, validate_registry
from pypm_lab.resolver import ResolutionFailed, Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.tar_safe import read_archive_manifest, safe_extractall, validate_members
from pypm_lab.verify import (
    check_lockfile_consistency,
    check_lockfile_reachability,
    check_manifest_lockfile_alignment,
    verify_project,
)
from pypm_lab.versions import Version


def _run(project: Path, registry: Path, *args: str) -> int:
    return cli.main(["--project-dir", str(project), "--registry", str(registry), *args])


def test_add_remove_print_sync_note_when_lockfile_is_stale(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "add", "bravo", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()

    assert _run(project, registry_dir, "remove", "bravo") == 0
    err = capsys.readouterr().err
    assert "sync lockfile and .pypm/" in err


def test_add_does_not_print_sync_note_without_lockfile(tmp_path, capsys):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "add", "alpha", "^1.0.0") == 0
    assert capsys.readouterr().err == ""


def test_init_with_custom_name(tmp_path, capsys):
    project = tmp_path / "my-app"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init", "--name", "custom-app") == 0
    assert load_manifest(project).name == "custom-app"
    assert "initialized" in capsys.readouterr().out


def test_cli_resolution_failed_exit_code(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {"ghost": ">=1.0.0"}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    assert _run(project, registry_dir, "resolve") == 1
    err = capsys.readouterr().err
    assert "ghost" in err.lower() or "missing" in err.lower()


def test_cli_registry_validation_error_exit_code(tmp_path, capsys):
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "index.json").write_text('{"packages": {"alpha": {}}}', encoding="utf-8")
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    assert _run(project, registry, "resolve") == 1
    assert capsys.readouterr().err


def test_cli_pypm_error_exit_code(tmp_path, capsys):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "add", "alpha", "1.0.0") == 1
    assert "error:" in capsys.readouterr().err


def test_cli_remove_unknown_dependency(tmp_path, capsys):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "remove", "missing") == 1
    assert "error:" in capsys.readouterr().err


def test_constraint_empty_and_malformed():
    with pytest.raises(ConstraintError, match="missing version constraint"):
        VersionConstraint.parse("")
    with pytest.raises(ConstraintError, match="empty comparator"):
        VersionConstraint.parse(">=1.0.0,")
    with pytest.raises(ConstraintError, match="malformed comparator"):
        VersionConstraint.parse(">>1.0.0")
    with pytest.raises(ConstraintError, match="malformed version"):
        VersionConstraint.parse("^not-a-version")


def test_comparator_unsupported_op():
    from pypm_lab.constraints import Comparator

    broken = Comparator(">=", Version.parse("1.0.0"))
    object.__setattr__(broken, "op", "???")
    with pytest.raises(ConstraintError, match="unsupported comparator"):
        broken.allows(Version.parse("1.0.0"))


def test_atomic_write_text_cleans_up_temp_file_on_failure(tmp_path):
    target = tmp_path / "out.txt"
    with mock.patch("pypm_lab.fsio.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            atomic_write_text(target, "payload")
    assert not target.exists()
    assert list(tmp_path.glob("out.txt.*.tmp")) == []


def test_load_json_no_duplicates_reports_read_failure(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(RegistryValidationError, match="cannot read"):
        load_json_no_duplicates(missing)


def test_validate_registry_missing_index(tmp_path):
    with pytest.raises(RegistryValidationError, match="missing registry index"):
        validate_registry(tmp_path / "empty")


def test_validate_registry_duplicate_normalized_names(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    from pypm_lab.integrity import integrity_for_file

    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    index = {
        "packages": {
            "Alpha": {"versions": {"1.0.0": entry}},
            "alpha": {"versions": {"1.0.0": entry}},
        }
    }
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="duplicate package name after normalization"):
        validate_registry(registry)


def test_validate_registry_non_object_package_entry(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    index = {"packages": {"alpha": []}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="package entry must be an object"):
        validate_registry(registry, verify_archives=False)


def test_validate_registry_duplicate_version_key(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    raw = '{"packages": {"alpha": {"versions": {"1.0.0": {}, "1.0.0": {}}}}}'
    (registry / "index.json").write_text(raw, encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="duplicate key"):
        validate_registry(registry, verify_archives=False)


def test_validate_registry_non_object_version_entry(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    index = {"packages": {"alpha": {"versions": {"1.0.0": []}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="version entry must be an object"):
        validate_registry(registry, verify_archives=False)


def test_validate_registry_non_string_dependency_constraint(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    from pypm_lab.integrity import integrity_for_file

    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {"shared": 123},
    }
    index = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="constraint must be a string"):
        validate_registry(registry, verify_archives=False)


def test_validate_registry_missing_archive_file(tmp_path):
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    index = {
        "packages": {
            "alpha": {
                "versions": {
                    "1.0.0": {
                        "archive": "archives/missing.tar.gz",
                        "integrity": "sha256:" + "0" * 64,
                        "dependencies": {},
                    }
                }
            }
        }
    }
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="archive does not exist"):
        validate_registry(registry, verify_archives=False)


def test_validate_registry_archive_metadata_version_mismatch(
    tmp_path, make_archive: Callable[..., Path]
):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    from pypm_lab.integrity import integrity_for_file

    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    index = {"packages": {"alpha": {"versions": {"9.9.9": entry}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="archive metadata version"):
        validate_registry(registry)


def test_validate_registry_archive_dependency_disagreement(
    tmp_path, make_archive: Callable[..., Path]
):
    archive = make_archive("alpha", "1.0.0", {"shared": ">=1.0.0"})
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    from pypm_lab.integrity import integrity_for_file

    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    index = {"packages": {"alpha": {"versions": {"1.0.0": entry}}}}
    (registry / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="dependencies disagree"):
        validate_registry(registry)


def test_read_archive_manifest_missing_package_json(tmp_path):
    archive_path = tmp_path / "empty.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo(name="readme.txt"))
    with pytest.raises(RegistryValidationError, match="missing package.json"):
        read_archive_manifest(archive_path)


def test_read_archive_manifest_non_object_json(tmp_path, make_archive: Callable[..., Path]):
    import io

    archive = make_archive("alpha", "1.0.0")
    with mock.patch.object(
        tarfile.TarFile,
        "extractfile",
        return_value=io.BytesIO(b"[]"),
    ):
        with pytest.raises(RegistryValidationError, match="must be an object"):
            read_archive_manifest(archive)


def test_read_archive_manifest_corrupt_tar(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not a tar archive")
    with pytest.raises(RegistryValidationError, match="cannot read archive"):
        read_archive_manifest(bad)


def test_safe_extractall_rejects_path_escape(tmp_path):
    import io

    evil = tmp_path / "evil.tar.gz"
    payload = b'{"name":"alpha","version":"1.0.0","dependencies":{}}'
    with tarfile.open(evil, "w:gz") as archive_file:
        info = tarfile.TarInfo(name="../escape/package.json")
        info.size = len(payload)
        archive_file.addfile(info, fileobj=io.BytesIO(payload))
    with pytest.raises(InstallError, match="escapes install root"):
        safe_extractall(evil, tmp_path / "dest")


def test_validate_members_size_cap(tmp_path, make_archive: Callable[..., Path]):
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = make_archive("alpha", "1.0.0")
    with tarfile.open(archive_path, "r:gz") as archive:
        member = tarfile.TarInfo(name="big.bin")
        member.size = 9999
        with mock.patch.object(archive, "getmembers", return_value=[member]):
            with pytest.raises(InstallError, match="extraction size limit"):
                validate_members(archive, destination, max_total_bytes=1024)


def test_publish_missing_archive(tmp_path):
    with pytest.raises(RegistryError, match="archive does not exist"):
        publish_archive(tmp_path / "registry", tmp_path / "missing.tar.gz")


def test_publish_duplicate_version(tmp_path, make_archive: Callable[..., Path]):
    registry = tmp_path / "registry"
    archive = make_archive("alpha", "1.0.0")
    publish_archive(registry, archive)
    with pytest.raises(RegistryError, match="already exists"):
        publish_archive(registry, archive)


def test_publish_non_object_dependencies(tmp_path, make_archive: Callable[..., Path]):
    build_root = tmp_path / "build" / "alpha-1.0.0"
    build_root.mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps({"name": "alpha", "version": "1.0.0", "dependencies": []}),
        encoding="utf-8",
    )
    archive = tmp_path / "alpha-1.0.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(build_root, arcname="alpha-1.0.0")
    with pytest.raises(RegistryError, match="dependencies must be an object"):
        publish_archive(tmp_path / "registry", archive)


def test_publish_rolls_back_on_validation_failure(tmp_path, make_archive: Callable[..., Path], monkeypatch):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"

    def fail_validation(*args, **kwargs):
        raise RegistryValidationError(["simulated validation failure"])

    monkeypatch.setattr("pypm_lab.publish.validate_new_entry", fail_validation)
    with pytest.raises(RegistryValidationError, match="simulated validation failure"):
        publish_archive(registry, archive)
    assert not (registry / "archives" / archive.name).exists()


def test_check_lockfile_consistency_invalid_constraint():
    digest = "sha256:" + "0" * 64
    lockfile = Lockfile(
        packages={
            "alpha": LockPackage(Version.parse("1.0.0"), digest, {"shared": ">>1.0.0"}),
            "shared": LockPackage(Version.parse("1.0.0"), digest, {}),
        },
        roots=("alpha",),
    )
    problems = check_lockfile_consistency(lockfile)
    assert any("invalid constraint" in problem for problem in problems)


def test_check_lockfile_consistency_missing_dependency():
    digest = "sha256:" + "0" * 64
    lockfile = Lockfile(
        packages={
            "alpha": LockPackage(Version.parse("1.0.0"), digest, {"ghost": ">=1.0.0"}),
        },
        roots=("alpha",),
    )
    problems = check_lockfile_consistency(lockfile)
    assert any("ghost" in problem and "not in the lockfile" in problem for problem in problems)


def test_check_lockfile_consistency_unsatisfied_constraint():
    digest = "sha256:" + "0" * 64
    lockfile = Lockfile(
        packages={
            "alpha": LockPackage(Version.parse("1.0.0"), digest, {"shared": ">=2.0.0"}),
            "shared": LockPackage(Version.parse("1.0.0"), digest, {}),
        },
        roots=("alpha",),
    )
    problems = check_lockfile_consistency(lockfile)
    assert any("requires shared" in problem for problem in problems)


def test_check_manifest_lockfile_alignment_root_mismatch():
    from pypm_lab.manifest import Manifest

    digest = "sha256:" + "0" * 64
    manifest = Manifest(name="demo", dependencies={"alpha": "1.0.0"})
    lockfile = Lockfile(
        packages={"alpha": LockPackage(Version.parse("1.0.0"), digest, {})},
        roots=("beta",),
    )
    problems = check_manifest_lockfile_alignment(manifest, lockfile)
    assert any("do not match lockfile roots" in problem for problem in problems)


def test_verify_orphan_installed_record(tmp_path, build_registry: Callable[..., Path]):
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
    records["ghost"] = alpha.__class__(
        name="ghost",
        version="1.0.0",
        integrity=alpha.integrity,
        tree_hash=alpha.tree_hash,
        path="store/ghost/1.0.0",
    )
    store.package_dir("ghost", "1.0.0").mkdir(parents=True)
    store.write_records(records)

    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("ghost" in message and "not present in lockfile" in message for message in messages)


def test_verify_modified_installed_contents(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    add_dependency(project, "alpha", "1.0.0")
    registry = LocalRegistry(registry_dir)
    graph = Resolver(registry).resolve(load_manifest(project).requirements()).graph
    install_resolved(project, graph, registry)
    write_lockfile(project, Lockfile.from_graph(graph))

    installed = project / ".pypm" / "store" / "alpha" / "1.0.0" / "src" / "alpha.txt"
    installed.write_text("tampered", encoding="utf-8")

    ok, messages = verify_project(project, registry)
    assert not ok
    assert any("contents were modified" in message for message in messages)


def test_replace_directory_failure_restores_backup(tmp_path):
    from pypm_lab.installer import _replace_directory

    final = tmp_path / "final"
    final.mkdir()
    (final / "data.txt").write_text("old", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.txt").write_text("new", encoding="utf-8")
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()

    real_rename = Path.rename
    calls = {"n": 0}

    def tracked_rename(self, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("rename failed")
        return real_rename(self, target)

    with mock.patch.object(Path, "rename", tracked_rename):
        with pytest.raises(OSError, match="rename failed"):
            _replace_directory(source, final, tmp_root)

    assert final.exists()
    assert (final / "data.txt").read_text() == "old"


def test_resolution_failed_has_explainable_conflict():
    from pypm_lab.registry import InMemoryRegistry
    from pypm_lab.requirements import parse_requirement

    registry = InMemoryRegistry({"alpha": {"1.0.0": {}}})
    with pytest.raises(ResolutionFailed) as exc:
        Resolver(registry).resolve([parse_requirement("alpha@>=2.0.0")])
    assert "alpha" in exc.value.conflict.explain().lower()


@pytest.mark.parametrize(
    ("roots", "extra"),
    [
        (("alpha",), ("ghost",)),
        (("alpha", "beta"), ("alpha", "beta", "ghost")),
    ],
)
def test_lockfile_reachability_property(roots: tuple[str, ...], extra: tuple[str, ...]):
    digest = "sha256:" + "0" * 64
    packages = {
        name: LockPackage(Version.parse("1.0.0"), digest, {})
        for name in set(roots) | set(extra)
    }
    lockfile = Lockfile(packages=packages, roots=roots)
    unreachable = set(extra) - set(roots)
    problems = check_lockfile_reachability(lockfile)
    for name in sorted(unreachable):
        assert any(name in problem for problem in problems)
