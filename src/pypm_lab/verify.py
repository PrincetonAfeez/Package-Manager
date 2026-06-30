"""Project verification command support."""

from __future__ import annotations

from pathlib import Path

from .integrity import hash_directory, verify_integrity
from .lockfile import load_lockfile
from .resolver import RegistryReader
from .store import ProjectStore


def verify_project(project_dir: Path | str, registry: RegistryReader) -> tuple[bool, tuple[str, ...]]:
    messages: list[str] = []
    ok = True
    lockfile = load_lockfile(project_dir)
    store = ProjectStore(project_dir)
    records = store.read_records()

    for name, locked in sorted(lockfile.packages.items()):
        try:
            registry_package = registry.get_package_version(name, locked.version)
            if registry_package.integrity.lower() != locked.integrity.lower():
                ok = False
                messages.append(f"{name}@{locked.version}: registry integrity differs from lockfile")
            verify_integrity(registry_package.archive, locked.integrity)
        except Exception as exc:  # noqa: BLE001 - verification reports all failures it can.
            ok = False
            messages.append(f"{name}@{locked.version}: registry archive verification failed: {exc}")

        record = records.get(name)
        if record is None:
            ok = False
            messages.append(f"{name}@{locked.version}: missing installed record")
            continue
        if record.version != str(locked.version):
            ok = False
            messages.append(f"{name}: installed version {record.version} differs from lockfile {locked.version}")
        if record.integrity.lower() != locked.integrity.lower():
            ok = False
            messages.append(f"{name}: installed integrity differs from lockfile")
        installed_path = store.root / record.path
        if not installed_path.exists():
            ok = False
            messages.append(f"{name}@{locked.version}: missing installed package directory")
            continue
        try:
            actual_tree_hash = hash_directory(installed_path)
            if actual_tree_hash.lower() != record.tree_hash.lower():
                ok = False
                messages.append(f"{name}@{locked.version}: installed contents were modified")
        except Exception as exc:  # noqa: BLE001
            ok = False
            messages.append(f"{name}@{locked.version}: cannot verify installed contents: {exc}")

    for name in sorted(set(records) - set(lockfile.packages)):
        ok = False
        messages.append(f"{name}: installed but not present in lockfile")

    if ok:
        messages.append("verification passed")
    return ok, tuple(messages)
