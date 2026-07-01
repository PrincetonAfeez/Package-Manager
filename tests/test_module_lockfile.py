"""Exhaustive lockfile module tests."""

from __future__ import annotations

import pytest

from pypm_lab.errors import LockfileError
from pypm_lab.lockfile import (
    Lockfile,
    LockPackage,
    load_lockfile,
    lockfile_path,
    parse_lockfile,
    write_lockfile,
)
from pypm_lab.models import ResolvedGraph, ResolvedPackage
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def _minimal_lockfile_dict(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "lockfileVersion": 1,
        "roots": ["alpha"],
        "packages": {
            "alpha": {
                "version": "1.0.0",
                "integrity": DIGEST,
                "dependencies": {},
            }
        },
    }
    base.update(overrides)
    return base


def test_lockfile_path_and_write(tmp_path):
    project = tmp_path / "proj"
    lock = Lockfile(
        packages={"alpha": LockPackage(Version.parse("1.0.0"), DIGEST, {})},
        roots=("alpha",),
    )
    path = write_lockfile(project, lock)
    assert path == lockfile_path(project)
    assert load_lockfile(project).dumps() == lock.dumps()


def test_load_lockfile_missing(tmp_path):
    with pytest.raises(LockfileError, match="missing lockfile"):
        load_lockfile(tmp_path)


def test_load_lockfile_malformed_json(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    lockfile_path(project).write_text("{ bad", encoding="utf-8")
    with pytest.raises(LockfileError, match="malformed lockfile"):
        load_lockfile(project)


def test_load_lockfile_duplicate_keys(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    lockfile_path(project).write_text(
        '{"lockfileVersion": 1, "roots": [], "packages": {}, "packages": {}}',
        encoding="utf-8",
    )
    with pytest.raises(LockfileError, match="malformed lockfile"):
        load_lockfile(project)


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ([], "must be a JSON object"),
        ({"lockfileVersion": 99}, "unsupported lockfileVersion"),
        ({"lockfileVersion": 1, "roots": {}}, "roots must be a list"),
        ({"lockfileVersion": 1, "roots": [], "packages": []}, "packages must be an object"),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": []},
            },
            "lockfile package must be an object",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": {"integrity": DIGEST, "dependencies": {}}},
            },
            "missing lockfile field version",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": {"version": "1.0.0", "dependencies": {}}},
            },
            "missing lockfile field integrity",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {"alpha": {"version": "1.2", "integrity": DIGEST, "dependencies": {}}},
            },
            "invalid version",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {
                    "alpha": {
                        "version": "1.0.0",
                        "integrity": "sha1:abc",
                        "dependencies": {},
                    }
                },
            },
            "invalid integrity",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {
                    "alpha": {
                        "version": "1.0.0",
                        "integrity": DIGEST,
                        "dependencies": [],
                    }
                },
            },
            "dependencies must be an object",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["ghost"],
                "packages": {
                    "alpha": {
                        "version": "1.0.0",
                        "integrity": DIGEST,
                        "dependencies": {},
                    }
                },
            },
            "lockfile root ghost has no package entry",
        ),
        (
            {
                "lockfileVersion": 1,
                "roots": ["alpha"],
                "packages": {
                    "alpha": {
                        "version": "1.0.0",
                        "integrity": DIGEST,
                        "dependencies": {"ghost": ">=1.0.0"},
                    }
                },
            },
            "dependency ghost has no package entry",
        ),
    ],
)
def test_parse_lockfile_validation_errors(data, match):
    with pytest.raises(LockfileError, match=match):
        parse_lockfile(data)


def test_lockfile_roundtrip_via_graph():
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={
            "alpha": ResolvedPackage(
                name="alpha",
                version=Version.parse("1.0.0"),
                dependencies={"shared": ">=1.0.0"},
                integrity=DIGEST,
            ),
            "shared": ResolvedPackage(
                name="shared",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity=DIGEST,
            ),
        },
    )
    lock = Lockfile.from_graph(graph)
    restored = lock.to_graph()
    assert sorted(restored.packages) == sorted(graph.packages)
    assert restored.roots == graph.roots
