"""Exhaustive resolver, outdated, publish, tar, and registry_validation tests."""

from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from pypm_lab.errors import InstallError, RegistryError, RegistryValidationError
from pypm_lab.lockfile import Lockfile, LockPackage
from pypm_lab.manifest import Manifest
from pypm_lab.outdated import OutdatedPackage, find_outdated
from pypm_lab.publish import publish_archive
from pypm_lab.registry import InMemoryRegistry
from pypm_lab.registry_validation import validate_index_data, validate_new_entry
from pypm_lab.requirements import parse_requirement
from pypm_lab.resolver import ResolutionFailed, resolve
from pypm_lab.tar_safe import read_archive_manifest, safe_extractall
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def test_resolve_module_function():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {}}})
    result = resolve([parse_requirement("alpha@1.0.0")], registry, trace=True)
    assert result.graph.packages["alpha"].version == Version.parse("1.0.0")
    assert result.trace


def test_resolver_no_candidate_when_all_rejected():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {}, "2.0.0": {}}})
    with pytest.raises(ResolutionFailed, match="No available version satisfies"):
        resolve([parse_requirement("alpha@>=3.0.0")], registry)


def test_resolver_reports_no_satisfying_version_message():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {}, "2.0.0": {}}})
    with pytest.raises(ResolutionFailed) as exc:
        resolve([parse_requirement("alpha@>=9.0.0")], registry)
    assert "No available version satisfies" in exc.value.conflict.explain()


def test_outdated_latest_compatible_differs():
    registry = InMemoryRegistry({"alpha": {"1.0.0": {}, "1.5.0": {}, "3.0.0": {}}})
    lockfile = Lockfile(
        roots=("alpha",),
        packages={"alpha": LockPackage(Version.parse("1.0.0"), DIGEST, {})},
    )
    manifest = Manifest(name="demo", dependencies={"alpha": "^1.0.0"})
    report = find_outdated(lockfile, manifest, registry)
    assert len(report.outdated) == 1
    item = report.outdated[0]
    assert isinstance(item, OutdatedPackage)
    assert item.latest_compatible == Version.parse("1.5.0")
    assert "latest compatible" in item.describe()


def test_outdated_direct_dependency_not_in_manifest():
    registry = InMemoryRegistry({"shared": {"1.0.0": {}, "2.0.0": {}}})
    lockfile = Lockfile(
        roots=("alpha",),
        packages={
            "alpha": LockPackage(Version.parse("1.0.0"), DIGEST, {"shared": "1.0.0"}),
            "shared": LockPackage(Version.parse("1.0.0"), DIGEST, {}),
        },
    )
    manifest = Manifest(name="demo", dependencies={"alpha": "1.0.0"})
    report = find_outdated(lockfile, manifest, registry)
    shared = next(item for item in report.outdated if item.name == "shared")
    assert shared.latest_compatible is None


def test_publish_non_string_dependency_constraint(tmp_path, make_archive: Callable[..., Path]):
    build_root = tmp_path / "build" / "alpha-1.0.0"
    build_root.mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps(
            {
                "name": "alpha",
                "version": "1.0.0",
                "dependencies": {"shared": 123},
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "alpha-1.0.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(build_root, arcname="alpha-1.0.0")
    with pytest.raises(RegistryError, match="constraint must be a string"):
        publish_archive(tmp_path / "registry", archive)


def test_publish_generic_exception_rolls_back(tmp_path, make_archive: Callable[..., Path], monkeypatch):
    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"

    def boom(*args, **kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr("pypm_lab.publish.shutil.copy2", boom)
    with pytest.raises(RuntimeError, match="copy failed"):
        publish_archive(registry, archive)
    assert not (registry / "archives" / archive.name).exists()


def test_tar_safe_tar_error_on_extract(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not-a-tar")
    with pytest.raises(InstallError, match="cannot unpack archive"):
        safe_extractall(bad, tmp_path / "dest")


def test_tar_safe_extractfile_none(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    with mock.patch.object(tarfile.TarFile, "extractfile", return_value=None):
        with pytest.raises(RegistryValidationError, match="cannot read"):
            read_archive_manifest(archive)


def test_tar_safe_malformed_archive_json(tmp_path, make_archive: Callable[..., Path]):
    archive = make_archive("alpha", "1.0.0")
    with mock.patch.object(
        tarfile.TarFile,
        "extractfile",
        return_value=io.BytesIO(b'{"name":"alpha","version":"1.0.0","dependencies":{'),
    ):
        with pytest.raises(RegistryValidationError, match="malformed archive package.json"):
            read_archive_manifest(archive)


def test_tar_safe_install_error_wrapped_as_validation(tmp_path):
    import io

    evil = tmp_path / "evil.tar.gz"
    payload = b'{"name":"alpha","version":"1.0.0","dependencies":{}}'
    with tarfile.open(evil, "w:gz") as archive_file:
        info = tarfile.TarInfo(name="../escape/package.json")
        info.size = len(payload)
        archive_file.addfile(info, fileobj=io.BytesIO(payload))
    with pytest.raises(RegistryValidationError, match="escapes"):
        read_archive_manifest(evil)


def test_validate_index_data_non_object_packages(tmp_path):
    with pytest.raises(RegistryValidationError, match="must contain a 'packages' object"):
        validate_index_data(tmp_path, {"packages": []})


def test_validate_index_duplicate_version_key_in_raw_index(
    tmp_path, make_archive: Callable[..., Path]
):
    from pypm_lab.integrity import integrity_for_file
    from pypm_lab.registry_validation import validate_registry

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    (registry / "index.json").write_text(
        '{"packages": {"alpha": {"versions": {"1.0.0": '
        + json.dumps(entry)
        + ', "1.0.0": '
        + json.dumps(entry)
        + "}}}}",
        encoding="utf-8",
    )
    with pytest.raises(RegistryValidationError, match="duplicate key"):
        validate_registry(registry, verify_archives=False)


def test_validate_new_entry_isolated(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.integrity import integrity_for_file

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    dest = registry / "archives" / archive.name
    dest.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(dest),
        "dependencies": {},
    }
    validate_new_entry(registry, "alpha", Version.parse("1.0.0"), entry)


def test_validate_archive_metadata_invalid_name(tmp_path, make_archive: Callable[..., Path]):
    from pypm_lab.integrity import integrity_for_file

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    data = {"packages": {"beta": {"versions": {"1.0.0": entry}}}}
    with pytest.raises(RegistryValidationError, match="archive metadata name"):
        validate_index_data(registry, data, verify_archives=True)


def test_validate_archive_metadata_non_string_name(tmp_path):
    import tarfile

    from pypm_lab.integrity import integrity_for_file

    build_root = tmp_path / "build" / "123-1.0.0"
    build_root.mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps({"name": 123, "version": "1.0.0", "dependencies": {}}),
        encoding="utf-8",
    )
    archive = tmp_path / "123-1.0.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(build_root, arcname="123-1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    entry = {
        "archive": f"archives/{archive.name}",
        "integrity": integrity_for_file(placed),
        "dependencies": {},
    }
    data = {"packages": {"123": {"versions": {"1.0.0": entry}}}}
    with pytest.raises(RegistryValidationError, match="archive metadata name must be a string"):
        validate_index_data(registry, data, verify_archives=True)


def test_validate_registry_archive_path_escapes_root(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    data = {
        "packages": {
            "alpha": {
                "versions": {
                    "1.0.0": {
                        "archive": "../../../outside.tar.gz",
                        "integrity": DIGEST,
                        "dependencies": {},
                    }
                }
            }
        }
    }
    with pytest.raises(RegistryValidationError, match="must stay inside"):
        validate_index_data(registry, data, verify_archives=False)


def test_validate_registry_cannot_hash_archive(tmp_path, monkeypatch, make_archive: Callable[..., Path]):
    from pypm_lab.integrity import integrity_for_file

    archive = make_archive("alpha", "1.0.0")
    registry = tmp_path / "registry"
    (registry / "archives").mkdir(parents=True)
    placed = registry / "archives" / archive.name
    placed.write_bytes(archive.read_bytes())
    data = {
        "packages": {
            "alpha": {
                "versions": {
                    "1.0.0": {
                        "archive": f"archives/{archive.name}",
                        "integrity": integrity_for_file(placed),
                        "dependencies": {},
                    }
                }
            }
        }
    }

    def fail_hash(path):
        raise OSError("permission denied")

    monkeypatch.setattr("pypm_lab.registry_validation.integrity_for_file", fail_hash)
    with pytest.raises(RegistryValidationError, match="cannot hash archive"):
        validate_index_data(registry, data, verify_archives=True)
