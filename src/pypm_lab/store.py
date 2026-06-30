"""Project-local package store and installed records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .errors import InstallError
from .integrity import parse_integrity
from .models import StoreRecord


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

    def read_records(self) -> dict[str, StoreRecord]:
        if not self.installed_path.exists():
            return {}
        try:
            data = json.loads(self.installed_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InstallError(f"malformed installed record {self.installed_path}: {exc.msg}") from exc
        packages = data.get("packages", {})
        if not isinstance(packages, dict):
            raise InstallError("installed.json packages must be an object")
        records: dict[str, StoreRecord] = {}
        for name, record in packages.items():
            if not isinstance(record, dict):
                raise InstallError(f"installed record for {name} must be an object")
            try:
                records[name] = StoreRecord(
                    name=name,
                    version=str(record["version"]),
                    integrity=str(record["integrity"]),
                    tree_hash=str(record["treeHash"]),
                    path=str(record["path"]),
                )
            except KeyError as exc:
                raise InstallError(
                    f"installed record for {name} is missing field {exc.args[0]}"
                ) from exc
        return records

    def write_records(self, records: dict[str, StoreRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "packages": {
                name: record.to_dict()
                for name, record in sorted(records.items())
            }
        }
        fd, tmp_name = tempfile.mkstemp(
            prefix="installed-", suffix=".json", dir=str(self.root)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self.installed_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
