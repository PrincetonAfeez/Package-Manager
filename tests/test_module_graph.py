"""Exhaustive graph module tests."""

from __future__ import annotations

import json

import pytest

from pypm_lab.errors import GraphError
from pypm_lab.graph import (
    dependency_tree,
    detect_cycle,
    export_graph,
    format_why,
    topological_sort,
    why_paths,
)
from pypm_lab.models import ResolvedGraph, ResolvedPackage
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def _pkg(name: str, deps: dict[str, str] | None = None) -> ResolvedPackage:
    return ResolvedPackage(
        name=name,
        version=Version.parse("1.0.0"),
        dependencies=deps or {},
        integrity=DIGEST,
    )


def test_topological_sort_accepts_raw_edge_mapping():
    order = topological_sort({"app": ("lib",), "lib": ()})
    assert order.index("lib") < order.index("app")


def test_topological_sort_raises_on_cycle():
    with pytest.raises(GraphError, match="cycle detected"):
        topological_sort({"a": ("b",), "b": ("a",)})


def test_detect_cycle_skips_already_visited_nodes():
    # Shared dependency visited from one branch should not re-walk from another.
    assert detect_cycle({"a": ("shared",), "b": ("shared",), "shared": ()}) is None


def test_detect_cycle_finds_cycle_after_visited_branch():
    edges = {"root": ("mid",), "mid": ("leaf",), "leaf": ("mid",)}
    cycle = detect_cycle(edges)
    assert cycle is not None
    assert cycle[0] == cycle[-1]


def test_dependency_tree_marks_cycle():
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={
            "alpha": _pkg("alpha", {"bravo": "1.0.0"}),
            "bravo": _pkg("bravo", {"alpha": "1.0.0"}),
        },
    )
    text = dependency_tree(graph)
    assert "(cycle)" in text


def test_dependency_tree_skips_missing_root_package():
    graph = ResolvedGraph(roots=("ghost",), packages={"alpha": _pkg("alpha")})
    assert dependency_tree(graph) == ""


def test_why_paths_stops_at_missing_intermediate_node():
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={"alpha": _pkg("alpha", {"beta": "1.0.0"})},
    )
    assert why_paths(graph, "shared") == []


def test_why_paths_includes_external_dependency_name():
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={"alpha": _pkg("alpha", {"ghost": "1.0.0"})},
    )
    paths = why_paths(graph, "ghost")
    assert paths == [["alpha", "ghost"]]


def test_why_paths_finds_transitive_path():
    graph = ResolvedGraph(
        roots=("app",),
        packages={
            "app": _pkg("app", {"mid": "1.0.0"}),
            "mid": _pkg("mid", {"leaf": "1.0.0"}),
            "leaf": _pkg("leaf"),
        },
    )
    paths = why_paths(graph, "leaf")
    assert paths == [["app", "mid", "leaf"]]


def test_format_why_without_paths():
    graph = ResolvedGraph(roots=("alpha",), packages={"alpha": _pkg("alpha")})
    assert "not present" in format_why(graph, "missing", [])


def test_format_why_uses_default_paths():
    graph = ResolvedGraph(
        roots=("alpha",),
        packages={"alpha": _pkg("alpha", {"shared": "1.0.0"}), "shared": _pkg("shared")},
    )
    text = format_why(graph, "shared")
    assert "alpha@1.0.0 -> shared@1.0.0" in text


def test_format_why_renders_unknown_node_name():
    graph = ResolvedGraph(roots=("alpha",), packages={"alpha": _pkg("alpha")})
    text = format_why(graph, "alpha", [["alpha", "ghost"]])
    assert "ghost" in text


def test_export_graph_json_and_dot():
    graph = ResolvedGraph(
        roots=("app",),
        packages={"app": _pkg("app", {"lib": "1.0.0"}), "lib": _pkg("lib")},
    )
    payload = json.loads(export_graph(graph, "json"))
    assert payload["nodes"]
    assert payload["edges"]
    dot = export_graph(graph, "dot")
    assert "digraph dependencies" in dot
    assert '"app" -> "lib"' in dot


def test_export_graph_unsupported_format():
    graph = ResolvedGraph(roots=("alpha",), packages={"alpha": _pkg("alpha")})
    with pytest.raises(GraphError, match="unsupported graph format"):
        export_graph(graph, "svg")
