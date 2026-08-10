# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``design-landscape`` (read-only design synthesis report).

Fixture pattern follows ``tests/test_scaffold_binding.py`` / ``tests/test_fit_report.py``: a
tiny synthetic accelerator module (no real reference-model checkout) wired together with a
hub-local XML catalog and a ``data-domains.yaml`` module profile -- exactly the shape a real
accelerator-backed hub uses, just minimal.

The fixture deliberately exercises all five classification buckets with one class each:

* ``TradeParty``   -- 2 source tables + confirmed (``conforms``) discovery demand, and an
                      existing binding (full-IRI, direct accelerator target) + one BI/TMDL
                      concept-mapping reference -> ``canonical-candidate``.
* ``Invoice``       -- 1 source table, no discovery entry, no binding -> ``passthrough-candidate``.
* ``Payment``       -- 0 source tables, discovery outcome ``partial`` (evidence, not confirmed),
                      no binding -> ``demanded-but-unbound``.
* ``LoyaltyCard``   -- 0 source tables, discovery outcome ``not-applicable`` (an SME explicitly
                      said "we don't need this" -- real evidence exists, but it must not
                      rescue the class into a demand bucket), no binding -> ``no-evidence``.
                      This is the "zero evidence anywhere, not silently omitted" case.
* ``ShippingAddress`` -- 0 source tables, no discovery entry, bound via a *local* subclass
                      (``party:ShipTo rdfs:subClassOf acc:ShippingAddress``, DD-144's normal
                      pattern) -> ``bound-but-undemanded``.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.design_landscape import (
    DesignLandscapeError,
    run_design_landscape,
)

_ACCELERATOR_ONTOLOGY_IRI = "https://example.test/accelerator"
_ACCELERATOR_NAMESPACE = "https://example.test/accelerator#"

_ACCELERATOR_TTL = textwrap.dedent(
    """
    @prefix acc: <https://example.test/accelerator#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    <https://example.test/accelerator> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Test accelerator module" .

    acc:TradeParty a owl:Class ; rdfs:label "Trade Party" .
    acc:tradePartyId a owl:DatatypeProperty ; rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:partyName a owl:DatatypeProperty ; rdfs:domain acc:TradeParty ; rdfs:range xsd:string .

    acc:Invoice a owl:Class ; rdfs:label "Invoice" .
    acc:invoiceId a owl:DatatypeProperty ; rdfs:domain acc:Invoice ; rdfs:range xsd:string .
    acc:invoiceAmount a owl:DatatypeProperty ; rdfs:domain acc:Invoice ; rdfs:range xsd:decimal .

    acc:Payment a owl:Class ; rdfs:label "Payment" .
    acc:paymentId a owl:DatatypeProperty ; rdfs:domain acc:Payment ; rdfs:range xsd:string .

    acc:LoyaltyCard a owl:Class ; rdfs:label "Loyalty Card" .
    acc:cardNumber a owl:DatatypeProperty ; rdfs:domain acc:LoyaltyCard ; rdfs:range xsd:string .

    acc:ShippingAddress a owl:Class ; rdfs:label "Shipping Address" .
    acc:addressLine a owl:DatatypeProperty ; rdfs:domain acc:ShippingAddress ; rdfs:range xsd:string .
    """
).strip()

_DOMAIN_ONTOLOGY_TTL = textwrap.dedent(
    """
    @prefix party: <https://example.test/hub/party#> .
    @prefix acc: <https://example.test/accelerator#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    <https://example.test/hub/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      owl:imports <https://example.test/accelerator> .

    party:ShipTo a owl:Class ; rdfs:label "Ship To" ;
      rdfs:subClassOf acc:ShippingAddress .
    """
).strip()

_DATA_DOMAINS_YAML = textwrap.dedent(
    """
    module_profiles:
      - id: party
        ontology_iri: https://example.test/accelerator
        version_pin: "1.0.0"
        term_namespaces:
          - https://example.test/accelerator#
    groups:
      - domains:
          - id: party
            imports:
              - profile: party
    """
).strip()

_ALIGNMENT_YAML = textwrap.dedent(
    """
    schema_version: 3
    algorithm_version: 1
    domain: party
    domain_uris: []
    generated_at: "2026-01-01T00:00:00Z"
    model_used: test
    source_sha256: ""
    reference_rollup: []
    tables:
      - system: crm
        table: organisations
        ref_class: TradeParty
        ref_class_confidence: 0.9
        custom_columns: []
        columns:
          - column: org_id
            data_type: varchar(50)
            ref_class: TradeParty
            ref_property: tradePartyId
            alignment: exact
            confidence: 0.95
            rationale: ""
          - column: name
            data_type: varchar(200)
            ref_class: TradeParty
            ref_property: partyName
            alignment: semantic
            confidence: 0.8
            rationale: ""
      - system: erp
        table: business_partners
        ref_class: TradeParty
        ref_class_confidence: 0.85
        custom_columns: []
        columns:
          - column: bp_id
            data_type: varchar(50)
            ref_class: TradeParty
            ref_property: tradePartyId
            alignment: exact
            confidence: 0.9
            rationale: ""
      - system: billing
        table: invoices
        ref_class: Invoice
        ref_class_confidence: 0.9
        custom_columns: []
        columns:
          - column: invoice_id
            data_type: varchar(50)
            ref_class: Invoice
            ref_property: invoiceId
            alignment: exact
            confidence: 0.95
            rationale: ""
    """
).strip()

_CONFORMANCE_YAML = textwrap.dedent(
    """
    schema_version: 1
    generated_by: test
    generated_at: "2026-01-01T00:00:00Z"
    archetype:
      id: test-archetype
      label: Test Archetype
      source: test-archetype.yaml
      catalog_hash: sha256:test
      concept_set_hash: sha256:test-concepts
    refmodels_version: null
    discovery_doc: null
    ref_model_modules: []
    core_concepts:
      - uri: https://example.test/accelerator#TradeParty
        label: Trade Party
        tier: required
        outcome: conforms
      - uri: https://example.test/accelerator#Payment
        label: Payment
        tier: recommended
        outcome: partial
      - uri: https://example.test/accelerator#LoyaltyCard
        label: Loyalty Card
        tier: optional
        outcome: not-applicable
    topology_confirmations: []
    cardinality_answers: []
    scorecard: {}
    """
).strip()

_TRADE_PARTY_BINDING = textwrap.dedent(
    """
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-organisation
      domain: party
    source:
      relation: crm.organisations
    target:
      class: "https://example.test/accelerator#TradeParty"
    grain:
      columns: [org_id]
    identity:
      strategy: source-natural
      sourceKey: [org_id]
    load:
      mode: full-refresh
    fields:
      - property: "https://example.test/accelerator#tradePartyId"
        expression: org_id
    """
).strip()

_SHIP_TO_BINDING = textwrap.dedent(
    """
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-ship-to
      domain: party
      tier: passthrough
    source:
      relation: crm.ship_to
    target:
      class: party:ShipTo
    grain:
      columns: [ship_to_id]
    identity:
      strategy: source-natural
      sourceKey: [ship_to_id]
    load:
      mode: full-refresh
    fields:
      - property: acc:addressLine
        expression: address_line
    """
).strip()

_CONCEPT_MAPPING_YAML = textwrap.dedent(
    """
    schema_version: "1"
    model_name: SalesModel
    generated_at: "2026-01-01T00:00:00Z"
    tables:
      - tmdl_name: Organisations
        type: table
        columns: [OrgId, OrgName]
        measures: []
        domain: party
        reference_model_match: TradeParty
        action: use
        notes: ""
      - tmdl_name: Notes
        type: table
        columns: [NoteId]
        measures: []
        domain: ""
        reference_model_match: ""
        action: ""
        notes: ""
    relationships: []
    """
).strip()


def _build_hub(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal hub + sibling reference-models checkout. Returns (hub_root, ref_models_dir)."""
    hub_root = tmp_path / "ontology-hub"
    ref_models_dir = tmp_path / "ontology-reference-models"

    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources" / "_analysis").mkdir(parents=True)
    (hub_root / "integration" / "discovery" / "bi").mkdir(parents=True)
    (hub_root / "integration" / "bindings").mkdir(parents=True)

    (hub_root / "model" / "ontologies" / "party.ttl").write_text(
        _DOMAIN_ONTOLOGY_TTL, encoding="utf-8"
    )

    accelerator_ttl_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "ontologies" / "party.ttl"
    )
    accelerator_ttl_path.parent.mkdir(parents=True)
    accelerator_ttl_path.write_text(_ACCELERATOR_TTL, encoding="utf-8")

    data_domains_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data_domains_path.parent.mkdir(parents=True)
    data_domains_path.write_text(_DATA_DOMAINS_YAML, encoding="utf-8")

    catalog_path = hub_root / "catalog-v001.xml"
    catalog_path.write_text(
        textwrap.dedent(
            f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
              <uri name="{_ACCELERATOR_ONTOLOGY_IRI}"
                   uri="../ontology-reference-models/accelerator-packs/acme/ontologies/party.ttl"/>
            </catalog>
            """
        ).strip(),
        encoding="utf-8",
    )

    (hub_root / "integration" / "sources" / "_analysis" / "party-alignment.yaml").write_text(
        _ALIGNMENT_YAML, encoding="utf-8"
    )
    (hub_root / "integration" / "discovery" / "core-concepts-conformance.yaml").write_text(
        _CONFORMANCE_YAML, encoding="utf-8"
    )
    (hub_root / "integration" / "bindings" / "trade-party.binding.yaml").write_text(
        _TRADE_PARTY_BINDING, encoding="utf-8"
    )
    (hub_root / "integration" / "bindings" / "ship-to.binding.yaml").write_text(
        _SHIP_TO_BINDING, encoding="utf-8"
    )
    (hub_root / "integration" / "discovery" / "bi" / "salesmodel-concept-mapping.yaml").write_text(
        _CONCEPT_MAPPING_YAML, encoding="utf-8"
    )

    return hub_root, ref_models_dir


def _run(tmp_path: Path, **overrides):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    kwargs = dict(hub_root=hub_root, ref_models_dir=ref_models_dir)
    kwargs.update(overrides)
    return run_design_landscape(**kwargs), hub_root, ref_models_dir


def _by_name(result, name: str):
    return next(item for item in result.classes if item.class_name == name)


# ---------------------------------------------------------------------------
# Classification buckets
# ---------------------------------------------------------------------------


def test_classification_buckets_per_controlled_input(tmp_path):
    result, _, _ = _run(tmp_path)

    names = {item.class_name: item for item in result.classes}
    assert set(names) == {"TradeParty", "Invoice", "Payment", "LoyaltyCard", "ShippingAddress"}

    trade_party = names["TradeParty"]
    assert trade_party.classification == "canonical-candidate"
    assert trade_party.source_count == 2
    assert trade_party.bound is True
    assert trade_party.discovery.outcome == "conforms"
    assert trade_party.discovery.confirmed is True
    assert trade_party.populated_property_count == 2
    assert trade_party.unpopulated_property_count == 0

    invoice = names["Invoice"]
    assert invoice.classification == "passthrough-candidate"
    assert invoice.source_count == 1
    assert invoice.bound is False
    assert invoice.discovery is None
    assert invoice.populated_property_count == 1
    assert invoice.unpopulated_property_count == 1

    payment = names["Payment"]
    assert payment.classification == "demanded-but-unbound"
    assert payment.source_count == 0
    assert payment.bound is False
    assert payment.discovery.outcome == "partial"
    assert payment.discovery.confirmed is False
    assert payment.rank == 1  # sole backlog entry

    loyalty_card = names["LoyaltyCard"]
    assert loyalty_card.classification == "no-evidence"
    assert loyalty_card.source_count == 0
    assert loyalty_card.bound is False
    # Evidence *was* recorded (an SME explicitly said "not applicable") -- it must still
    # be visible, just never treated as demand.
    assert loyalty_card.discovery is not None
    assert loyalty_card.discovery.outcome == "not-applicable"
    assert loyalty_card.rank is None

    shipping_address = names["ShippingAddress"]
    assert shipping_address.classification == "bound-but-undemanded"
    assert shipping_address.source_count == 0
    assert shipping_address.bound is True
    assert shipping_address.discovery is None
    # Resolved via the local subclass ancestor walk (party:ShipTo -> acc:ShippingAddress).
    assert len(shipping_address.bindings) == 1


def test_zero_evidence_class_is_not_silently_omitted(tmp_path):
    result, _, _ = _run(tmp_path)
    loyalty_card = _by_name(result, "LoyaltyCard")
    assert loyalty_card.classification == "no-evidence"
    # It must actually be present in the report, not dropped.
    assert loyalty_card.class_uri == f"{_ACCELERATOR_NAMESPACE}LoyaltyCard"


# ---------------------------------------------------------------------------
# BI/TMDL evidence is structurally separate (constraint 1: advisory, never fact)
# ---------------------------------------------------------------------------


def test_bi_weight_is_structurally_separate_and_advisory_only(tmp_path):
    result, _, _ = _run(tmp_path)
    trade_party = _by_name(result, "TradeParty")

    assert len(trade_party.bi_weight) == 1
    assert trade_party.bi_weight[0].reference_model_match == "TradeParty"
    assert trade_party.bi_weight[0].tmdl_table == "Organisations"

    payload = trade_party.to_dict()
    # bi_weight lives in its own top-level key, distinct from source_coverage and
    # discovery_demand -- never merged into either.
    assert set(payload.keys()) >= {
        "source_coverage",
        "discovery_demand",
        "bi_weight",
        "binding_state",
    }
    assert payload["bi_weight"]["advisory_only"] is True
    assert payload["bi_weight"]["reference_count"] == 1
    # Never present inside source_coverage or discovery_demand.
    assert "bi_weight" not in payload["source_coverage"]
    assert "reference_model_match" not in json.dumps(payload["source_coverage"])
    assert "reference_model_match" not in json.dumps(payload["discovery_demand"])

    # A class with zero BI signals still carries the (empty) advisory field, never omits it.
    invoice = _by_name(result, "Invoice")
    invoice_payload = invoice.to_dict()
    assert invoice_payload["bi_weight"] == {
        "advisory_only": True,
        "reference_count": 0,
        "signals": [],
    }

    # An unfilled TMDL mapping row is a known, reported gap -- never silently dropped nor
    # promoted to fact.
    assert any("empty reference_model_match" in gap for gap in result.gaps)


def test_bi_weight_never_used_for_classification(tmp_path):
    """A class with ONLY BI weight (no source/discovery/binding) still ends up no-evidence."""
    result, hub_root, ref_models_dir = _run(tmp_path)
    trade_party = _by_name(result, "TradeParty")
    assert trade_party.classification == "canonical-candidate"
    # Proof BI weight is not a classification input: re-run with the BI concept-mapping
    # file removed entirely -- TradeParty's classification (driven only by source_count and
    # confirmed discovery demand) must be unchanged.
    (hub_root / "integration" / "discovery" / "bi" / "salesmodel-concept-mapping.yaml").unlink()
    result_without_bi = run_design_landscape(hub_root=hub_root, ref_models_dir=ref_models_dir)
    trade_party_without_bi = _by_name(result_without_bi, "TradeParty")
    assert trade_party_without_bi.classification == "canonical-candidate"
    assert trade_party_without_bi.bi_weight == ()


# ---------------------------------------------------------------------------
# --format json round-trip
# ---------------------------------------------------------------------------


def test_result_to_dict_round_trips_json(tmp_path):
    result, _, _ = _run(tmp_path)
    payload = result.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)

    assert decoded["schema_version"] == 1
    assert decoded["accelerator"] == "acme"
    assert len(decoded["classes"]) == 5
    assert "advisory" in decoded and "advisory only" in decoded["advisory"]


def test_cli_design_landscape_json_format(tmp_path, monkeypatch):
    hub_root, _ = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)

    result = CliRunner().invoke(cli, ["design-landscape", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["accelerator"] == "acme"
    class_names = {item["class_name"] for item in payload["classes"]}
    assert class_names == {"TradeParty", "Invoice", "Payment", "LoyaltyCard", "ShippingAddress"}


def test_cli_design_landscape_text_format_mentions_advisory(tmp_path, monkeypatch):
    hub_root, _ = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)

    result = CliRunner().invoke(cli, ["design-landscape"])

    assert result.exit_code == 0, result.output
    assert "advisory only" in result.output
    assert "canonical-candidate" in result.output


# ---------------------------------------------------------------------------
# Degrade gracefully / error handling
# ---------------------------------------------------------------------------


def test_no_ref_models_dir_raises_design_landscape_error(tmp_path):
    hub_root, _ = _build_hub(tmp_path)
    try:
        run_design_landscape(hub_root=hub_root, ref_models_dir=None)
    except DesignLandscapeError as exc:
        assert "reference-models" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected DesignLandscapeError")


def test_missing_evidence_inputs_are_reported_as_gaps_not_crashes(tmp_path):
    hub_root = tmp_path / "ontology-hub"
    ref_models_dir = tmp_path / "ontology-reference-models"
    (hub_root / "model" / "ontologies").mkdir(parents=True)

    accelerator_ttl_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "ontologies" / "party.ttl"
    )
    accelerator_ttl_path.parent.mkdir(parents=True)
    accelerator_ttl_path.write_text(_ACCELERATOR_TTL, encoding="utf-8")
    data_domains_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data_domains_path.parent.mkdir(parents=True)
    data_domains_path.write_text(_DATA_DOMAINS_YAML, encoding="utf-8")
    catalog_path = hub_root / "catalog-v001.xml"
    catalog_path.write_text(
        textwrap.dedent(
            f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
              <uri name="{_ACCELERATOR_ONTOLOGY_IRI}"
                   uri="../ontology-reference-models/accelerator-packs/acme/ontologies/party.ttl"/>
            </catalog>
            """
        ).strip(),
        encoding="utf-8",
    )

    result = run_design_landscape(hub_root=hub_root, ref_models_dir=ref_models_dir)

    # No source tables, no discovery artifact, no bindings anywhere -- degrade gracefully.
    assert result.classes == ()
    assert any("propose-alignment" in gap for gap in result.gaps)
    assert any("discovery-conformance" in gap for gap in result.gaps)
    assert any("binding" in gap.lower() for gap in result.gaps)


# ---------------------------------------------------------------------------
# DD-103 boundary: no raw TTL reads in this module.
# ---------------------------------------------------------------------------


def test_no_raw_ttl_reads_in_design_landscape_module():
    from tests.test_ttl_access_boundary import _find_violations

    module_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "kairos_ontology"
        / "core"
        / "design_landscape.py"
    )
    assert module_path.is_file()
    assert _find_violations(module_path) == []
