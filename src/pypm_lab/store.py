"""Project-local package store and installed records."""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath

from .errors import InstallError, IntegrityError, RequirementError, VersionError
from .fsio import atomic_write_json
from .integrity import parse_integrity
from .jsonio import loads_no_duplicate_keys
from .models import StoreRecord
from .requirements import validate_package_name
from .versions import Version


class ProjectStore:
    def __init__(self, project_dir: Path | str):
        self.project_dir = Path(project_dir)
        self.root = self.project_dir / ".pypm"
        self.store_dir = self.root / "store"
        self.cache_dir = self.root / "cache" / "sha256"
        self.tmp_dir = self.root / "tmp"
        self.installed_path = self.root / "installed.json"

    def ensure(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        if not self.installed_path.exists():
            self.write_records({})

    def package_dir(self, name: str, version: str) -> Path:
        return self.store_dir / name / version

    def cache_path(self, integrity: str) -> Path:
        digest = parse_integrity(integrity)
        return self.cache_dir / f"{digest}.tar.gz"

    def resolve_record_path(self, record: StoreRecord) -> Path:
        """Resolve an installed record path and ensure it stays under the store."""

        relative = _validate_installed_record_path(record.path, name=record.name, version=record.version)
        resolved = (self.root / relative).resolve()
        root_resolved = self.root.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise InstallError(f"installed record for {record.name}: path escapes .pypm root") from exc
        expected = self.package_dir(record.name, record.version).resolve()
        try:
            resolved.relative_to(expected)
        except ValueError as exc:
            raise InstallError(
                f"installed record for {record.name}: path is outside "
                f"store/{record.name}/{record.version}/"
            ) from exc
        return resolved

    def read_records(self) -> dict[str, StoreRecord]:
        if not self.installed_path.exists():
            return {}
        try:
            data = loads_no_duplicate_keys(self.installed_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InstallError(f"malformed installed record {self.installed_path}: {exc.msg}") from exc
        except ValueError as exc:
            raise InstallError(f"malformed installed record {self.installed_path}: {exc}") from exc
        packages = data.get("packages", {})
        if not isinstance(packages, dict):
            raise InstallError("installed.json packages must be an object")
        records: dict[str, StoreRecord] = {}
        for raw_name, record in packages.items():
            try:
                name = validate_package_name(raw_name)
            except RequirementError as exc:
                raise InstallError(f"installed record key {raw_name!r}: {exc}") from exc
            if not isinstance(record, dict):
                raise InstallError(f"installed record for {name} must be an object")
            for field in ("version", "integrity", "treeHash", "path"):
                if field not in record:
                    raise InstallError(f"installed record for {name} is missing field {field}")
                if not isinstance(record[field], str):
                    raise InstallError(f"installed record for {name}: field {field} must be a string")
            try:
                version = Version.parse(record["version"])
            except VersionError as exc:
                raise InstallError(
                    f"installed record for {name}: invalid version {record['version']!r}: {exc}"
                ) from exc
            try:
                parse_integrity(record["integrity"])
            except IntegrityError as exc:
                raise InstallError(f"installed record for {name}: invalid integrity: {exc}") from exc
            try:
                parse_integrity(record["treeHash"])
            except IntegrityError as exc:
                raise InstallError(f"installed record for {name}: invalid treeHash: {exc}") from exc
            path = _validate_installed_record_path(record["path"], name=name, version=str(version))
            records[name] = StoreRecord(
                name=name,
                version=str(version),
                integrity=record["integrity"],
                tree_hash=record["treeHash"],
                path=path,
            )
        return records

    def write_records(self, records: dict[str, StoreRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.installed_path,
            {
                "packages": {
                    name: record.to_dict()
                    for name, record in sorted(records.items())
                }
            },
        )

    def clean(self, *, dry_run: bool = False) -> list[str]:
        """Prune store directories and cache archives not referenced by installed.json.

        Reconciles the store against the recorded install set: removes orphaned
        package directories, cache entries whose integrity digest is no longer
        installed, and any leftover temporary files. Returns the relative paths
        that were (or, when ``dry_run`` is set, would be) removed without deleting
        anything.
        """

        records = self.read_records()
        kept_paths = {record.path for record in records.values()}
        kept_digests = {parse_integrity(record.integrity) for record in records.values()}
        removed: list[str] = []

        if self.store_dir.exists():
            for name_dir in sorted(self.store_dir.iterdir()):
                if not name_dir.is_dir():
                    continue
                for version_dir in sorted(name_dir.iterdir()):
                    relative = version_dir.relative_to(self.root).as_posix()
                    if relative not in kept_paths:
                        if not dry_run:
                            shutil.rmtree(version_dir, ignore_errors=True)
                        removed.append(relative)
                if not dry_run and name_dir.exists() and not any(name_dir.iterdir()):
                    name_dir.rmdir()

        if self.cache_dir.exists():
            for cache_file in sorted(self.cache_dir.glob("*.tar.gz")):
                digest = cache_file.name.removesuffix(".tar.gz")
                if digest not in kept_digests:
                    if not dry_run:
                        cache_file.unlink(missing_ok=True)
                    removed.append(f"cache/sha256/{cache_file.name}")

        if self.tmp_dir.exists():
            for leftover in sorted(self.tmp_dir.iterdir()):
                if not dry_run:
                    if leftover.is_dir():
                        shutil.rmtree(leftover, ignore_errors=True)
                    else:
                        leftover.unlink(missing_ok=True)
                removed.append(f"tmp/{leftover.name}")

        return removed


def _validate_installed_record_path(path: str, *, name: str, version: str) -> str:
    if "\\" in path or path.startswith("/"):
        raise InstallError(f"installed record for {name}: path must be a relative POSIX path")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise InstallError(f"installed record for {name}: path must be a relative POSIX path")
    if ".." in pure.parts or "" in pure.parts:
        raise InstallError(f"installed record for {name}: path must not contain empty or parent segments")
    expected = PurePosixPath("store") / name / version
    if pure != expected:
        try:
            pure.relative_to(expected)
        except ValueError as exc:
            raise InstallError(
                f"installed record for {name}: path must be {expected.as_posix()} or a subdirectory"
            ) from exc
    return pure.as_posix()
