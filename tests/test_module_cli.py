"""Exhaustive CLI command and main() tests."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab import __version__, cli
from pypm_lab.conflicts import Conflict
from pypm_lab.errors import PyPMError, RegistryValidationError
from pypm_lab.manifest import init_manifest, load_manifest
from pypm_lab.resolver import ResolutionFailed


def _run(project: Path, registry: Path, *args: str) -> int:
    return cli.main(["--project-dir", str(project), "--registry", str(registry), *args])


def test_cli_main_module_entrypoint():
    result = subprocess.run(
        [sys.executable, "-m", "pypm_lab", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_cli_main_name_main():
    with pytest.raises(SystemExit):
        cli.main(["--version"])


def test_cli_add_with_combined_requirement(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "add", "alpha@^1.0.0") == 0
    assert load_manifest(project).dependencies["alpha"] == "^1.0.0"


def test_cli_resolve_with_trace(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"shared": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "shared", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve", "--trace") == 0
    assert "initial direct dependencies" in capsys.readouterr().out


def test_cli_list_empty_project(tmp_path, capsys):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "list") == 0
    assert "no packages installed" in capsys.readouterr().out


def test_cli_why_missing_package(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0
    assert _run(project, registry_dir, "why", "ghost") == 1
    assert "not present" in capsys.readouterr().out


def test_cli_why_all_paths(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry(
        {
            "alpha": {"1.0.0": {"shared": "1.0.0"}},
            "bravo": {"1.0.0": {"shared": "1.0.0"}},
            "shared": {"1.0.0": {}},
        }
    )
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "add", "bravo", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    assert _run(project, registry_dir, "why", "shared", "--all") == 0
    assert capsys.readouterr().out.count("->") >= 2


def test_cli_graph_dot_format(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0
    assert _run(project, registry_dir, "graph", "--format", "dot") == 0
    assert "digraph" in capsys.readouterr().out


def test_cli_outdated_up_to_date(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "outdated") == 0
    assert "all packages are up to date" in capsys.readouterr().out


def test_cli_outdated_reports_newer_versions(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}, "2.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "outdated") == 0
    assert "1.0.0 -> 2.0.0" in capsys.readouterr().out


def test_cli_clean_nothing_to_clean(tmp_path, capsys):
    project = tmp_path / "project"
    registry = tmp_path / "registry"
    assert _run(project, registry, "init") == 0
    assert _run(project, registry, "clean") == 0
    assert "nothing to clean" in capsys.readouterr().out


def test_cli_clean_dry_run(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    orphan = project / ".pypm" / "store" / "orphan" / "1.0.0"
    orphan.mkdir(parents=True)
    (orphan / "file.txt").write_text("x", encoding="utf-8")
    capsys.readouterr()
    assert _run(project, registry_dir, "clean", "--dry-run") == 0
    assert "would remove" in capsys.readouterr().out


def test_cli_update_success(tmp_path, build_registry: Callable[..., Path], capsys):
    registry_dir = build_registry({"alpha": {"1.0.0": {}, "1.1.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "^1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "update") == 0
    assert "installed alpha@1.1.0" in capsys.readouterr().out


def test_cli_sync_note_when_manifest_changes(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    assert _run(project, registry_dir, "init") == 0
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "add", "bravo", "1.0.0") == 0
    assert "sync lockfile" in capsys.readouterr().err


def test_cli_resolve_store_note_on_version_mismatch(
    tmp_path, build_registry: Callable[..., Path], capsys
):
    registry_dir = build_registry({"alpha": {"1.0.0": {}, "1.1.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    assert _run(project, registry_dir, "add", "alpha", "1.0.0") == 0
    assert _run(project, registry_dir, "install") == 0
    capsys.readouterr()
    assert _run(project, registry_dir, "add", "alpha", "^1.0.0") == 0
    assert _run(project, registry_dir, "resolve") == 0
    assert "sync .pypm/" in capsys.readouterr().err


def test_cli_absolute_registry_path(tmp_path, build_registry: Callable[..., Path]):
    registry_dir = build_registry({"alpha": {"1.0.0": {}}})
    project = tmp_path / "project"
    init_manifest(project)
    code = cli.main(
        [
            "--project-dir",
            str(project),
            "--registry",
            str(registry_dir.resolve()),
            "add",
            "alpha",
            "1.0.0",
        ]
    )
    assert code == 0


def test_main_handles_resolution_failed(capsys):
    conflict = Conflict(
        package="alpha",
        constraints=(),
        attempted=(),
        message="Could not resolve alpha.",
    )

    with mock.patch.object(cli, "_cmd_resolve", side_effect=ResolutionFailed(conflict)):
        assert cli.main(["resolve"]) == 1
    assert "Could not resolve alpha." in capsys.readouterr().err


def test_main_handles_registry_validation_error(capsys):
    with mock.patch.object(
        cli,
        "_cmd_verify",
        side_effect=RegistryValidationError(["registry index invalid"]),
    ):
        assert cli.main(["verify"]) == 1
    assert "registry index invalid" in capsys.readouterr().err


def test_main_handles_pypm_error(capsys):
    with mock.patch.object(cli, "_cmd_list", side_effect=PyPMError("boom")):
        assert cli.main(["list"]) == 1
    assert "error: boom" in capsys.readouterr().err
