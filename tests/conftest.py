"""Shared pytest fixtures for building inert archives and local registries."""

from __future__ import annotations

import json
import logging
import tarfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from pypm_lab.publish import publish_archive


@pytest.fixture
def pypm_caplog(caplog):
    with caplog.at_level(logging.INFO, logger="pypm_lab"):
        yield caplog


def _write_archive(
    tmp_path: Path,
    name: str,
    version: str,
    dependencies: Mapping[str, str] | None,
    extra_files: Mapping[str, str] | None,
) -> Path:
    dependencies = dependencies or {}
    build_root = tmp_path / "build" / f"{name}-{version}"
    (build_root / "src").mkdir(parents=True, exist_ok=True)
    (build_root / "package.json").write_text(
        json.dumps({"name": name, "version": version, "dependencies": dict(dependencies)}),
        encoding="utf-8",
    )
    (build_root / "src" / f"{name}.txt").write_text(f"{name} {version}", encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        target = build_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    archive_path = tmp_path / f"{name}-{version}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(build_root, arcname=f"{name}-{version}")
    return archive_path


@pytest.fixture
def make_archive(tmp_path: Path) -> Callable[..., Path]:
    """Return a builder that writes an inert `name-version.tar.gz` archive."""

    def _make(
        name: str,
        version: str,
        dependencies: Mapping[str, str] | None = None,
        *,
        extra_files: Mapping[str, str] | None = None,
    ) -> Path:
        return _write_archive(tmp_path, name, version, dependencies, extra_files)

    return _make


@pytest.fixture
def build_registry(tmp_path: Path, make_archive: Callable[..., Path]) -> Callable[..., Path]:
    """Return a builder that publishes a package universe into a local registry.

    The universe is described as ``{name: {version: {dependency: constraint}}}``.
    """

    def _build(universe: Mapping[str, Mapping[str, Mapping[str, str]]]) -> Path:
        registry_dir = tmp_path / "registry"
        for name, versions in universe.items():
            for version, dependencies in versions.items():
                archive = make_archive(name, version, dependencies)
                publish_archive(registry_dir, archive)
        return registry_dir

    return _build
