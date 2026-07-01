"""Tests for graph and lockfile functionality."""

from pypm_lab.graph import detect_cycle, export_graph, topological_sort, why_paths
from pypm_lab.lockfile import Lockfile
from pypm_lab.models import ResolvedGraph, ResolvedPackage
from pypm_lab.versions import Version


def test_topological_sort_dependencies_before_dependents():
    graph = ResolvedGraph(
        roots=("app",),
        packages={
            "app": ResolvedPackage(
                name="app",
                version=Version.parse("1.0.0"),
                dependencies={"shared": "1.0.0"},
                integrity="sha256:" + "0" * 64,
            ),
            "shared": ResolvedPackage(
                name="shared",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity="sha256:" + "0" * 64,
            ),
        },
    )

    assert topological_sort(graph) == ["shared", "app"]
    adjacency = export_graph(graph, "adjacency")
    assert "app: shared" in adjacency
    # A leaf renders without a trailing space and `why` finds no path to a missing node.
    assert "shared:" in adjacency.splitlines()
    assert "shared: " not in adjacency.splitlines()
    assert why_paths(graph, "absent") == []


def test_cycle_detection_fires():
    assert detect_cycle({"alpha": ("bravo",), "bravo": ("alpha",)}) == [
        "alpha",
        "bravo",
        "alpha",
    ]


def test_lockfile_serialization_is_stable():
    graph = ResolvedGraph(
        roots=("bravo", "alpha"),
        packages={
            "shared": ResolvedPackage(
                name="shared",
                version=Version.parse("1.0.0"),
                dependencies={},
                integrity="sha256:" + "1" * 64,
            ),
            "alpha": ResolvedPackage(
                name="alpha",
                version=Version.parse("1.0.0"),
                dependencies={"shared": "1.0.0"},
                integrity="sha256:" + "2" * 64,
            ),
        },
    )

    dumped = Lockfile.from_graph(graph).dumps()
    assert dumped == Lockfile.from_graph(graph).dumps()
    assert dumped.index('"alpha"') < dumped.index('"shared"')
