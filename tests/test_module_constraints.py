"""Exhaustive constraints, versions, and requirements tests."""

from __future__ import annotations

import pytest

from pypm_lab.constraints import Comparator, VersionConstraint, parse_constraint
from pypm_lab.errors import RequirementError, VersionError
from pypm_lab.requirements import parse_requirement, parse_requirement_parts, validate_package_name
from pypm_lab.versions import Version, parse_version


def test_version_negative_part_rejected():
    with pytest.raises(VersionError, match="non-negative"):
        Version(-1, 0, 0)


def test_parse_version_alias():
    assert parse_version("1.2.3") == Version.parse("1.2.3")


def test_comparator_allows_all_operators():
    v10 = Version.parse("1.0.0")
    v20 = Version.parse("2.0.0")
    assert Comparator(">", v10).allows(v20)
    assert not Comparator(">", v20).allows(v10)
    assert Comparator("<", v20).allows(v10)
    assert Comparator("<=", v10).allows(v10)
    assert Comparator("==", v10).allows(v10)
    assert str(Comparator("==", v10)) == "1.0.0"
    assert str(Comparator(">=", v10)) == ">=1.0.0"


def test_version_constraint_any():
    any_constraint = VersionConstraint.any()
    assert any_constraint.allows(Version.parse("99.99.99"))


def test_version_constraint_wildcard():
    assert VersionConstraint.parse("*").allows(Version.parse("0.0.0"))


def test_version_constraint_caret_and_tilde():
    assert VersionConstraint.parse("^0.2.3").allows(Version.parse("0.2.9"))
    assert not VersionConstraint.parse("^0.2.3").allows(Version.parse("0.3.0"))


def test_version_constraint_allows_all():
    versions = [Version.parse("1.0.0"), Version.parse("2.0.0")]
    allowed = VersionConstraint.parse(">=1.5.0").allows_all(versions)
    assert allowed == [Version.parse("2.0.0")]


def test_parse_constraint_alias():
    assert parse_constraint("1.0.0").allows(Version.parse("1.0.0"))


def test_comparator_equals_sign_normalized():
    assert VersionConstraint.parse("=1.0.0").allows(Version.parse("1.0.0"))


def test_requirement_malformed_without_at():
    with pytest.raises(RequirementError, match="malformed requirement"):
        parse_requirement("alpha-only")


def test_requirement_invalid_constraint_wrapped():
    with pytest.raises(RequirementError, match="invalid constraint"):
        parse_requirement_parts("alpha", ">>1.0.0")


def test_requirement_source_and_raw_preserved():
    req = parse_requirement_parts("alpha", "1.0.0", source="test", raw="custom")
    assert req.source == "test"
    assert req.raw == "custom"


def test_validate_package_name_missing():
    with pytest.raises(RequirementError, match="missing package name"):
        validate_package_name("   ")


def test_validate_package_name_leading_trailing_dot():
    with pytest.raises(RequirementError, match="invalid package name"):
        validate_package_name(".hidden")
