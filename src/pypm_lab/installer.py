"""Install resolved package graphs into the project-local store."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import InstallError, IntegrityError
from .graph import topological_sort
from .integrity import hash_directory, parse_integrity, verify_integrity
from .lockfile import Lockfile
from .models import InstallPlan, PackageVersion, ResolvedGraph, ResolvedPackage, StoreRecord
from .resolver import RegistryReader
from .store import ProjectStore
from .tar_safe import safe_extractall
from .versions import Version


@dataclass(frozen=True)
class InstallReport:
    installed: tuple[str, ...]
    reused_cache: tuple[str, ...]
    plan: InstallPlan
    pruned: tuple[str, ...] = ()


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
    previous_records = store.read_records()
    records = dict(previous_records)
    installed: list[str] = []
    reused_cache: list[str] = []
    rollback: list[tuple[str, StoreRecord | None, Version]] = []
    new_cache_files: list[Path] = []

    order = topological_sort(graph)
    plan = InstallPlan(order=tuple(order))
    try:
        for name in order:
            if name not in graph.packages:
                raise InstallError(f"resolved graph references missing package {name}")
            resolved = graph.packages[name]
            package_version = registry.get_package_version(name, resolved.version)
            if package_version.integrity.lower() != resolved.integrity.lower():
                raise IntegrityError(
                    f"resolved integrity for {resolved.identifier} does not match registry"
                )
            rollback.append((name, previous_records.get(name), resolved.version))
            cache_path, reused = _cache_archive(store, package_version)
            if not reused:
                new_cache_files.append(cache_path)
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
            installed.append(resolved.identifier)

        keep = set(graph.packages)
        orphans = {name: records.pop(name) for name in sorted(set(records) - keep)}
        store.write_records(records)
        pruned = _delete_orphan_directories(store, orphans)
    except Exception as exc:
        try:
            _rollback_install(store, registry, rollback, new_cache_files, previous_records)
        except InstallError as rollback_exc:
            raise InstallError(f"{exc}\n{rollback_exc}") from exc
        raise

    return InstallReport(
        installed=tuple(installed),
        reused_cache=tuple(reused_cache),
        plan=plan,
        pruned=tuple(pruned),
    )


def _rollback_install(
    store: ProjectStore,
    registry: RegistryReader,
    rollback: list[tuple[str, StoreRecord | None, Version]],
    new_cache_files: list[Path],
    previous_records: dict[str, StoreRecord],
) -> None:
    """Restore the pre-install store view after a failed graph install."""

    restore_errors: list[str] = []
    cache_to_review = list(new_cache_files)
    try:
        for name, previous, attempted_version in reversed(rollback):
            try:
                if previous is None:
                    attempted_dir = store.package_dir(name, str(attempted_version))
                    shutil.rmtree(attempted_dir, ignore_errors=True)
                    parent = attempted_dir.parent
                    if parent != store.store_dir and parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                else:
                    package_version = registry.get_package_version(name, Version.parse(previous.version))
                    cache_path, reused = _cache_archive(store, package_version)
                    if not reused:
                        cache_to_review.append(cache_path)
                    _place_package(store, package_version, cache_path)
            except Exception as exc:  # noqa: BLE001 - collect every rollback failure.
                restore_errors.append(f"{name}: {exc}")

        kept_digests = {parse_integrity(record.integrity) for record in previous_records.values()}
        for cache_path in cache_to_review:
            digest = cache_path.name.removesuffix(".tar.gz")
            if digest not in kept_digests and cache_path.exists():
                cache_path.unlink(missing_ok=True)
    finally:
        try:
            store.write_records(previous_records)
        except Exception as exc:  # noqa: BLE001
            restore_errors.append(f"installed.json: {exc}")

    if restore_errors:
        lines = "\n".join(f"  - {error}" for error in restore_errors)
        raise InstallError(f"install rollback incomplete:\n{lines}")


def _delete_orphan_directories(
    store: ProjectStore,
    orphans: dict[str, StoreRecord],
) -> list[str]:
    """Remove on-disk package directories dropped from the resolved graph."""

    removed: list[str] = []
    for name, record in sorted(orphans.items()):
        package_dir = store.root / record.path
        shutil.rmtree(package_dir, ignore_errors=True)
        parent = package_dir.parent
        if parent != store.store_dir and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        removed.append(f"{name}@{record.version}")
    return removed


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
        safe_extractall(cache_path, extract_dir)
        source = _archive_content_root(extract_dir)
        shutil.move(str(source), placement_dir)
        _replace_directory(placement_dir, final_dir, store.tmp_dir)
        return final_dir
    except Exception:
        shutil.rmtree(placement_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


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
