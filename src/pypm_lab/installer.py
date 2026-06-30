"""Install resolved package graphs into the project-local store."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tarfile
import uuid

from .errors import InstallError, IntegrityError
from .graph import topological_sort
from .integrity import hash_directory, verify_integrity
from .lockfile import Lockfile
from .models import PackageVersion, ResolvedGraph, ResolvedPackage, StoreRecord
from .resolver import RegistryReader
from .store import ProjectStore


@dataclass(frozen=True)
class InstallReport:
    installed: tuple[str, ...]
    reused_cache: tuple[str, ...]


def graph_from_lockfile(lockfile: Lockfile, registry: RegistryReader) -> ResolvedGraph:
    packages: dict[str, ResolvedPackage] = {}
    for name, locked in sorted(lockfile.packages.items()):
        registry_package = registry.get_package_version(name, locked.version)
        if registry_package.integrity.lower() != locked.integrity.lower():
            raise IntegrityError(
                f"lockfile integrity for {name}@{locked.version} does not match registry"
            )
        packages[name] = ResolvedPackage(
            name=name,
            version=locked.version,
            dependencies=dict(sorted(locked.dependencies.items())),
            integrity=locked.integrity,
            archive=str(registry_package.archive),
        )
    return ResolvedGraph(packages=packages, roots=tuple(sorted(lockfile.roots)))


def install_resolved(
    project_dir: Path | str,
    graph: ResolvedGraph,
    registry: RegistryReader,
) -> InstallReport:
    store = ProjectStore(project_dir)
    store.ensure()
    records = store.read_records()
    installed: list[str] = []
    reused_cache: list[str] = []

    for name in topological_sort(graph):
        if name not in graph.packages:
            raise InstallError(f"resolved graph references missing package {name}")
        resolved = graph.packages[name]
        package_version = registry.get_package_version(name, resolved.version)
        if package_version.integrity.lower() != resolved.integrity.lower():
            raise IntegrityError(
                f"resolved integrity for {resolved.identifier} does not match registry"
            )
        cache_path, reused = _cache_archive(store, package_version)
        if reused:
            reused_cache.append(resolved.identifier)
        final_path = _place_package(store, package_version, cache_path)
        tree_hash = hash_directory(final_path)
        records[name] = StoreRecord(
            name=name,
            version=str(resolved.version),
            integrity=resolved.integrity,
            tree_hash=tree_hash,
            path=final_path.relative_to(store.root).as_posix(),
        )
        store.write_records(records)
        installed.append(resolved.identifier)

    return InstallReport(installed=tuple(installed), reused_cache=tuple(reused_cache))


def install_from_lockfile(
    project_dir: Path | str,
    lockfile: Lockfile,
    registry: RegistryReader,
) -> InstallReport:
    graph = graph_from_lockfile(lockfile, registry)
    return install_resolved(project_dir, graph, registry)


def _cache_archive(store: ProjectStore, package_version: PackageVersion) -> tuple[Path, bool]:
    archive_path = Path(package_version.archive)
    target = store.cache_path(package_version.integrity)
    if target.exists():
        verify_integrity(target, package_version.integrity)
        return target, True
    tmp = store.tmp_dir / f"cache-{uuid.uuid4().hex}.tar.gz"
    try:
        shutil.copy2(archive_path, tmp)
        verify_integrity(tmp, package_version.integrity)
        os.replace(tmp, target)
        return target, False
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _place_package(store: ProjectStore, package_version: PackageVersion, cache_path: Path) -> Path:
    name = package_version.name
    version = str(package_version.version)
    extract_dir = store.tmp_dir / f"extract-{name}-{version}-{uuid.uuid4().hex}"
    placement_dir = store.tmp_dir / f"place-{name}-{version}-{uuid.uuid4().hex}"
    final_dir = store.package_dir(name, version)
    extract_dir.mkdir(parents=True)
    try:
        _safe_extract(cache_path, extract_dir)
        source = _archive_content_root(extract_dir)
        shutil.move(str(source), placement_dir)
        _replace_directory(placement_dir, final_dir, store.tmp_dir)
        return final_dir
    except Exception:
        shutil.rmtree(placement_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _safe_extract(archive_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            destination_root = destination.resolve()
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                try:
                    target.relative_to(destination_root)
                except ValueError as exc:
                    raise InstallError(f"archive member escapes install root: {member.name}") from exc
            # `filter="data"` makes tarfile itself reject unsafe members (absolute
            # paths, traversal, escaping symlinks/hardlinks, device files) on every
            # supported Python version, not only 3.14 where it became the default.
            archive.extractall(destination, filter="data")
    except tarfile.TarError as exc:
        raise InstallError(f"cannot unpack archive {archive_path}: {exc}") from exc


def _archive_content_root(extract_dir: Path) -> Path:
    children = list(extract_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def _replace_directory(source: Path, final: Path, tmp_root: Path) -> None:
    final.parent.mkdir(parents=True, exist_ok=True)
    backup = tmp_root / f"backup-{final.name}-{uuid.uuid4().hex}"
    had_existing = final.exists()
    try:
        if had_existing:
            final.rename(backup)
        source.rename(final)
    except Exception:
        if final.exists() and not had_existing:
            shutil.rmtree(final, ignore_errors=True)
        if had_existing and backup.exists() and not final.exists():
            backup.rename(final)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)
