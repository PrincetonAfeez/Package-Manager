"""CLI integration tests for command wiring, exit codes, and install output."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pypm_lab import cli
from pypm_lab.lockfile import load_lockfile
from pypm_lab.manifest import init_manifest, load_manifest


def _run(project: Path, registry: Path, *args: str) -> int:
    return cli.main(["--project-dir", str(project), "--registry", str(registry), *args])


def test_main_without_subcommand_returns_usage_exit_code(capsys):
    assert cli.main([]) == 2
    assert "usage:" in capsys.readouterr().out.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "pypm" in capsys.readouterr().out


def test_init_add_remove_list(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert (project / "package.json").exists()
    assert _run(project, registry, "add", "alpha", "^1.0.0") == 0
    assert load_manifest(project).dependencies["alpha"] == "^1.0.0"
    assert _run(project, registry, "remove", "alpha") == 0
    assert load_manifest(project).dependencies == {}


def test_add_wildcard_constraint(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "add", "alpha", "*") == 0
    assert load_manifest(project).dependencies["alpha"] == "*"


def test_publish_install_locked_tree_graph_verify(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0
    assert _run(project, registry_dir, "install", "--locked") == 0
    assert _run(project, registry_dir, "list") == 0
    assert "shared@1.0.0" in capsys.readouterr().out
    assert _run(project, registry_dir, "tree") == 0
    assert "shared@1.0.0" in capsys.readouterr().out
    assert _run(project, registry_dir, "graph", "--format", "json") == 0
    assert "shared" in capsys.readouterr().out
    assert _run(project, registry_dir, "verify") == 0


def test_update_writes_lockfile_only_after_successful_install(
    tmp_path, build_registry: Callable[..., Path]
):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    original = load_lockfile(project).dumps()

    index_path = registry_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["packages"]["shared"]["versions"]["1.0.0"]["integrity"] = "sha256:" + "f" * 64
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    assert _run(project, registry_dir, "update") == 1
    assert load_lockfile(project).dumps() == original


def test_install_reresolve_writes_lockfile_only_after_success(
    tmp_path, build_registry: Callable[..., Path]
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "beta": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    original = load_lockfile(project).dumps()

    assert _run(project, registry_dir, "add", "beta", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    assert load_lockfile(project).dumps() != original


def test_reused_cache_is_reported(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "install") == 0
    out = capsys.readouterr().out
    assert "reused cache shared@1.0.0" in out


def test_outdated_strict_exits_nonzero(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0

    index_path = registry_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["packages"]["shared"]
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    capsys.readouterr()
    assert _run(project, registry_dir, "outdated", "--strict") == 1


def test_resolve_warns_when_store_is_out_of_sync(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0
    err = capsys.readouterr().err
    assert "run `pypm install`" in err


def test_publish_via_cli(tmp_path, make_archive: Callable[..., Path], capsys):
    registry = tmp_path / "registry"
    archive = make_archive("widget", "1.0.0")
    assert _run(tmp_path / "project", registry, "init") == 0
    assert _run(tmp_path / "project", registry, "publish", str(archive)) == 0
    assert "published widget@1.0.0" in capsys.readouterr().out


def test_install_locked_missing_lockfile(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "install", "--locked") == 1


def test_install_locked_rejects_malformed_dependency_constraint(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0

    lock_path = project / "pypm-lock.json"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["packages"]["shared"]["dependencies"] = {"ghost": ">>>"}
    lock_data["packages"]["ghost"] = {
        "version": "1.0.0",
        "integrity": "sha256:" + "0" * 64,
        "dependencies": {},
    }
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")

    assert _run(project, registry_dir, "install", "--locked") == 1
    err = capsys.readouterr().err
    assert "invalid constraint" in err


def test_remove_makes_verify_fail_until_install(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}, "bravo": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "add", "bravo", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    assert _run(project, registry_dir, "remove", "bravo") == 0
    assert _run(project, registry_dir, "verify") == 1


def test_main_module_exits_without_subcommand():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pypm_lab"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_outdated_reports_missing_registry_package(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0

    index_path = registry_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["packages"]["shared"]
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    capsys.readouterr()
    assert _run(project, registry_dir, "outdated") == 0
    assert "missing from registry" in capsys.readouterr().out
