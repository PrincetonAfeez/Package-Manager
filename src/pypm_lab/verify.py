"""Project verification command support."""

from __future__ import annotations

from pathlib import Path

from .constraints import VersionConstraint
from .errors import ConstraintError
from .integrity import hash_directory, verify_integrity
from .lockfile import Lockfile, load_lockfile
from .manifest import Manifest, load_manifest, manifest_path
from .resolver import RegistryReader
from .store import ProjectStore


def check_lockfile_consistency(lockfile: Lockfile) -> list[str]:
    """Return problems if the locked graph is not internally consistent.

    Every dependency constraint recorded in the lockfile must be satisfied by the
    version the lockfile pins for that dependency. A lockfile produced by the
    resolver always satisfies this; the check catches a hand-edited or corrupted
    lockfile whose pinned versions contradict its own dependency edges.
    """

    problems: list[str] = []
    for name, locked in sorted(lockfile.packages.items()):
        for dep_name, raw_constraint in sorted(locked.dependencies.items()):
            dependency = lockfile.packages.get(dep_name)
            if dependency is None:
                problems.append(f"{name}: dependency {dep_name} is not in the lockfile")
                continue
            try:
                constraint = VersionConstraint.parse(raw_constraint)
            except ConstraintError as exc:
                problems.append(f"{name}: invalid constraint for {dep_name}: {exc}")
                continue
            if not constraint.allows(dependency.version):
                problems.append(
                    f"{name}: requires {dep_name} {raw_constraint} "
                    f"but lockfile pins {dep_name}@{dependency.version}"
                )
    return problems


def check_manifest_lockfile_alignment(manifest: Manifest, lockfile: Lockfile) -> list[str]:
    """Return problems when direct manifest requirements disagree with the lockfile."""

    problems: list[str] = []
    requirements = manifest.requirements()
    manifest_roots = {requirement.name for requirement in requirements}
    lock_roots = set(lockfile.roots)
    if manifest_roots != lock_roots:
        problems.append(
            "manifest direct dependencies do not match lockfile roots: "
            f"manifest={sorted(manifest_roots)}, lockfile={sorted(lock_roots)}"
        )
    for requirement in requirements:
        locked = lockfile.packages.get(requirement.name)
        if locked is None:
            problems.append(f"{requirement.name}: required by manifest but missing from lockfile")
            continue
        if not requirement.constraint.allows(locked.version):
            problems.append(
                f"{requirement.name}: manifest requires {requirement.raw_constraint} "
                f"but lockfile pins {requirement.name}@{locked.version}"
            )
    return problems


def check_lockfile_reachability(lockfile: Lockfile) -> list[str]:
    """Return problems for lockfile packages not reachable from ``roots``."""

    reachable: set[str] = set()
    pending = list(lockfile.roots)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        if name not in lockfile.packages:
            continue
        reachable.add(name)
        pending.extend(sorted(lockfile.packages[name].dependencies))
    return [
        f"{name}: lockfile package is not reachable from roots"
        for name in sorted(set(lockfile.packages) - reachable)
    ]


def verify_project(project_dir: Path | str, registry: RegistryReader) -> tuple[bool, tuple[str, ...]]:
    messages: list[str] = []
    ok = True
    lockfile = load_lockfile(project_dir)
    store = ProjectStore(project_dir)
    records = store.read_records()

    if manifest_path(project_dir).exists():
        for problem in check_manifest_lockfile_alignment(load_manifest(project_dir), lockfile):
            ok = False
            messages.append(problem)

    for problem in check_lockfile_reachability(lockfile):
        ok = False
        messages.append(problem)

    for problem in check_lockfile_consistency(lockfile):
        ok = False
        messages.append(problem)

    for name, locked in sorted(lockfile.packages.items()):
        try:
            registry_package = registry.get_package_version(name, locked.version)
            if registry_package.integrity.lower() != locked.integrity.lower():
                ok = False
                messages.append(f"{name}@{locked.version}: registry integrity differs from lockfile")
            registry_dependencies = dict(sorted(registry_package.dependencies.items()))
            lock_dependencies = dict(sorted(locked.dependencies.items()))
            if registry_dependencies != lock_dependencies:
                ok = False
                messages.append(
                    f"{name}@{locked.version}: lockfile dependencies disagree with registry"
                )
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
