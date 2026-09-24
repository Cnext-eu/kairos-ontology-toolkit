# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`validate` checks every externalReference key against its parent's binding (#934).

The compile check reads only the parent's Silver contract, and most hubs author none, so
on them a cross-domain join naming the parent's *source* column (instead of the column it
emits) passed compile, emit and the sample audit, and failed in the warehouse.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.external_reference_audit import audit_external_references
from tests.scenarios.test_scenario_v5 import (
    _add_billing_contract,
    _add_external_reference_fixture,
    _copy_hub,
)


def _set_key(hub, column):
    path = hub / "integration" / "bindings" / "customer.binding.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    relationship = data["relationships"][0]
    relationship["externalReference"]["key"][0]["column"] = column
    relationship["join"][0]["foreign"] = column
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_a_key_the_parent_emits_is_clean(tmp_path):
    hub = _copy_hub(tmp_path)
    _add_external_reference_fixture(hub)

    report = audit_external_references(hub)

    assert report.checked == 1
    assert report.findings == []


def test_a_key_naming_the_parents_source_column_is_reported(tmp_path):
    """The field shape: the parent carries `code` through `fields:` as `account_id`."""
    hub = _copy_hub(tmp_path)
    _add_external_reference_fixture(hub)
    _set_key(hub, "code")

    report = audit_external_references(hub)

    assert [(f.column, f.parent) for f in report.findings] == [("code", "billing.account")]
    message = report.findings[0].message
    assert "account_id" in message, "name what the parent does emit, or it cannot be acted on"
    assert "output" in message


def test_a_contracted_parent_is_left_to_compile(tmp_path):
    """A contract can pin names the binding does not show; compile is the authority."""
    hub = _copy_hub(tmp_path)
    _add_external_reference_fixture(hub)
    _add_billing_contract(hub, column_name="account_ref")
    _set_key(hub, "code")

    assert audit_external_references(hub).findings == []


def test_a_parent_bound_nowhere_in_the_hub_is_named_not_guessed(tmp_path):
    hub = _copy_hub(tmp_path)
    _add_external_reference_fixture(hub)
    (hub / "integration" / "bindings" / "account.binding.yaml").unlink()

    report = audit_external_references(hub)

    assert report.findings == []
    assert report.to_dict()["unresolved_parents"] == ["billing.account"]
