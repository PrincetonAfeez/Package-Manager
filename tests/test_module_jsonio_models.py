"""jsonio and models public API smoke tests."""

from __future__ import annotations

import pytest

from pypm_lab.jsonio import loads_no_duplicate_keys
from pypm_lab.models import InstallPlan, PackageVersion, StoreRecord
from pypm_lab.versions import Version

DIGEST = "sha256:" + "0" * 64


def test_loads_no_duplicate_keys_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate key"):
        loads_no_duplicate_keys('{"a": 1, "a": 2}')


def test_package_version_identifier():
    package = PackageVersion(
        name="alpha",
        version=Version.parse("1.2.3"),
        dependencies={"shared": ">=1.0.0"},
        integrity=DIGEST,
        archive="/tmp/alpha.tar.gz",
    )
    assert package.identifier == "alpha@1.2.3"


def test_store_record_to_dict():
    record = StoreRecord(
        name="alpha",
        version="1.0.0",
        integrity=DIGEST,
        tree_hash=DIGEST,
        path="store/alpha/1.0.0",
    )
    payload = record.to_dict()
    assert payload["treeHash"] == DIGEST
    assert payload["path"] == "store/alpha/1.0.0"


def test_install_plan_order():
    plan = InstallPlan(order=("shared", "alpha"))
    assert plan.order == ("shared", "alpha")
