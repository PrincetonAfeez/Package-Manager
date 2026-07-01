"""Property-based tests for the version/constraint layer and resolver determinism."""

import hypothesis.strategies as st
from hypothesis import given, settings

from pypm_lab.constraints import VersionConstraint
from pypm_lab.lockfile import Lockfile
from pypm_lab.registry import InMemoryRegistry
from pypm_lab.requirements import parse_requirement
from pypm_lab.resolver import Resolver
from pypm_lab.versions import Version


def versions() -> st.SearchStrategy[Version]:
    part = st.integers(min_value=0, max_value=30)
    return st.builds(Version, part, part, part)


@given(versions())
def test_version_str_roundtrip(version: Version) -> None:
    assert Version.parse(str(version)) == version


def _caret_upper(base: Version) -> Version:
    # Independent oracle for caret semantics documented in the README.
    if base.major > 0:
        return Version(base.major + 1, 0, 0)
    if base.minor > 0:
        return Version(0, base.minor + 1, 0)
    return Version(0, 0, base.patch + 1)


@given(versions(), versions())
def test_caret_matches_documented_bounds(base: Version, candidate: Version) -> None:
    allowed = VersionConstraint.parse(f"^{base}").allows(candidate)
    assert allowed == (base <= candidate < _caret_upper(base))


@given(versions(), versions())
def test_tilde_matches_documented_bounds(base: Version, candidate: Version) -> None:
    upper = Version(base.major, base.minor + 1, 0)
    allowed = VersionConstraint.parse(f"~{base}").allows(candidate)
    assert allowed == (base <= candidate < upper)


@given(versions(), versions(), versions())
def test_range_constraint_semantics(low: Version, high: Version, candidate: Version) -> None:
    constraint = VersionConstraint.parse(f">={low},<{high}")
    assert constraint.allows(candidate) == (low <= candidate < high)


_REQUIREMENTS = ["alpha@^1.0.0", "bravo@>=2.0.0,<3.0.0", "shared@>=1.0.0"]


def _make_registry() -> InMemoryRegistry:
    return InMemoryRegistry(
        {
            "alpha": {
                "1.2.4": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}},
                "1.3.0": {"dependencies": {"shared": ">=2.0.0,<3.0.0"}},
            },
            "bravo": {"2.1.0": {"dependencies": {"shared": ">=1.0.0,<2.0.0"}}},
            "shared": {"1.5.0": {"dependencies": {}}, "2.0.0": {"dependencies": {}}},
        }
    )


@given(st.permutations(range(len(_REQUIREMENTS))))
@settings(max_examples=50)
def test_resolution_invariant_to_requirement_order(order: tuple[int, ...]) -> None:
    canonical = Resolver(_make_registry()).resolve(
        [parse_requirement(text) for text in _REQUIREMENTS]
    )
    permuted = Resolver(_make_registry()).resolve(
        [parse_requirement(_REQUIREMENTS[index]) for index in order]
    )
    assert Lockfile.from_graph(permuted.graph).dumps() == Lockfile.from_graph(canonical.graph).dumps()
