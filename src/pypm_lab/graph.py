"""Resolved dependency DAG utilities."""

from __future__ import annotations

import json
from typing import Iterator, Mapping

from .errors import GraphError
from .models import ResolvedGraph


def _all_nodes(edges: Mapping[str, tuple[str, ...] | list[str]]) -> set[str]:
    nodes = set(edges)
    for dependencies in edges.values():
        nodes.update(dependencies)
    return nodes


def detect_cycle(edges: Mapping[str, tuple[str, ...] | list[str]]) -> list[str] | None:
    """Return a deterministic cycle path if one exists.

    Implemented with an explicit stack (iterative DFS) so that deep dependency
    chains cannot exceed Python's recursion limit.
    """

    visited: set[str] = set()
    for start in sorted(_all_nodes(edges)):
        if start in visited:
            continue
        path: list[str] = [start]
        on_path: set[str] = {start}
        frames: list[Iterator[str]] = [iter(sorted(edges.get(start, ())))]
        while frames:
            advanced = False
            for dependency in frames[-1]:
                if dependency in on_path:
                    return path[path.index(dependency):] + [dependency]
                if dependency in visited:
                    continue
                path.append(dependency)
                on_path.add(dependency)
                frames.append(iter(sorted(edges.get(dependency, ()))))
                advanced = True
                break
            if not advanced:
                node = path.pop()
                on_path.discard(node)
                visited.add(node)
                frames.pop()
    return None


def topological_sort(graph: ResolvedGraph | Mapping[str, tuple[str, ...] | list[str]]) -> list[str]:
    """Return dependencies before dependents (iterative post-order DFS)."""

    edges = graph.edges() if isinstance(graph, ResolvedGraph) else dict(graph)
    cycle = detect_cycle(edges)
    if cycle:
        raise GraphError(f"cycle detected: {' -> '.join(cycle)}")

    visited: set[str] = set()
    order: list[str] = []
    for start in sorted(_all_nodes(edges)):
        if start in visited:
            continue
        visited.add(start)
        frames: list[Iterator[str]] = [iter(sorted(edges.get(start, ())))]
        nodes: list[str] = [start]
        while frames:
            advanced = False
            for dependency in frames[-1]:
                if dependency not in visited:
                    visited.add(dependency)
                    nodes.append(dependency)
                    frames.append(iter(sorted(edges.get(dependency, ()))))
                    advanced = True
                    break
            if not advanced:
                order.append(nodes.pop())
                frames.pop()
    return order


def dependency_tree(graph: ResolvedGraph) -> str:
    lines: list[str] = []

    def walk(name: str, prefix: str, path: tuple[str, ...]) -> None:
        package = graph.packages[name]
        marker = " (cycle)" if name in path else ""
        lines.append(f"{prefix}{package.identifier}{marker}")
        if marker:
            return
        for dependency in sorted(package.dependencies):
            if dependency in graph.packages:
                walk(dependency, prefix + "  ", path + (name,))

    for root in graph.roots:
        if root in graph.packages:
            walk(root, "", ())
    return "\n".join(lines)


def why_paths(graph: ResolvedGraph, target: str) -> list[list[str]]:
    paths: list[list[str]] = []

    def walk(name: str, path: list[str]) -> None:
        current = path + [name]
        if name == target:
            paths.append(current)
            return
        package = graph.packages.get(name)
        if package is None:
            return
        for dependency in sorted(package.dependencies):
            if dependency not in current:
                walk(dependency, current)

    for root in graph.roots:
        walk(root, [])
    return paths


def format_why(graph: ResolvedGraph, target: str) -> str:
    paths = why_paths(graph, target)
    if not paths:
        return f"{target} is not present in the resolved graph."
    lines = [f"{target} is installed because:"]
    for path in paths:
        rendered = " -> ".join(graph.packages[name].identifier for name in path)
        lines.append(f"  - {rendered}")
    return "\n".join(lines)


def export_graph(graph: ResolvedGraph, fmt: str = "adjacency") -> str:
    edges = graph.edges()
    if fmt == "adjacency":
        lines = []
        for name in sorted(edges):
            dependencies = ", ".join(edges[name])
            lines.append(f"{name}: {dependencies}" if dependencies else f"{name}:")
        return "\n".join(lines)
    if fmt == "json":
        data = {
            "nodes": [
                {"name": name, "version": str(graph.packages[name].version)}
                for name in sorted(graph.packages)
            ],
            "edges": [
                {"from": name, "to": dependency}
                for name in sorted(edges)
                for dependency in edges[name]
            ],
        }
        return json.dumps(data, indent=2, sort_keys=True)
    if fmt == "dot":
        lines = ["digraph dependencies {"]
        for name in sorted(graph.packages):
            package = graph.packages[name]
            lines.append(f'  "{name}" [label="{package.identifier}"];')
        for name in sorted(edges):
            for dependency in edges[name]:
                lines.append(f'  "{name}" -> "{dependency}";')
        lines.append("}")
        return "\n".join(lines)
    raise GraphError(f"unsupported graph format {fmt!r}")
