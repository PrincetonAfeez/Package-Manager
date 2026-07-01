"""Validation for the custom local registry and inert archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constraints import VersionConstraint
from .errors import RegistryValidationError
from .integrity import integrity_for_file, parse_integrity
from .jsonio import loads_no_duplicate_keys
from .requirements import RequirementError, validate_package_name
from .tar_safe import read_archive_manifest
from .versions import Version, VersionError


def load_json_no_duplicates(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryValidationError([f"cannot read {path}: {exc}"]) from exc

    try:
        data = loads_no_duplicate_keys(text)
    except json.JSONDecodeError as exc:
        raise RegistryValidationError([f"malformed JSON in {path}: {exc.msg}"]) from exc
    except ValueError as exc:
        raise RegistryValidationError([f"malformed JSON in {path}: {exc}"]) from exc
    if not isinstance(data, dict):
        raise RegistryValidationError([f"{path} must contain a JSON object"])
    return data


def validate_registry(
    root: Path | str,
    *,
    verify_archives: bool = True,
    check_dependencies_exist: bool = True,
) -> dict[str, Any]:
    registry_root = Path(root)
    index_path = registry_root / "index.json"
    if not index_path.exists():
        raise RegistryValidationError([f"missing registry index {index_path}"])
    data = load_json_no_duplicates(index_path)
    validate_index_data(
        registry_root,
        data,
        verify_archives=verify_archives,
        check_dependencies_exist=check_dependencies_exist,
    )
    return data


def validate_index_data(
    root: Path | str,
    data: dict[str, Any],
    *,
    verify_archives: bool = True,
    check_dependencies_exist: bool = True,
) -> None:
    registry_root = Path(root).resolve()
    errors: list[str] = []
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise RegistryValidationError(["registry index must contain a 'packages' object"])

    normalized_names: dict[str, str] = {}
    for raw_name in packages:
        try:
            normalized = validate_package_name(raw_name)
        except RequirementError as exc:
            errors.append(str(exc))
            continue
        if normalized in normalized_names and normalized_names[normalized] != raw_name:
            errors.append(f"duplicate package name after normalization: {raw_name!r}")
        normalized_names[normalized] = raw_name

    known_packages = set(normalized_names)

    for raw_name, package_data in packages.items():
        try:
            name = validate_package_name(raw_name)
        except RequirementError:
            continue
        if not isinstance(package_data, dict):
            errors.append(f"{name}: package entry must be an object")
            continue
        versions = package_data.get("versions")
        if not isinstance(versions, dict) or not versions:
            errors.append(f"{name}: missing or empty versions object")
            continue
        seen_versions: set[Version] = set()
        for raw_version, version_data in versions.items():
            try:
                version = Version.parse(raw_version)
            except VersionError as exc:
                errors.append(f"{name}: invalid version {raw_version!r}: {exc}")
                continue
            if version in seen_versions:
                errors.append(f"{name}: duplicate version {version}")
            seen_versions.add(version)
            if not isinstance(version_data, dict):
                errors.append(f"{name}@{version}: version entry must be an object")
                continue
            _validate_version_entry(
                registry_root,
                known_packages,
                name,
                version,
                version_data,
                errors,
                verify_archives=verify_archives,
                check_dependencies_exist=check_dependencies_exist,
            )

    if errors:
        raise RegistryValidationError(errors)


def validate_new_entry(
    registry_root: Path | str,
    name: str,
    version: Version,
    version_data: dict[str, Any],
) -> None:
    """Validate a single newly-published version entry in isolation.

    Used by `publish`, which builds a registry incrementally. It checks the new
    entry's archive path, integrity, dependency constraints, archive existence,
    and archive-metadata agreement, but does not re-scan the whole index or
    require the entry's dependencies to already exist (that is enforced when the
    registry is later loaded). This keeps publishing O(1) instead of O(N).
    """

    errors: list[str] = []
    _validate_version_entry(
        Path(registry_root).resolve(),
        {name},
        name,
        version,
        version_data,
        errors,
        verify_archives=False,
        check_dependencies_exist=False,
    )
    if errors:
        raise RegistryValidationError(errors)


def _validate_version_entry(
    registry_root: Path,
    known_packages: set[str],
    name: str,
    version: Version,
    version_data: dict[str, Any],
    errors: list[str],
    *,
    verify_archives: bool = True,
    check_dependencies_exist: bool = True,
) -> None:
    archive_value = version_data.get("archive")
    archive_path: Path | None = None
    if not isinstance(archive_value, str) or not archive_value:
        errors.append(f"{name}@{version}: missing archive path")
    else:
        archive_path = _resolve_archive_path(registry_root, archive_value, f"{name}@{version}", errors)

    integrity = version_data.get("integrity")
    if not isinstance(integrity, str):
        errors.append(f"{name}@{version}: missing integrity field")
        integrity = ""
    else:
        try:
            parse_integrity(integrity)
        except Exception as exc:  # noqa: BLE001 - keep validation cumulative.
            errors.append(f"{name}@{version}: {exc}")

    dependencies = version_data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        errors.append(f"{name}@{version}: dependencies must be an object")
        dependencies = {}
    normalized_dependencies: dict[str, str] = {}
    for dependency_name, raw_constraint in dependencies.items():
        try:
            normalized_dependency = validate_package_name(dependency_name)
        except RequirementError as exc:
            errors.append(f"{name}@{version}: invalid dependency name {dependency_name!r}: {exc}")
            continue
        if check_dependencies_exist and normalized_dependency not in known_packages:
            errors.append(f"{name}@{version}: dependency on missing package {normalized_dependency}")
        if not isinstance(raw_constraint, str):
            errors.append(f"{name}@{version}: dependency {normalized_dependency} constraint must be a string")
            continue
        try:
            VersionConstraint.parse(raw_constraint)
        except Exception as exc:  # noqa: BLE001 - keep validation cumulative.
            errors.append(f"{name}@{version}: malformed dependency constraint for {normalized_dependency}: {exc}")
            continue
        normalized_dependencies[normalized_dependency] = raw_constraint

    if archive_path is None or not archive_path.exists():
        if archive_path is not None:
            errors.append(f"{name}@{version}: archive does not exist: {archive_path}")
        return

    if verify_archives and integrity:
        try:
            actual_integrity = integrity_for_file(archive_path)
            if actual_integrity.lower() != integrity.lower():
                errors.append(
                    f"{name}@{version}: archive hash mismatch: expected {integrity}, got {actual_integrity}"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}@{version}: cannot hash archive: {exc}")

    try:
        archive_manifest = read_archive_manifest(archive_path)
        _validate_archive_manifest_agreement(
            name,
            version,
            normalized_dependencies,
            archive_manifest,
            errors,
        )
    except RegistryValidationError as exc:
        errors.extend(exc.errors)


def _resolve_archive_path(
    registry_root: Path,
    archive_value: str,
    label: str,
    errors: list[str],
) -> Path | None:
    raw_path = Path(archive_value)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        errors.append(f"{label}: archive path must stay inside the registry")
        return None
    archive_path = (registry_root / raw_path).resolve()
    try:
        archive_path.relative_to(registry_root)
    except ValueError:
        errors.append(f"{label}: archive path escapes registry root")
        return None
    return archive_path


def _validate_archive_manifest_agreement(
    name: str,
    version: Version,
    dependencies: dict[str, str],
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    try:
        archive_name = validate_package_name(str(manifest.get("name", "")))
    except RequirementError as exc:
        errors.append(f"{name}@{version}: archive metadata has invalid name: {exc}")
        archive_name = ""
    try:
        archive_version = Version.parse(str(manifest.get("version", "")))
    except VersionError as exc:
        errors.append(f"{name}@{version}: archive metadata has invalid version: {exc}")
        archive_version = None

    if archive_name and archive_name != name:
        errors.append(f"{name}@{version}: archive metadata name is {archive_name}, expected {name}")
    if archive_version is not None and archive_version != version:
        errors.append(f"{name}@{version}: archive metadata version is {archive_version}, expected {version}")

    archive_dependencies = manifest.get("dependencies", {})
    if not isinstance(archive_dependencies, dict):
        errors.append(f"{name}@{version}: archive dependencies must be an object")
        return
    normalized_archive_dependencies: dict[str, str] = {}
    for dependency_name, raw_constraint in archive_dependencies.items():
        try:
            normalized_dependency = validate_package_name(dependency_name)
        except RequirementError as exc:
            errors.append(f"{name}@{version}: archive dependency name is invalid: {exc}")
            continue
        if not isinstance(raw_constraint, str):
            errors.append(f"{name}@{version}: archive dependency {normalized_dependency} constraint must be a string")
            continue
        normalized_archive_dependencies[normalized_dependency] = raw_constraint

    if normalized_archive_dependencies != dependencies:
        errors.append(f"{name}@{version}: archive metadata dependencies disagree with registry index")
