"""Tests for version and requirement parsing."""

import pytest

from pypm_lab.constraints import VersionConstraint
from pypm_lab.errors import RequirementError, VersionError
from pypm_lab.requirements import parse_requirement, parse_requirement_parts, validate_package_name
from pypm_lab.versions import Version


def test_semver_parsing_and_comparison():
    assert Version.parse("1.2.10") > Version.parse("1.2.3")
    assert str(Version.parse("0.0.1")) == "0.0.1"
    with pytest.raises(VersionError):
        Version.parse("1.2")


@pytest.mark.parametrize(
    ("constraint", "allowed", "rejected"),
    [
        ("1.2.3", "1.2.3", "1.2.4"),
        (">=1.0.0,<2.0.0", "1.5.0", "2.0.0"),
        ("^1.2.3", "1.9.0", "2.0.0"),
        ("^0.2.3", "0.2.9", "0.3.0"),
        ("^0.0.3", "0.0.3", "0.0.4"),
        ("~1.2.3", "1.2.9", "1.3.0"),
    ],
)
def test_constraint_satisfaction_table(constraint, allowed, rejected):
    parsed = VersionConstraint.parse(constraint)
    assert parsed.allows(Version.parse(allowed))
    assert not parsed.allows(Version.parse(rejected))


def test_wildcard_constraint_allows_any_semver():
    parsed = VersionConstraint.parse("*")
    assert parsed.allows(Version.parse("0.0.0"))
    assert parsed.allows(Version.parse("99.99.99"))


def test_requirement_parser_forms():
    requirement = parse_requirement("Alpha@^1.2.0")
    assert requirement.name == "alpha"
    assert requirement.raw_constraint == "^1.2.0"

    split = parse_requirement_parts("bravo", ">=2.0.0,<3.0.0")
    assert split.name == "bravo"
    assert split.constraint.allows(Version.parse("2.1.0"))

    wildcard = parse_requirement("echo@*")
    assert wildcard.name == "echo"
    assert wildcard.raw_constraint == "*"
    assert wildcard.constraint.allows(Version.parse("0.0.0"))


@pytest.mark.parametrize("text", ["", "../alpha", "alpha/beta", ".hidden"])
def test_invalid_package_names(text):
    with pytest.raises(RequirementError):
        validate_package_name(text)


def test_package_name_rejects_separators_with_clear_message():
    with pytest.raises(RequirementError, match="path separators"):
        validate_package_name("alpha/beta")


def test_package_name_allows_interior_dots():
    # "a..b" is an ordinary name, not a path traversal sequence.
    assert validate_package_name("a..b") == "a..b"


def test_missing_requirement_constraint_is_reported():
    with pytest.raises(RequirementError, match="missing constraint"):
        parse_requirement("alpha@")


def test_constraint_intersection_has_no_candidate():
    lower = VersionConstraint.parse(">=2.0.0")
    upper = VersionConstraint.parse("<2.0.0")
    versions = [Version.parse(text) for text in ("1.0.0", "2.0.0", "3.0.0")]

    jointly_allowed = [v for v in versions if lower.allows(v) and upper.allows(v)]

    assert jointly_allowed == []
