# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Class-level disposition ledger (DD-231, #847).

The class-side sibling of the source-table ledger, minus its four defects: a malformed
ledger raises instead of reading as empty, `decided_by` is closed in core, `clear` is
reachable, and `list --undecided` exists. Adoption is opt-in then binding: warnings until
the ledger exists, errors afterwards.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.class_disposition import class_disposition_group
from kairos_ontology.core import class_disposition as cd

PARTY = textwrap.dedent(
    """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix party: <https://acme.example/ont/party#> .
    @prefix bsp: <https://kairosflow.ai/ont/bsp/party#> .
    <https://acme.example/ont/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
    party:Party a owl:Class ; rdfs:label "Party" .
    party:Customer a owl:Class ; rdfs:subClassOf party:Party ; rdfs:label "Customer" .
    party:Supplier a owl:Class ; rdfs:subClassOf party:Party ; rdfs:label "Supplier" .
    party:PostalAddress a owl:Class ; rdfs:label "Postal Address" .
    # A reference-model IRI re-declared locally for a label: not the hub's class to decide.
    bsp:TradeParty a owl:Class ; rdfs:label "Trade Party" .
    """
)

BILLING = textwrap.dedent(
    """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix billing: <https://acme.example/ont/billing#> .
    <https://acme.example/ont/billing> a owl:Ontology ; owl:versionInfo "1.0.0" .
    billing:Invoice a owl:Class ; rdfs:label "Invoice" .
    """
)

NS = "https://acme.example/ont/party#"


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "ontologies" / "party.ttl").write_text(PARTY, encoding="utf-8")
    (hub / "model" / "ontologies" / "billing.ttl").write_text(BILLING, encoding="utf-8")
    (hub / "model" / "ontologies" / "_master.ttl").write_text("", encoding="utf-8")
    return hub


def _bind(hub: Path, name: str, token: str, domain: str = "party") -> None:
    directory = hub / "integration" / "bindings"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {"name": name, "domain": domain},
        "source": {"relation": f"crm.{name}"},
        "target": {"class": token},
    }
    (directory / f"{name}.binding.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestPopulation:
    def test_only_classes_in_the_hubs_own_namespaces_count(self, tmp_path):
        graphs = cd.load_domain_files(_hub(tmp_path))
        iris = [item.iri for item in cd.hub_classes(graphs)]
        assert iris == [
            "https://acme.example/ont/billing#Invoice",
            f"{NS}Customer",
            f"{NS}Party",
            f"{NS}PostalAddress",
            f"{NS}Supplier",
        ]
        assert cd.hub_classes(graphs)[1].domain == "party"

    def test_non_domain_files_are_skipped(self, tmp_path):
        hub = _hub(tmp_path)
        (hub / "model" / "ontologies" / "party-silver-ext.ttl").write_text(PARTY, encoding="utf-8")
        assert set(cd.load_domain_files(hub)) == {"party", "billing"}

    def test_qname_resolves_through_the_domain_files_prefixes(self, tmp_path):
        graphs = cd.load_domain_files(_hub(tmp_path))
        assert cd.resolve_class_token("party:Customer", graphs, "party") == f"{NS}Customer"
        assert cd.resolve_class_token("party:Customer", graphs, "billing") == f"{NS}Customer"
        assert cd.resolve_class_token(f"{NS}Customer", graphs) == f"{NS}Customer"
        assert cd.resolve_class_token("nope:Customer", graphs) is None


class TestAudit:
    def test_without_a_ledger_undecided_classes_are_warnings(self, tmp_path):
        report = cd.audit_class_dispositions(hub_root=_hub(tmp_path))
        assert not report.ledger_present
        assert report.classes_total == 5 and report.classes_undecided == 5
        assert {d.level for d in report.diagnostics} == {"warning"}
        assert all(d.code == cd.CODE_UNDECIDED for d in report.diagnostics)
        assert not report.is_blocking
        assert any("class-disposition init" in note for note in report.notices)

    def test_binding_derives_bound_and_bound_via_subclass(self, tmp_path):
        hub = _hub(tmp_path)
        _bind(hub, "customers", "party:Customer")
        report = cd.audit_class_dispositions(hub_root=hub)
        assert report.statuses[f"{NS}Customer"] == cd.STATUS_BOUND
        assert report.statuses[f"{NS}Party"] == cd.STATUS_BOUND_VIA_SUBCLASS
        assert f"{NS}Supplier" not in report.statuses  # no bound-via-superclass, on purpose
        assert report.classes_bound == 2 and report.classes_undecided == 3

    def test_once_the_ledger_exists_undecided_is_an_error(self, tmp_path):
        hub = _hub(tmp_path)
        cd.init_ledger(hub)
        report = cd.audit_class_dispositions(hub_root=hub)
        assert report.ledger_present and report.is_blocking
        assert len(report.errors) == 5
        assert "class-disposition set --class" in report.errors[0].remediation

    def test_recorded_dispositions_count_as_decided(self, tmp_path):
        hub = _hub(tmp_path)
        cd.record_class_disposition(
            hub_root=hub,
            class_iri="party:PostalAddress",
            disposition="architecture-only",
            rationale="Its own bounded context; physically resident in party.",
        )
        cd.record_class_disposition(hub_root=hub, class_iri=f"{NS}Party", disposition="abstract")
        report = cd.audit_class_dispositions(hub_root=hub)
        assert report.statuses[f"{NS}PostalAddress"] == "architecture-only"
        assert report.statuses[f"{NS}Party"] == "abstract"
        assert report.classes_disposed == 2
        assert report.coverage() == 0.4

    def test_hand_written_bad_entries_are_errors(self, tmp_path):
        hub = _hub(tmp_path)
        cd.init_ledger(hub)
        cd.ledger_path(hub).write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "classes": [
                        {"class": f"{NS}Party", "disposition": "parked", "decided_by": "user"},
                        {"class": f"{NS}Customer", "disposition": "deferred", "decided_by": "user"},
                        {
                            "class": f"{NS}Supplier",
                            "disposition": "abstract",
                            "decided_by": "copilot",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        report = cd.audit_class_dispositions(hub_root=hub)
        codes = {d.class_iri: d.code for d in report.errors}
        assert codes[f"{NS}Party"] == cd.CODE_UNKNOWN_VALUE
        assert codes[f"{NS}Customer"] == cd.CODE_MISSING_RATIONALE
        assert codes[f"{NS}Supplier"] == cd.CODE_UNKNOWN_DECIDER

    def test_a_stale_entry_for_a_now_bound_class_warns(self, tmp_path):
        hub = _hub(tmp_path)
        cd.record_class_disposition(
            hub_root=hub, class_iri="party:Customer", disposition="deferred", rationale="later"
        )
        _bind(hub, "customers", "party:Customer")
        report = cd.audit_class_dispositions(hub_root=hub)
        stale = [d for d in report.diagnostics if d.code == cd.CODE_STALE]
        assert len(stale) == 1 and "customers.binding.yaml" in stale[0].message
        assert report.statuses[f"{NS}Customer"] == cd.STATUS_BOUND

    def test_an_entry_for_an_unknown_class_warns(self, tmp_path):
        hub = _hub(tmp_path)
        cd.init_ledger(hub)
        cd.ledger_path(hub).write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "classes": [
                        {"class": f"{NS}Gone", "disposition": "abstract", "decided_by": "user"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        report = cd.audit_class_dispositions(hub_root=hub)
        assert any(d.code == cd.CODE_UNKNOWN_CLASS for d in report.warnings)

    def test_a_malformed_ledger_raises_instead_of_reading_as_empty(self, tmp_path):
        hub = _hub(tmp_path)
        cd.ledger_path(hub).parent.mkdir(parents=True)
        cd.ledger_path(hub).write_text("classes: [\n", encoding="utf-8")
        with pytest.raises(cd.ClassDispositionError):
            cd.audit_class_dispositions(hub_root=hub)
        cd.ledger_path(hub).write_text("schema_version: 99\nclasses: []\n", encoding="utf-8")
        with pytest.raises(cd.ClassDispositionError, match="schema_version"):
            cd.audit_class_dispositions(hub_root=hub)

    def test_no_classes_yields_a_notice_not_a_failure(self, tmp_path):
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        report = cd.audit_class_dispositions(hub_root=hub)
        assert report.classes_total == 0 and not report.is_blocking and report.notices


class TestRecordAndClear:
    def test_record_validates_value_rationale_decider_and_class(self, tmp_path):
        hub = _hub(tmp_path)
        with pytest.raises(cd.ClassDispositionError, match="Unknown disposition"):
            cd.record_class_disposition(hub_root=hub, class_iri="party:Party", disposition="parked")
        with pytest.raises(cd.ClassDispositionError, match="requires a rationale"):
            cd.record_class_disposition(
                hub_root=hub, class_iri="party:Party", disposition="deferred"
            )
        with pytest.raises(cd.ClassDispositionError, match="decided_by"):
            cd.record_class_disposition(
                hub_root=hub, class_iri="party:Party", disposition="abstract", decided_by="copilot"
            )
        with pytest.raises(cd.ClassDispositionError, match="not a class this hub declares"):
            cd.record_class_disposition(
                hub_root=hub, class_iri="party:Nope", disposition="abstract"
            )
        with pytest.raises(cd.ClassDispositionError, match="not a class this hub declares"):
            cd.record_class_disposition(
                hub_root=hub,
                class_iri="https://kairosflow.ai/ont/bsp/party#TradeParty",
                disposition="abstract",
            )

    def test_the_ledger_is_sorted_and_replaces_in_place(self, tmp_path):
        hub = _hub(tmp_path)
        cd.record_class_disposition(
            hub_root=hub, class_iri="party:Supplier", disposition="abstract"
        )
        cd.record_class_disposition(hub_root=hub, class_iri="party:Party", disposition="abstract")
        cd.record_class_disposition(
            hub_root=hub,
            class_iri="party:Party",
            disposition="deferred",
            rationale="bind once the CRM export lands",
            decided_by="ai",
            evidence=("HUB-DD-20260920-abc123",),
        )
        document = yaml.safe_load(cd.ledger_path(hub).read_text(encoding="utf-8"))
        assert document["schema_version"] == 1 and document["generated_by"] == cd.GENERATED_BY
        assert [entry["class"] for entry in document["classes"]] == [f"{NS}Party", f"{NS}Supplier"]
        party = document["classes"][0]
        assert party["disposition"] == "deferred" and party["decided_by"] == "ai"
        assert party["domain"] == "party" and party["evidence"] == ["HUB-DD-20260920-abc123"]

    def test_clear_by_class_disposition_or_decider(self, tmp_path):
        hub = _hub(tmp_path)
        cd.record_class_disposition(
            hub_root=hub, class_iri="party:Supplier", disposition="abstract"
        )
        cd.record_class_disposition(
            hub_root=hub,
            class_iri="party:Party",
            disposition="deferred",
            rationale="x",
            decided_by="ai",
        )
        preview = cd.clear_class_dispositions(hub, decided_by="ai", dry_run=True)
        assert preview["removed"] == 1 and preview["classes"] == [f"{NS}Party"]
        assert len(cd.load_ledger(hub)[1]) == 2  # dry run wrote nothing
        assert cd.clear_class_dispositions(hub, classes={"party:Supplier"})["removed"] == 1
        assert list(cd.load_ledger(hub)[1]) == [f"{NS}Party"]

    def test_init_is_idempotent(self, tmp_path):
        hub = _hub(tmp_path)
        path, created = cd.init_ledger(hub)
        assert created and path == cd.ledger_path(hub)
        assert cd.init_ledger(hub) == (path, False)


class TestCli:
    def test_set_list_and_clear_round_trip(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        monkeypatch.chdir(hub)
        runner = CliRunner()
        result = runner.invoke(
            class_disposition_group,
            [
                "set",
                "--class",
                "party:PostalAddress",
                "--disposition",
                "architecture-only",
                "--rationale",
                "own context, physically in party",
            ],
        )
        assert result.exit_code == 0, result.output
        result = runner.invoke(class_disposition_group, ["list", "--undecided"])
        assert result.exit_code == 0, result.output
        assert "PostalAddress" not in result.output and "Customer" in result.output
        result = runner.invoke(class_disposition_group, ["list", "--format", "json"])
        assert result.exit_code == 0, result.output
        assert '"ledger_present": true' in result.output
        result = runner.invoke(class_disposition_group, ["clear", "--class", "party:PostalAddress"])
        assert result.exit_code == 0, result.output
        assert "removed 1" in result.output

    def test_set_rejects_a_missing_rationale_with_a_clean_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(_hub(tmp_path))
        result = CliRunner().invoke(
            class_disposition_group, ["set", "--class", "party:Party", "--disposition", "deferred"]
        )
        assert result.exit_code != 0
        assert "requires a rationale" in result.output

    def test_clear_needs_a_filter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(_hub(tmp_path))
        result = CliRunner().invoke(class_disposition_group, ["clear"])
        assert result.exit_code != 0 and "at least one of" in result.output

    def test_init_lists_what_now_needs_a_decision(self, tmp_path, monkeypatch):
        monkeypatch.chdir(_hub(tmp_path))
        result = CliRunner().invoke(class_disposition_group, ["init"])
        assert result.exit_code == 0, result.output
        assert "created" in result.output and "5 class(es) now need a decision" in result.output
