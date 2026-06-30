"""Project manifest loading and mutation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import ManifestError
from .jsonio import loads_no_duplicate_keys
from .requirements import Requirement, parse_requirement_parts, validate_package_name

MANIFEST_NAME = "package.json"


@dataclass(frozen=True)
class Manifest:
    name: str
    dependencies: dict[str, str]

    def requirements(self) -> tuple[Requirement, ...]:
        return tuple(
            parse_requirement_parts(name, constraint)
            for name, constraint in sorted(self.dependencies.items())
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "dependencies": dict(sorted(self.dependencies.items())),
        }


def manifest_path(project_dir: Path | str) -> Path:
    return Path(project_dir) / MANIFEST_NAME


def load_manifest(project_dir: Path | str) -> Manifest:
    path = manifest_path(project_dir)
    if not path.exists():
        raise ManifestError(f"missing manifest {path}; run `pypm init` first")
    try:
        data = loads_no_duplicate_keys(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"malformed manifest {path}: {exc.msg}") from exc
    except ValueError as exc:
        raise ManifestError(f"malformed manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    name = str(data.get("name", "demo-app"))
    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise ManifestError("manifest dependencies must be an object")
    parsed_dependencies: dict[str, str] = {}
    for raw_name, raw_constraint in dependencies.items():
        name_key = validate_package_name(raw_name)
        if not isinstance(raw_constraint, str):
            raise ManifestError(f"dependency {name_key} constraint must be a string")
        parse_requirement_parts(name_key, raw_constraint)
        parsed_dependencies[name_key] = raw_constraint
    return Manifest(name=name, dependencies=dict(sorted(parsed_dependencies.items())))


def save_manifest(project_dir: Path | str, manifest: Manifest) -> Path:
    path = manifest_path(project_dir)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def init_manifest(project_dir: Path | str, *, name: str | None = None) -> Manifest:
    project_path = Path(project_dir)
    project_path.mkdir(parents=True, exist_ok=True)
    path = manifest_path(project_path)
    if path.exists():
        return load_manifest(project_path)
    manifest = Manifest(name=name or project_path.resolve().name.lower().replace(" ", "-"), dependencies={})
    save_manifest(project_path, manifest)
    return manifest


def add_dependency(project_dir: Path | str, package: str, constraint: str) -> Manifest:
    manifest = load_manifest(project_dir)
    requirement = parse_requirement_parts(package, constraint)
    dependencies = dict(manifest.dependencies)
    dependencies[requirement.name] = requirement.raw_constraint
    updated = Manifest(name=manifest.name, dependencies=dict(sorted(dependencies.items())))
    save_manifest(project_dir, updated)
    return updated


def remove_dependency(project_dir: Path | str, package: str) -> Manifest:
    manifest = load_manifest(project_dir)
    package_name = validate_package_name(package)
    dependencies = dict(manifest.dependencies)
    if package_name not in dependencies:
        raise ManifestError(f"{package_name} is not a direct dependency")
    del dependencies[package_name]
    updated = Manifest(name=manifest.name, dependencies=dict(sorted(dependencies.items())))
    save_manifest(project_dir, updated)
    return updated
