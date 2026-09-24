# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Role groups survive alignment and reach the decision point (#938).

`group_columns_by_role` found consignee/shipper/notify blocks for the alignment prompt
and then threw them away, so on one hub 78 denormalised party columns were ruled
`deferred` one name at a time, with no command naming the normative pattern that governs
exactly that shape. These pin the chain: the artifact keeps the groups, the report
carries the role, and the sheet names `qualified-role-assignment`.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.alignment_report import build_alignment_report
from kairos_ontology.core.gap_decisions import ROLE_PATTERN, build_decision_sheet
from kairos_ontology.core.propose_alignment import (
    DomainAlignment,
    TableAlignment,
    alignment_to_dict,
    group_columns_by_role,
)


def test_role_groups_are_found_and_persisted():
    columns = [{"name": n} for n in (
        "consignee_code", "consignee_name", "consignee_zip",
        "shipper_code", "shipper_name", "weight", "volume", "booking_date",
    )]
    groups, _ = group_columns_by_role(columns)
    assert {token for token, _ in groups} == {"consignee", "shipper"}

    table = TableAlignment(
        system="tms", table="bookings", ref_class="Booking", ref_class_confidence=0.9,
        columns=[], custom_columns=[{"column": "consignee_zip", "role_group": "consignee"}],
        role_groups=[{"role": "consignee", "columns": ["consignee_code", "consignee_name"]}],
    )
    document = alignment_to_dict(DomainAlignment(domain="booking", domain_uris=[], generated_at="t", model_used="m", tables=[table]))
    (entry,) = document["tables"]
    assert entry["role_groups"] == [
        {"role": "consignee", "columns": ["consignee_code", "consignee_name"]}
    ]


def test_a_table_without_role_groups_is_unchanged():
    table = TableAlignment(
        system="tms", table="t", ref_class="C", ref_class_confidence=0.9,
        columns=[], custom_columns=[],
    )
    (entry,) = alignment_to_dict(DomainAlignment(domain="d", domain_uris=[], generated_at="t", model_used="m", tables=[table]))["tables"]
    assert "role_groups" not in entry


def _hub(tmp_path):
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    custom = [
        {"column": f"{role}_{attr}", "data_type": "varchar", "role_group": role}
        for role in ("consignee", "shipper", "notify")
        for attr in ("zip", "city", "street")
    ] + [{"column": "weight_note", "data_type": "varchar"}]
    (analysis / "dom-booking.alignment.yaml").write_text(
        yaml.safe_dump({"domain": "booking", "tables": [{
            "system": "tms", "table": "bookings", "ref_class": "Booking",
            "columns": [], "custom_columns": custom,
        }]}),
        encoding="utf-8",
    )
    return tmp_path


def test_the_report_carries_the_role(tmp_path):
    hub = _hub(tmp_path)
    report = build_alignment_report(hub / "integration" / "sources" / "_analysis", hub_root=hub)
    roles = {c.column: c.role_group for d in report.domains for c in d.unmapped}
    assert roles["consignee_zip"] == "consignee"
    assert roles["weight_note"] == ""


def test_the_sheet_names_the_governing_pattern(tmp_path):
    sheet = build_decision_sheet(_hub(tmp_path))

    rows = {e["column"]: e for e in sheet["decisions"]}
    for family in sheet["families"]:
        for member in family["members"]:
            rows.setdefault(member, family)

    consignee = rows["consignee_zip"]
    assert consignee["governing_pattern"] == ROLE_PATTERN
    assert "consignee" in consignee["role_groups"]
    assert "governing_pattern" not in rows["weight_note"]
