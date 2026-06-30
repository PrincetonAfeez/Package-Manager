import json
from pathlib import Path
import tarfile

import pytest

from pypm_lab.errors import IntegrityError, RegistryValidationError
from pypm_lab.installer import install_from_lockfile, install_resolved
from pypm_lab.integrity import integrity_for_file
from pypm_lab.lockfile import LockPackage, Lockfile, write_lockfile
from pypm_lab.manifest import add_dependency, init_manifest, load_manifest
from pypm_lab.models import PackageVersion, ResolvedGraph, ResolvedPackage
from pypm_lab.publish import publish_archive
from pypm_lab.registry import InMemoryRegistry, LocalRegistry
from pypm_lab.registry_validation import validate_registry
from pypm_lab.resolver import Resolver
from pypm_lab.store import ProjectStore
from pypm_lab.verify import verify_project
from pypm_lab.versions import Version


def make_archive(tmp_path: Path, name: str, version: str, dependencies=None) -> Path:
    dependencies = dependencies or {}
    build_root = tmp_path / "build" / f"{name}-{version}"
    (build_root / "src").mkdir(parents=True)
    (build_root / "package.json").write_text(
        json.dumps({"name": name, "version": version, "dependencies": dependencies}),
        encoding="utf-8",
    )
    (build_root / "src" / f"{name}.txt").write_text(f"{name} {version}", encoding="utf-8")
    archive_path = tmp_path / f"{name}-{version}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(build_root, arcname=f"{name}-{version}")
    return archive_path


def test_registry_validation_rejects_archive_metadata_disagreement(tmp_path):
    registry = tmp_path / "registry"
    archives = registry / "archives"
    archives.mkdir(parents=True)
    archive_path = make_archive(tmp_path, "alpha", "1.0.0")
    registry_archive = archives / archive_path.name
    registry_archive.write_bytes(archive_path.read_bytes())
    (registry / "index.json").write_text(
        json.dumps(
            {
                "packages": {
                    "alpha": {
                        "versions": {
                            "1.0.1": {
                                "archive": f"archives/{archive_path.name}",
                                "integrity": integrity_for_file(registry_archive),
                                "dependencies": {},
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RegistryValidationError, match="archive metadata version"):
        validate_registry(registry)


def test_publish_resolve_install_and_verify_detects_tampering(tmp_path):
    registry_dir = tmp_path / "registry"
    project_dir = tmp_path / "project"
    init_manifest(project_dir)

    archive = make_archive(tmp_path, "shared", "1.0.0")
    publish_archive(registry_dir, archive)
    add_dependency(project_dir, "shared", "1.0.0")

    registry = LocalRegistry(registry_dir)
    resolution = Resolver(registry).resolve(load_manifest(project_dir).requirements())
    lockfile = Lockfile.from_graph(resolution.graph)
    write_lockfile(project_dir, lockfile)
    install_resolved(project_dir, resolution.graph, registry)

    ok, messages = verify_project(project_dir, registry)
    assert ok, messages

    installed_file = project_dir / ".pypm" / "store" / "shared" / "1.0.0" / "src" / "shared.txt"
    installed_file.write_text("tampered", encoding="utf-8")

    ok, messages = verify_project(project_dir, registry)
    assert not ok
    assert any("installed contents were modified" in message for message in messages)


def test_integrity_mismatch_does_not_mark_package_installed(tmp_path):
    archive = make_archive(tmp_path, "alpha", "1.0.0")
    bad_integrity = "sha256:" + "0" * 64
    registry = InMemoryRegistry(
        {
            "alpha": {
                "1.0.0": PackageVersion(
                    name="alpha",
                    version=Version.parse("1.0.0"),
                    dependencies={},
                    integrity=bad_integrity,
                    archive=archive,
                )
            }
        }
    )
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={
            "alpha": ResolvedPackage(
                name="alpha",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity=bad_integrity,
                archive=str(archive),
            )
        },
    )

    with pytest.raises(IntegrityError):
        install_resolved(tmp_path / "project", graph, registry)

    records = ProjectStore(tmp_path / "project").read_records()
    assert records == {}


def test_locked_install_does_not_query_available_versions(tmp_path):
    archive = make_archive(tmp_path, "alpha", "1.0.0")
    integrity = integrity_for_file(archive)
    package = PackageVersion(
        name="alpha",
        version=Version.parse("1.0.0"),
        dependencies={},
        integrity=integrity,
        archive=archive,
    )
    lockfile = Lockfile(
        roots=("alpha",),
        packages={
            "alpha": LockPackage(
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity=integrity,
            )
        },
    )

    class LockedOnlyRegistry:
        def available_versions(self, name):
            raise AssertionError("locked install should not resolve")

        def get_package_version(self, name, version):
            assert name == "alpha"
            assert version == Version.parse("1.0.0")
            return package

    report = install_from_lockfile(tmp_path / "project", lockfile, LockedOnlyRegistry())

    assert report.installed == ("alpha@1.0.0",)
