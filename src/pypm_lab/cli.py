"""Command-line interface for PyPM Lab."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Callable, cast

from .errors import PyPMError, RegistryValidationError
from .graph import dependency_tree, export_graph, format_why, why_paths
from .installer import install_from_lockfile, install_resolved
from .lockfile import Lockfile, load_lockfile, lockfile_path, write_lockfile
from .manifest import (
    Manifest,
    add_dependency,
    init_manifest,
    load_manifest,
    remove_dependency,
)
from .publish import publish_archive
from .registry import LocalRegistry, init_registry
from .requirements import parse_requirement, parse_requirement_parts
from .resolver import Resolution, ResolutionFailed, Resolver
from .store import ProjectStore
from .verify import verify_project

Handler = Callable[[argparse.Namespace], int]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    handler = cast(Handler, args.handler)
    try:
        return handler(args)
    except ResolutionFailed as exc:
        print(exc.conflict.explain(), file=sys.stderr)
        return 1
    except RegistryValidationError as exc:
        print(exc, file=sys.stderr)
        return 1
    except PyPMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pypm", description="Educational local package manager.")
    parser.add_argument("--project-dir", default=".", help="Project directory (default: current directory).")
    parser.add_argument("--registry", default="registry", help="Registry path, relative to project unless absolute.")
    subparsers = parser.add_subparsers(dest="command")

    _command(subparsers, "init", "Initialize a project manifest, registry, and local store.", _cmd_init)

    add = _command(subparsers, "add", "Add a direct dependency.", _cmd_add)
    add.add_argument("package", help="Package name or requirement like alpha@^1.2.0")
    add.add_argument("constraint", nargs="?", help="Version constraint when package is separate.")

    remove = _command(subparsers, "remove", "Remove a direct dependency.", _cmd_remove)
    remove.add_argument("package")

    resolve = _command(subparsers, "resolve", "Resolve dependencies and write the lockfile.", _cmd_resolve)
    resolve.add_argument("--trace", action="store_true", help="Show resolver decisions.")

    install = _command(subparsers, "install", "Install dependencies into .pypm/.", _cmd_install)
    install.add_argument("--locked", action="store_true", help="Install from lockfile without resolving.")

    _command(subparsers, "update", "Resolve and install the latest compatible graph.", _cmd_update)
    _command(subparsers, "list", "List installed packages.", _cmd_list)
    _command(subparsers, "tree", "Print the resolved dependency tree.", _cmd_tree)

    why = _command(subparsers, "why", "Explain why a package is present.", _cmd_why)
    why.add_argument("package")

    graph = _command(subparsers, "graph", "Export the resolved dependency DAG.", _cmd_graph)
    graph.add_argument("--format", choices=("adjacency", "json", "dot"), default="adjacency")

    _command(subparsers, "verify", "Verify lockfile, registry archives, and installed packages.", _cmd_verify)

    publish = _command(subparsers, "publish", "Publish an inert package archive to the local registry.", _cmd_publish)
    publish.add_argument("archive")

    return parser


def _command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    handler: Handler,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(handler=handler)
    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir)
    init_manifest(project_dir)
    init_registry(_registry_path(args))
    ProjectStore(project_dir).ensure()
    print(f"initialized {project_dir.resolve()}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    if args.constraint is None:
        requirement = parse_requirement(args.package)
    else:
        requirement = parse_requirement_parts(args.package, args.constraint)
    manifest = add_dependency(args.project_dir, requirement.name, requirement.raw_constraint)
    print(f"added {requirement}")
    print(f"{len(manifest.dependencies)} direct dependencies")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    manifest = remove_dependency(args.project_dir, args.package)
    print(f"removed {args.package}")
    print(f"{len(manifest.dependencies)} direct dependencies")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    resolution = _resolve_project(args, trace=args.trace)
    write_lockfile(args.project_dir, Lockfile.from_graph(resolution.graph))
    if args.trace:
        print("\n".join(resolution.trace))
    for name in sorted(resolution.graph.packages):
        print(resolution.graph.packages[name].identifier)
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    registry = _open_registry(args)
    if args.locked:
        lockfile = load_lockfile(args.project_dir)
        report = install_from_lockfile(args.project_dir, lockfile, registry)
    else:
        # A plain `install` is reproducible by default: honor an existing
        # lockfile when it still satisfies the manifest, and only re-resolve
        # (and rewrite the lockfile) when it is missing or stale. Use `update`
        # to force re-resolution to the newest compatible graph.
        manifest = load_manifest(args.project_dir)
        existing_lock = _load_lockfile_if_present(args.project_dir)
        if existing_lock is not None and _lockfile_satisfies_manifest(manifest, existing_lock):
            report = install_from_lockfile(args.project_dir, existing_lock, registry)
        else:
            resolution = Resolver(registry).resolve(manifest.requirements())
            write_lockfile(args.project_dir, Lockfile.from_graph(resolution.graph))
            report = install_resolved(args.project_dir, resolution.graph, registry)
    for item in report.installed:
        print(f"installed {item}")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    registry = _open_registry(args)
    resolution = _resolve_project(args, registry=registry)
    write_lockfile(args.project_dir, Lockfile.from_graph(resolution.graph))
    report = install_resolved(args.project_dir, resolution.graph, registry)
    for item in report.installed:
        print(f"installed {item}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    store = ProjectStore(args.project_dir)
    records = store.read_records()
    if not records:
        print("no packages installed")
        return 0
    for name, record in sorted(records.items()):
        print(f"{name}@{record.version}")
    return 0


def _cmd_tree(args: argparse.Namespace) -> int:
    graph = load_lockfile(args.project_dir).to_graph()
    print(dependency_tree(graph))
    return 0


def _cmd_why(args: argparse.Namespace) -> int:
    graph = load_lockfile(args.project_dir).to_graph()
    target = args.package.lower()
    print(format_why(graph, target))
    return 0 if why_paths(graph, target) else 1


def _cmd_graph(args: argparse.Namespace) -> int:
    graph = load_lockfile(args.project_dir).to_graph()
    print(export_graph(graph, args.format))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    # Load the registry structurally only; `verify_project` performs and reports
    # the archive content hashing itself, so a tampered archive surfaces as a
    # readable verification failure rather than a registry-load exception.
    registry = _open_registry(args)
    ok, messages = verify_project(args.project_dir, registry)
    print("\n".join(messages))
    return 0 if ok else 1


def _cmd_publish(args: argparse.Namespace) -> int:
    package_version = publish_archive(_registry_path(args), args.archive)
    print(f"published {package_version.identifier}")
    return 0


def _resolve_project(
    args: argparse.Namespace,
    *,
    registry: LocalRegistry | None = None,
    trace: bool = False,
) -> Resolution:
    manifest = load_manifest(args.project_dir)
    active_registry = registry or _open_registry(args)
    return Resolver(active_registry, trace=trace).resolve(manifest.requirements())


def _open_registry(args: argparse.Namespace, *, verify_archives: bool = False) -> LocalRegistry:
    # Resolution and install need only the registry index facts. Archive bytes
    # are re-hashed where it actually matters (the installer before placement,
    # and `verify`), so the registry is loaded with structural validation only
    # by default instead of re-hashing every archive on each command.
    return LocalRegistry(_registry_path(args), verify_archives=verify_archives)


def _load_lockfile_if_present(project_dir: str | Path) -> Lockfile | None:
    if lockfile_path(project_dir).exists():
        return load_lockfile(project_dir)
    return None


def _lockfile_satisfies_manifest(manifest: Manifest, lockfile: Lockfile) -> bool:
    requirements = manifest.requirements()
    if {requirement.name for requirement in requirements} != set(lockfile.roots):
        return False
    for requirement in requirements:
        locked = lockfile.packages.get(requirement.name)
        if locked is None or not requirement.constraint.allows(locked.version):
            return False
    return True


def _registry_path(args: argparse.Namespace) -> Path:
    registry_path = Path(args.registry)
    if registry_path.is_absolute():
        return registry_path
    return Path(args.project_dir) / registry_path


if __name__ == "__main__":
    raise SystemExit(main())
