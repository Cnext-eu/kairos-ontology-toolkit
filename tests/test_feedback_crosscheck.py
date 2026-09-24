# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""analyse-sources names the tables open feedback records discuss (#695).

A re-run of analyse-sources contradicted a detailed recorded review in five places and
said nothing, because no stage read the HUB-FB-* records. These pin that each overlap is
surfaced beside the domain the run assigned, and that resolved records and incidental
substrings stay quiet.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.feedback_crosscheck import load_assignments, tables_in_open_feedback


def _record(folder, record_id, status, body):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{record_id}.md").write_text(
        "---\n"
        "type: Modeling Feedback\n"
        f"id: {record_id}\n"
        "title: Party source review\n"
        "area: party\n"
        f"status: {status}\n"
        "generated:\n  by: kairos-ontology-toolkit/5.22.0\n  at: 2026-09-24T00:00:00Z\n"
        "sources: []\n"
        "---\n\n"
        f"# Observation\n\n{body}\n",
        encoding="utf-8",
    )


def _repo(tmp_path):
    hub = tmp_path / "ontology-hub"
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "src-tms.affinity.yaml").write_text(
        yaml.safe_dump({"system": "tms", "schema_version": 2, "tables": [
            {"table": "partyaddress", "domain": "party"},
            {"table": "partymisc", "domain": "party"},
            {"table": "orders", "domain": "booking"},
        ]}),
        encoding="utf-8",
    )
    feedback = tmp_path / ".import" / "modeling" / "feedback"
    return hub, analysis, feedback


def test_a_table_an_open_record_discusses_is_named_with_its_new_domain(tmp_path):
    hub, analysis, feedback = _repo(tmp_path)
    _record(feedback, "HUB-FB-20260901-party", "open",
            "PartyAddress is not party: the location half belongs to reference-data.")

    mentions = tables_in_open_feedback(hub, load_assignments(analysis))

    assert [m.describe() for m in mentions] == [
        "HUB-FB-20260901-party: tms.partyaddress -> party"
    ]


def test_resolved_records_and_substrings_stay_quiet(tmp_path):
    hub, analysis, feedback = _repo(tmp_path)
    _record(feedback, "HUB-FB-20260901-old", "resolved", "partymisc was split long ago.")
    _record(feedback, "HUB-FB-20260902-new", "open", "The partyaddresses view is fine.")

    assert tables_in_open_feedback(hub, load_assignments(analysis)) == []


def test_a_hub_with_no_feedback_reports_nothing(tmp_path):
    hub, analysis, _ = _repo(tmp_path)
    assert tables_in_open_feedback(hub, load_assignments(analysis)) == []
