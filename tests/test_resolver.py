import pytest

from pypm_lab.lockfile import Lockfile
from pypm_lab.registry import InMemoryRegistry
from pypm_lab.requirements import parse_requirement
from pypm_lab.resolver import ResolutionFailed, Resolver


def test_diamond_dependency_resolves_to_one_shared_version():
    registry = InMemoryRegistry(
        {
            "alpha": {
                "1.2.4": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}},
            },
            "bravo": {
                "2.1.0": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}},
            },
            "shared": {
                "1.5.0": {"dependencies": {}},
                "2.0.0": {"dependencies": {}},
            },
        }
    )
    result = Resolver(registry).resolve(
        [
            parse_requirement("alpha@^1.0.0"),
            parse_requirement("bravo@>=2.0.0,<3.0.0"),
        ]
    )

    assert str(result.graph.packages["shared"].version) == "1.5.0"
    assert sorted(result.graph.packages) == ["alpha", "bravo", "shared"]


def test_backtracking_selects_older_root_when_newest_conflicts():
    registry = InMemoryRegistry(
        {
            "alpha": {
                "1.3.0": {"dependencies": {"shared": ">=2.0.0,<3.0.0"}},
                "1.2.4": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}},
            },
            "bravo": {
                "1.0.0": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}},
            },
            "shared": {
                "2.1.0": {"dependencies": {}},
                "1.5.0": {"dependencies": {}},
            },
        }
    )
    result = Resolver(registry, trace=True).resolve(
        [parse_requirement("alpha@^1.0.0"), parse_requirement("bravo@1.0.0")]
    )

    assert str(result.graph.packages["alpha"].version) == "1.2.4"
    assert any("rejecting alpha@1.3.0" in line for line in result.trace)


def test_conflict_explanation_includes_constraint_sources():
    registry = InMemoryRegistry(
        {
            "alpha": {"1.0.0": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}}},
            "bravo": {"1.0.0": {"dependencies": {"shared": ">=2.0.0,<3.0.0"}}},
            "shared": {
                "1.5.0": {"dependencies": {}},
                "2.5.0": {"dependencies": {}},
            },
        }
    )

    with pytest.raises(ResolutionFailed) as exc:
        Resolver(registry).resolve(
            [parse_requirement("alpha@1.0.0"), parse_requirement("bravo@1.0.0")]
        )

    explanation = exc.value.conflict.explain()
    assert "Could not resolve shared." in explanation
    assert ">=1.0.0,<2.0.0 by alpha@1.0.0" in explanation
    assert ">=2.0.0,<3.0.0 by bravo@1.0.0" in explanation


def test_cycle_detection_is_reported():
    registry = InMemoryRegistry(
        {
            "alpha": {"1.0.0": {"dependencies": {"bravo": "1.0.0"}}},
            "bravo": {"1.0.0": {"dependencies": {"alpha": "1.0.0"}}},
        }
    )

    with pytest.raises(ResolutionFailed) as exc:
        Resolver(registry).resolve([parse_requirement("alpha@1.0.0")])

    assert "cycle detected" in exc.value.conflict.explain()


def test_resolver_output_and_lockfile_are_deterministic():
    registry = InMemoryRegistry(
        {
            "alpha": {"1.0.0": {"dependencies": {"shared": "1.0.0"}}},
            "shared": {"1.0.0": {"dependencies": {}}},
        }
    )
    requirements = [parse_requirement("alpha@1.0.0")]

    first = Resolver(registry).resolve(requirements)
    second = Resolver(registry, trace=True).resolve(requirements)

    assert Lockfile.from_graph(first.graph).dumps() == Lockfile.from_graph(second.graph).dumps()
    assert second.trace


def test_trace_does_not_change_resolved_graph():
    registry = InMemoryRegistry(
        {
            "alpha": {"1.2.4": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}}},
            "bravo": {"2.1.0": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}}},
            "shared": {"1.5.0": {"dependencies": {}}, "2.0.0": {"dependencies": {}}},
        }
    )
    requirements = [parse_requirement("alpha@^1.0.0"), parse_requirement("bravo@>=2.0.0,<3.0.0")]

    untraced = Resolver(registry, trace=False).resolve(requirements)
    traced = Resolver(registry, trace=True).resolve(requirements)

    assert Lockfile.from_graph(untraced.graph).dumps() == Lockfile.from_graph(traced.graph).dumps()
    assert traced.trace and not untraced.trace


def test_cycle_conflict_has_first_class_message():
    registry = InMemoryRegistry(
        {
            "alpha": {"1.0.0": {"dependencies": {"bravo": "1.0.0"}}},
            "bravo": {"1.0.0": {"dependencies": {"alpha": "1.0.0"}}},
        }
    )

    with pytest.raises(ResolutionFailed) as exc:
        Resolver(registry).resolve([parse_requirement("alpha@1.0.0")])

    assert "Dependency cycle detected: alpha -> bravo -> alpha." in exc.value.conflict.explain()
