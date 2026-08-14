# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for ``kairos-ontology next`` (DD-137)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.hub_inspection import _authored_ttl, gather_hub_input_snapshot
from kairos_ontology.core.next_actions import (
    CompileStatus,
    DiscoveryConformanceStatus,
    InputStatus,
    SourceSampleStatus,
)

_HUB = Path(__file__).parent / "scenarios" / "v5-hub"


@pytest.fixture()
def hub(tmp_path: Path) -> Path:
    dest = tmp_path / "hub"
    shutil.copytree(_HUB, dest)
    (dest / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    return dest


def _invoke(hub: Path, monkeypatch, args):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["next", *args])


def _stdout_json(result):
    """Return parsed stdout JSON, proving stdout is clean once stderr is removed.

    The test runner merges stdout+stderr into ``result.output`` while keeping
    ``result.stderr`` separate; at the OS level stdout carries only the JSON.
    """
    stdout = result.output[len(result.stderr) :]
    return json.loads(stdout)


def test_next_json_is_clean_on_stdout_with_banner_on_stderr(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    assert result.exit_code == 0
    payload = _stdout_json(result)  # would raise if stdout were polluted
    assert payload["schema_version"] == 3
    assert payload["compile_ran"] is True
    assert "DD-137" in result.stderr
    kinds = {action["kind"] for action in payload["actions"]}
    assert "compile-emit" in kinds


def test_next_text_reports_inputs_and_actions(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, [])
    assert result.exit_code == 0
    assert "next-action proposal" in result.output
    assert "compile-emit" in result.output
    assert "party" in result.output


def test_next_no_compile_marks_downstream_indeterminate(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--no-compile", "--format", "json"])
    payload = _stdout_json(result)
    assert payload["compile_ran"] is False
    statuses = {action["kind"]: action["status"] for action in payload["actions"]}
    assert statuses.get("run-check") == "indeterminate"
    assert "compile-emit" not in statuses


def test_next_domain_filter_restricts_domains(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--domain", "does-not-exist", "--format", "json"])
    payload = _stdout_json(result)
    domains = {action["domain"] for action in payload["actions"] if action["domain"]}
    assert "party" not in domains


def test_next_hub_not_found_is_operational_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    result = CliRunner().invoke(cli, ["next", "--format", "json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"] == "hub-not-found"


def test_gather_snapshot_reports_passing_domain(hub):
    snapshot = gather_hub_input_snapshot(hub)
    assert snapshot.hub_root == str(hub.resolve())
    party = next(d for d in snapshot.domains if d.domain == "party")
    assert party.ontology is InputStatus.PRESENT
    assert party.has_bindings is True
    assert party.compile_status is CompileStatus.PASSED


def test_gather_snapshot_flags_binding_without_ontology(hub):
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    text = binding.read_text(encoding="utf-8").replace("domain: party", "domain: orphan")
    binding.write_text(text, encoding="utf-8")

    snapshot = gather_hub_input_snapshot(hub)
    assert "orphan" in snapshot.binding_only_domains
    orphan = next(d for d in snapshot.domains if d.domain == "orphan")
    assert orphan.ontology is InputStatus.MISSING
    assert orphan.has_bindings is True


def test_gather_snapshot_observes_emitted_project_and_adapter(hub):
    without = gather_hub_input_snapshot(hub)
    assert without.emitted_dbt_project is InputStatus.MISSING
    assert without.adapter == "fabric"

    project = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    project.mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: hub\n", encoding="utf-8")

    with_emit = gather_hub_input_snapshot(hub)
    assert with_emit.emitted_dbt_project is InputStatus.PRESENT


def test_gather_snapshot_observes_discovery_conformance(hub):
    # v5-hub ships a resolved (mode: interactive) discovery artifact.
    resolved = gather_hub_input_snapshot(hub)
    assert resolved.discovery_conformance is DiscoveryConformanceStatus.VALID

    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.write_text(
        "\n".join(
            [
                "schema_version: 2",
                "generated_by: test",
                "mode: fleet",
                "archetype:\n  id: x\n  confirmed_by: human",
                "core_concepts:",
                "  - uri: u1",
                "    label: One",
                "    decided_by: ai",
                "    needs_confirmation: true",
            ]
        ),
        encoding="utf-8",
    )
    unresolved = gather_hub_input_snapshot(hub)
    assert unresolved.discovery_conformance is DiscoveryConformanceStatus.UNRESOLVED_FLEET


def test_next_surfaces_resolve_discovery_open_questions_action(hub, monkeypatch):
    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.write_text(
        "\n".join(
            [
                "schema_version: 2",
                "generated_by: test",
                "mode: fleet",
                "archetype:\n  id: x\n  confirmed_by: human",
                "core_concepts:",
                "  - uri: u1",
                "    label: One",
                "    decided_by: ai",
                "    needs_confirmation: true",
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    action = next(a for a in payload["actions"] if a["kind"] == "resolve-discovery-open-questions")
    assert action["status"] == "blocking"
    assert action["blocking"] is True
    assert action["skill"] == "kairos-design-discovery"


def test_authored_ttl_rejects_scaffold_templates_regardless_of_naming(tmp_path):
    # Issue #288: init's scaffold uses `glossary-template.ttl` (a `-template.ttl` suffix),
    # not the legacy `*.template` convention — both must be rejected as non-authored.
    assert _authored_ttl(tmp_path / "glossary-template.ttl") is False
    assert _authored_ttl(tmp_path / "foo.template") is False
    assert _authored_ttl(tmp_path / "party-discovery.ttl") is True


def test_gather_snapshot_discovery_ignores_scaffold_template_only(hub):
    # Issue #288: a freshly-scaffolded businessdiscovery/ containing only the init-copied
    # glossary-template.ttl (plus README.md) has zero authored evidence and must report
    # MISSING, not PRESENT — otherwise the DD-148 discovery gate is silently disabled.
    discovery_dir = hub / "businessdiscovery"
    discovery_dir.mkdir()
    (discovery_dir / "glossary-template.ttl").write_text("# scaffold\n", encoding="utf-8")
    (discovery_dir / "README.md").write_text("# discovery\n", encoding="utf-8")

    scaffold_only = gather_hub_input_snapshot(hub)
    assert scaffold_only.discovery is InputStatus.MISSING

    (discovery_dir / "party-discovery.ttl").write_text("# authored\n", encoding="utf-8")
    with_authored = gather_hub_input_snapshot(hub)
    assert with_authored.discovery is InputStatus.PRESENT


def test_next_surfaces_optional_validate_dbt_after_emit(hub, monkeypatch):
    project = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    project.mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: hub\n", encoding="utf-8")

    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    gate = next(a for a in payload["actions"] if a["kind"] == "validate-dbt")
    assert gate["status"] == "optional"
    assert gate["command"] == "kairos-ontology validate-dbt --platform fabric"


# ---------------------------------------------------------------------------
# Issue #298 — source-sample-coverage observation
# ---------------------------------------------------------------------------


def _strip_sample_values(path: Path) -> None:
    # Remove only the `kb:sampleValues "..." ;` predicate-object pair, never the whole
    # line: the fixture's Turtle packs multiple predicates (and the closing `.`) onto one
    # physical line, so deleting the entire line can eat the statement terminator and
    # corrupt the following triple.
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'kb:sampleValues\s+"[^"]*"\s*;\s*', "", text)
    path.write_text(text, encoding="utf-8")


def test_gather_snapshot_source_samples_partial_on_unmodified_fixture(hub):
    # v5-hub ships crm (2 tables, both sampled) + erp (1 table, zero sampled columns).
    snapshot = gather_hub_input_snapshot(hub)
    assert snapshot.source_samples.status is SourceSampleStatus.PARTIAL
    assert snapshot.source_samples.tables_with_samples == 2
    assert snapshot.source_samples.tables_total == 3


def test_gather_snapshot_source_samples_none_when_all_samples_stripped(hub):
    crm = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    erp = hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl"
    _strip_sample_values(crm)
    _strip_sample_values(erp)

    snapshot = gather_hub_input_snapshot(hub)
    assert snapshot.source_samples.status is SourceSampleStatus.NONE
    assert snapshot.source_samples.tables_with_samples == 0
    assert snapshot.source_samples.tables_total == 3


def test_gather_snapshot_source_samples_full_when_every_table_sampled(hub):
    erp = hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl"
    with erp.open("a", encoding="utf-8") as handle:
        handle.write('src:customer_id kb:sampleValues "C-1" .\n')

    snapshot = gather_hub_input_snapshot(hub)
    assert snapshot.source_samples.status is SourceSampleStatus.FULL
    assert snapshot.source_samples.tables_with_samples == 3
    assert snapshot.source_samples.tables_total == 3


def test_gather_snapshot_source_samples_not_applicable_when_sources_missing(tmp_path):
    empty_hub = tmp_path / "empty-hub"
    (empty_hub / "model" / "ontologies").mkdir(parents=True)
    snapshot = gather_hub_input_snapshot(empty_hub)
    assert snapshot.source_samples.status is SourceSampleStatus.NOT_APPLICABLE
    assert snapshot.source_samples.tables_total == 0


def test_next_text_renders_source_sample_suffix(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, [])
    assert "sources:        present (samples: 2/3 tables)" in result.output


def test_next_text_renders_no_sample_evidence_suffix(hub, monkeypatch):
    crm = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    erp = hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl"
    _strip_sample_values(crm)
    _strip_sample_values(erp)

    result = _invoke(hub, monkeypatch, [])
    assert "sources:        present (no sample evidence in 3 table(s))" in result.output


def test_next_json_includes_source_samples_payload(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["source_samples"] == {
        "status": "partial",
        "tables_with_samples": 2,
        "tables_total": 3,
    }
    # unchanged, existing key untouched (contract stability)
    assert payload["inputs"]["sources"] == "present"


def test_next_surfaces_human_decision_required_when_no_samples_at_all(hub, monkeypatch):
    crm = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    erp = hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl"
    _strip_sample_values(crm)
    _strip_sample_values(erp)

    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    design_source_actions = [a for a in payload["actions"] if a["kind"] == "design-source"]
    assert any(a["status"] == "human_decision_required" for a in design_source_actions)


# ---------------------------------------------------------------------------
# Issue #310 — discovery_gate_satisfied surfaced in rendering + JSON
# ---------------------------------------------------------------------------


def test_next_text_shows_gate_satisfied_qualifier_when_conformance_artifact_exists(hub, monkeypatch):
    # v5-hub ships a valid conformance artifact but no businessdiscovery/ narrative.
    result = _invoke(hub, monkeypatch, [])
    assert "discovery:      missing" in result.output
    assert "compile/validate gate satisfied via conformance artifact — DD-148" in result.output


def test_next_json_discovery_fields_consistent_when_gate_satisfied(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["discovery"] == "missing"
    assert payload["inputs"]["discovery_conformance"] == "valid"
    assert payload["inputs"]["discovery_gate_satisfied"] is True
    action = next(a for a in payload["actions"] if a["kind"] == "design-discovery")
    assert action["status"] == "human_decision_required"
    assert action["blocking"] is False


def test_next_text_shows_no_qualifier_when_neither_signal_present(hub, monkeypatch):
    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.unlink()

    result = _invoke(hub, monkeypatch, [])
    assert "discovery:      missing" in result.output
    assert "compile/validate gate satisfied" not in result.output


def test_next_json_discovery_gate_not_satisfied_when_neither_signal_present(hub, monkeypatch):
    artifact_path = hub / "integration" / "discovery" / "core-concepts-conformance.yaml"
    artifact_path.unlink()

    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["discovery"] == "missing"
    assert payload["inputs"]["discovery_conformance"] == "not_run"
    assert payload["inputs"]["discovery_gate_satisfied"] is False
    action = next(a for a in payload["actions"] if a["kind"] == "design-discovery")
    assert action["status"] == "blocking"
    assert action["blocking"] is True


# ---------------------------------------------------------------------------
# Issue #321 — DD-047 inventory-freshness gate surfaced in `next`
# ---------------------------------------------------------------------------


def test_next_text_reports_missing_inventory(hub, monkeypatch):
    # v5-hub's party.ttl has classes but referencemodels-unpacked/ was never generated.
    result = _invoke(hub, monkeypatch, [])
    assert "inventory:      missing" in result.output


def test_next_json_includes_inventory_status_and_blocking_action(hub, monkeypatch):
    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["inventory_status"] == "missing"
    action = next(a for a in payload["actions"] if a["kind"] == "generate-inventory")
    assert action["status"] == "blocking"
    assert action["blocking"] is True
    assert action["command"] == "kairos-ontology generate-inventory"
    assert action["skill"] == "kairos-design-domain"


def test_next_inventory_status_present_once_generated(hub, monkeypatch):
    from kairos_ontology.core.inventory import generate_inventory, inventory_filename, write_inventory

    ttl = hub / "model" / "ontologies" / "party.ttl"
    inv = generate_inventory(ttl, include_specializations=False)
    write_inventory(inv, hub / "referencemodels-unpacked" / inventory_filename(ttl))

    result = _invoke(hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["inventory_status"] == "present"
    assert not any(a["kind"] == "generate-inventory" for a in payload["actions"])


# ---------------------------------------------------------------------------
# Issue #386 — inventory_status must scope to --domain on multi-accelerator hubs
# ---------------------------------------------------------------------------

_MULTI_ACCEL_PARTY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-party: <https://kairos.cnext.eu/ref/party#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" .

ref-party:Party a owl:Class ;
    rdfs:label "Party" .

ref-party:partyName a owl:DatatypeProperty ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .
"""

_MULTI_ACCEL_BOOKING_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-booking: <https://kairos.cnext.eu/ref/booking#> .

<https://kairos.cnext.eu/ref/booking> a owl:Ontology ;
    rdfs:label "Booking" .

ref-booking:Booking a owl:Class ;
    rdfs:label "Booking" .

ref-booking:bookingRef a owl:DatatypeProperty ;
    rdfs:domain ref-booking:Booking ;
    rdfs:range xsd:string .
"""

_MULTI_ACCEL_CATALOG_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog" prefer="public">
  <uri name="https://kairos.cnext.eu/ref/party" uri="ontology-reference-models/party.ttl"/>
  <uri name="https://kairos.cnext.eu/ref/booking" uri="ontology-reference-models/booking.ttl"/>
</catalog>
"""

_PARTY_DATA_DOMAINS_YAML = """\
groups:
  - id: acme-party
    domains:
      - id: party
        name: Party
        imports:
          - uri: https://kairos.cnext.eu/ref/party#
            module: party
"""

_BOOKING_DATA_DOMAINS_YAML = """\
groups:
  - id: acme-logistics
    domains:
      - id: booking
        name: Booking
        imports:
          - uri: https://kairos.cnext.eu/ref/booking#
            module: booking
"""


@pytest.fixture()
def multi_accelerator_hub(tmp_path: Path) -> Path:
    """Two independently-installed accelerator packs, each owning one domain (#386).

    ``party``'s pack (``acme-party``) never gets its inventory generated; ``booking``'s
    pack (``acme-logistics``) does. This is the shape issue #386 complains about: a
    hub with an irrelevant accelerator's stale/missing inventory must not block a
    ``--domain`` query for an unrelated, genuinely-ready domain.
    """
    root = tmp_path / "hub"
    (root / "model" / "ontologies").mkdir(parents=True)
    (root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")

    ref_dir = root / "ontology-reference-models"
    ref_dir.mkdir()
    (ref_dir / "party.ttl").write_text(_MULTI_ACCEL_PARTY_TTL, encoding="utf-8")
    (ref_dir / "booking.ttl").write_text(_MULTI_ACCEL_BOOKING_TTL, encoding="utf-8")

    party_pack = ref_dir / "accelerator-packs" / "acme-party" / "client-hub-blueprint"
    party_pack.mkdir(parents=True)
    (party_pack / "data-domains.yaml").write_text(_PARTY_DATA_DOMAINS_YAML, encoding="utf-8")

    booking_pack = ref_dir / "accelerator-packs" / "acme-logistics" / "client-hub-blueprint"
    booking_pack.mkdir(parents=True)
    (booking_pack / "data-domains.yaml").write_text(_BOOKING_DATA_DOMAINS_YAML, encoding="utf-8")

    (root / "catalog-v001.xml").write_text(_MULTI_ACCEL_CATALOG_XML, encoding="utf-8")

    # Only booking's inventory is generated/fresh. party's is left entirely missing —
    # the "unrelated accelerator" failure a --domain booking query must not see.
    from kairos_ontology.core.inventory import generate_inventory, write_inventory

    inv = generate_inventory(
        ref_dir / "booking.ttl",
        include_specializations=True,
        catalog_path=root / "catalog-v001.xml",
    )
    write_inventory(inv, root / "referencemodels-unpacked" / "booking-inventory.yaml")

    return root


def test_next_domain_scoped_inventory_ignores_unrelated_accelerator(
    multi_accelerator_hub, monkeypatch
):
    # party's accelerator pack never had its inventory generated at all, but the
    # query is scoped to booking (a different, unrelated accelerator pack) — the
    # out-of-scope missing party inventory must not block booking's readiness (#386).
    result = _invoke(
        multi_accelerator_hub, monkeypatch, ["--domain", "booking", "--format", "json"]
    )
    payload = _stdout_json(result)
    assert payload["inputs"]["inventory_status"] == "present"
    assert not any(a["kind"] == "generate-inventory" for a in payload["actions"])


def test_next_domain_scoped_inventory_still_blocks_relevant_gap(
    multi_accelerator_hub, monkeypatch
):
    # party's own inventory really is missing, and the query is scoped to party
    # itself — this must still block. The fix must scope, not blanket-suppress.
    result = _invoke(
        multi_accelerator_hub, monkeypatch, ["--domain", "party", "--format", "json"]
    )
    payload = _stdout_json(result)
    assert payload["inputs"]["inventory_status"] == "missing"
    action = next(a for a in payload["actions"] if a["kind"] == "generate-inventory")
    assert action["blocking"] is True


def test_next_without_domain_filter_reports_unscoped_inventory_status(
    multi_accelerator_hub, monkeypatch
):
    # Regression: omitting --domain (the common case) must behave exactly as
    # before — the plain repo-wide check_inventories() result, unscoped. party's
    # missing inventory blocks even with no domain filter to disambiguate.
    result = _invoke(multi_accelerator_hub, monkeypatch, ["--format", "json"])
    payload = _stdout_json(result)
    assert payload["inputs"]["inventory_status"] == "missing"
    action = next(a for a in payload["actions"] if a["kind"] == "generate-inventory")
    assert action["blocking"] is True
