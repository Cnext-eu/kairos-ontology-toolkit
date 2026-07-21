# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the canonical binding analysis (B0).

Covers the pure classifier, the materialization-eligibility helper over a
``ClaimRegistry``, and the ``build`` path (bound / stub / folded / skipped)
grounded in the shared ``compute_source_bindings``.
"""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import OWL

from kairos_ontology.core import binding_analysis as ba
from kairos_ontology.core.claim_registry import Claim, ClaimRegistry, write_registry
from kairos_ontology.core.projections.shared import KAIROS_EXT

NS = Namespace("https://acme.example/client#")


def _class(graph: Graph, local: str) -> str:
    uri = URIRef(NS[local])
    graph.add((uri, RDF.type, OWL.Class))
    graph.add((uri, RDFS.label, Literal(local)))
    return str(uri)


def _cls_dicts(*locals_: str) -> list[dict]:
    return [{"uri": str(NS[loc]), "name": loc, "label": loc, "comment": loc} for loc in locals_]


def test_classify_binding_precedence():
    # Bound always wins, even if also a discriminator subtype.
    assert ba.classify_binding(
        has_sources=True, discriminator_subclass=True, is_eligible=True
    ) == ba.BOUND
    # Unbound discriminator subtype folds.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=True, is_eligible=True
    ) == ba.FOLDED
    # Unbound eligible claim is an aspirational STUB — independent of stub emission.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=False, is_eligible=True
    ) == ba.STUB
    # Unbound, unclaimed.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=False, is_eligible=False
    ) == ba.SKIPPED


def test_materialization_eligible_class_uris():
    reg = ClaimRegistry(
        domain="client",
        claims=[
            Claim(id="c1", type="class", status="approved", disposition="claim",
                  class_uri=str(NS.Client)),
            Claim(id="c2", type="class", status="approved", disposition="specialize",
                  class_uri=str(NS.CorporateClient)),
            Claim(id="c3", type="reference_data", status="approved", disposition="claim",
                  class_uri=str(NS.Country)),
            # Excluded: proposed (not approved)
            Claim(id="c4", type="class", status="proposed", disposition="claim",
                  class_uri=str(NS.Prospect)),
            # Excluded: rejected (not approved)
            Claim(id="c4b", type="class", status="rejected", disposition="claim",
                  class_uri=str(NS.Rejected)),
            # Excluded: gap disposition (DEC-5)
            Claim(id="c5", type="class", status="approved", disposition="gap",
                  class_uri=str(NS.Missing)),
            # Excluded: passthrough
            Claim(id="c6", type="class", status="approved", disposition="passthrough",
                  class_uri=str(NS.Note)),
            # Excluded: property claim (not class-like)
            Claim(id="c7", type="property", status="approved", disposition="claim",
                  property_uri=str(NS.email)),
        ],
    )
    eligible = ba.materialization_eligible_class_uris(reg)
    assert eligible == {str(NS.Client), str(NS.CorporateClient), str(NS.Country)}


def test_approved_imported_class_uris():
    reg = ClaimRegistry(
        domain="client",
        claims=[
            # Included: approved + imported + claim/specialize.
            Claim(id="i1", type="class", status="approved", disposition="claim",
                  origin="imported", class_uri=str(NS.Party)),
            Claim(id="i2", type="class", status="approved", disposition="specialize",
                  origin="imported", class_uri=str(NS.Organisation)),
            # Excluded: authored origin (local, not imported).
            Claim(id="i3", type="class", status="approved", disposition="claim",
                  origin="authored", class_uri=str(NS.Client)),
            # Excluded: proposed / rejected status.
            Claim(id="i4", type="class", status="proposed", disposition="claim",
                  origin="imported", class_uri=str(NS.Prospect)),
            Claim(id="i5", type="class", status="rejected", disposition="claim",
                  origin="imported", class_uri=str(NS.Rejected)),
            # Excluded: gap disposition.
            Claim(id="i6", type="class", status="approved", disposition="gap",
                  origin="imported", class_uri=str(NS.Missing)),
        ],
    )
    assert ba.approved_imported_class_uris(reg) == {str(NS.Party), str(NS.Organisation)}


def test_analyze_hub_includes_catalog_loaded_approved_import(tmp_path):
    """Status/release analysis includes claimed classes loaded through the hub catalog."""
    hub = tmp_path / "hub"
    ontologies = hub / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "client.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://acme.example/client> a owl:Ontology ;\n"
        "    owl:imports <https://ref.example/party> .\n",
        encoding="utf-8",
    )
    (ontologies / "_party.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<https://ref.example/party> a owl:Ontology .\n"
        "<https://ref.example/party#TradeParty> a owl:Class ;\n"
        '    rdfs:label "Trade Party" .\n',
        encoding="utf-8",
    )
    (hub / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="https://ref.example/party" '
        'uri="model/ontologies/_party.ttl"/>\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    write_registry(
        ClaimRegistry(
            domain="client",
            claims=[
                Claim(
                    id="trade-party",
                    type="class",
                    status="approved",
                    disposition="claim",
                    origin="imported",
                    class_uri="https://ref.example/party#TradeParty",
                )
            ],
        ),
        hub / "model" / "claims" / "client-claims.yaml",
    )

    snapshot = ba.analyze_domain_from_hub(hub, "client")

    assert snapshot is not None
    assert snapshot.aspirational_names() == ["TradeParty"]


def test_build_aspirational_decoupled_from_stub_emission():
    """STUB/aspirational/release facts are derived independently of ``stubs_enabled``.

    Only *emission* (``should_emit_stub``) and *materialization* (``is_materialized``)
    follow the flag; status/release can therefore reason with stubs off.
    """
    g = Graph()
    _class(g, "Client")
    _class(g, "Prospect")
    classes = _cls_dicts("Client", "Prospect")
    mappings = {"table_maps": {}, "column_maps": {}}

    for stubs_enabled in (True, False):
        analysis = ba.build(
            classes=classes, graph=g, systems=[], mappings=mappings,
            eligible_class_uris={str(NS.Client)}, stubs_enabled=stubs_enabled,
        )
        # Client is eligible + unbound -> aspirational STUB regardless of the flag.
        assert analysis.state(str(NS.Client)) == ba.STUB
        assert analysis.is_aspirational(str(NS.Client))
        assert analysis.is_release_blocking(str(NS.Client))
        assert analysis.aspirational_class_uris() == [str(NS.Client)]
        assert analysis.release_blocking_class_uris() == [str(NS.Client)]
        # Prospect is not eligible -> SKIPPED, never aspirational/release-blocking.
        assert analysis.state(str(NS.Prospect)) == ba.SKIPPED
        assert not analysis.is_aspirational(str(NS.Prospect))
        assert not analysis.is_release_blocking(str(NS.Prospect))
        # Emission + materialization are the only flag-sensitive facts.
        assert analysis.should_emit_stub(str(NS.Client)) is stubs_enabled
        assert analysis.is_materialized(str(NS.Client)) is stubs_enabled
        assert analysis.materialized_class_uris() == (
            [str(NS.Client)] if stubs_enabled else []
        )


def test_build_bound_beats_stub():
    g = Graph()
    _class(g, "Client")
    classes = _cls_dicts("Client")
    tbl_uri = "https://acme.example/bronze/adminpulse#tblClient"
    systems = [{
        "system_label": "AdminPulse",
        "tables": [{"uri": tbl_uri, "name": "tbl_client", "columns": []}],
    }]
    mappings = {
        "table_maps": {tbl_uri: [{"target_uri": str(NS.Client), "mapping_type": "direct"}]},
        "column_maps": {},
    }
    analysis = ba.build(
        classes=classes, graph=g, systems=systems, mappings=mappings,
        eligible_class_uris={str(NS.Client)}, stubs_enabled=True,
    )
    # Even though Client is eligible + stubs enabled, it is BOUND (has a source).
    assert analysis.state(str(NS.Client)) == ba.BOUND
    assert not analysis.is_aspirational(str(NS.Client))


def test_build_discriminator_subclass_folds():
    g = Graph()
    parent = _class(g, "Client")
    sub = _class(g, "CorporateClient")
    g.add((URIRef(sub), RDFS.subClassOf, URIRef(parent)))
    g.add((URIRef(parent), KAIROS_EXT.inheritanceStrategy, Literal("discriminator")))
    classes = _cls_dicts("Client", "CorporateClient")
    mappings = {"table_maps": {}, "column_maps": {}}
    analysis = ba.build(
        classes=classes, graph=g, systems=[], mappings=mappings,
        eligible_class_uris={sub}, stubs_enabled=True,
    )
    # Unbound discriminator subtype folds into parent rather than stubbing.
    assert analysis.state(sub) == ba.FOLDED


def test_build_folding_beats_stub_even_when_eligible():
    # An eligible discriminator subtype with stubs enabled still FOLDS (no stub):
    # folding precedence must win so we don't emit a duplicate physical model.
    g = Graph()
    parent = _class(g, "Client")
    sub = _class(g, "CorporateClient")
    g.add((URIRef(sub), RDFS.subClassOf, URIRef(parent)))
    g.add((URIRef(parent), KAIROS_EXT.inheritanceStrategy, Literal("discriminator")))
    classes = _cls_dicts("Client", "CorporateClient")
    mappings = {"table_maps": {}, "column_maps": {}}
    analysis = ba.build(
        classes=classes, graph=g, systems=[], mappings=mappings,
        eligible_class_uris={sub, parent}, stubs_enabled=True,
    )
    assert analysis.state(sub) == ba.FOLDED
    assert not analysis.is_aspirational(sub)
    # The unbound parent (not a subtype) is a genuine stub.
    assert analysis.state(parent) == ba.STUB


def test_build_mapped_child_under_discriminator_parent_folds_source_to_parent():
    # A discriminator subtype's source is routed (folded) into the projected parent:
    # the child has no own physical model (FOLDED); the parent becomes BOUND.
    g = Graph()
    parent = _class(g, "Client")
    sub = _class(g, "CorporateClient")
    g.add((URIRef(sub), RDFS.subClassOf, URIRef(parent)))
    g.add((URIRef(parent), KAIROS_EXT.inheritanceStrategy, Literal("discriminator")))
    classes = _cls_dicts("Client", "CorporateClient")
    tbl_uri = "https://acme.example/bronze/adminpulse#tblCorp"
    systems = [{
        "system_label": "AdminPulse",
        "tables": [{"uri": tbl_uri, "name": "tbl_corp", "columns": []}],
    }]
    mappings = {
        "table_maps": {tbl_uri: [{"target_uri": sub, "mapping_type": "direct"}]},
        "column_maps": {},
    }
    analysis = ba.build(
        classes=classes, graph=g, systems=systems, mappings=mappings,
        eligible_class_uris={sub}, stubs_enabled=True,
    )
    assert analysis.state(sub) == ba.FOLDED
    assert analysis.state(parent) == ba.BOUND


def test_build_reasons_and_order_are_deterministic():
    """Each state carries a stable reason string and state lists are sorted."""
    g = Graph()
    parent = _class(g, "Client")
    sub = _class(g, "CorporateClient")
    g.add((URIRef(sub), RDFS.subClassOf, URIRef(parent)))
    g.add((URIRef(parent), KAIROS_EXT.inheritanceStrategy, Literal("discriminator")))
    bound = _class(g, "Account")
    _class(g, "Prospect")
    classes = _cls_dicts("Client", "CorporateClient", "Account", "Prospect")
    tbl_uri = "https://acme.example/bronze/adminpulse#tblAccount"
    systems = [{
        "system_label": "AdminPulse",
        "tables": [{"uri": tbl_uri, "name": "tbl_account", "columns": []}],
    }]
    mappings = {
        "table_maps": {tbl_uri: [{"target_uri": bound, "mapping_type": "direct"}]},
        "column_maps": {},
    }
    analysis = ba.build(
        classes=classes, graph=g, systems=systems, mappings=mappings,
        eligible_class_uris={str(NS.Client)},
    )
    # Deterministic per-state reason text.
    assert analysis.reason(bound) == "bound to bronze source(s)"
    assert analysis.reason(sub) == "S3 discriminator subclass of Client"
    assert analysis.reason(str(NS.Client)) == (
        "approved claim, no bronze mapping (aspirational)"
    )
    assert analysis.reason(str(NS.Prospect)) == (
        "no bronze mapping and no approving claim"
    )
    # State lists are sorted (deterministic order across runs).
    assert analysis.class_uris_in_state(ba.BOUND) == sorted(
        analysis.class_uris_in_state(ba.BOUND)
    )
    assert analysis.aspirational_class_uris() == [str(NS.Client)]
    # A repeated build produces identical states/reasons (byte-stable).
    again = ba.build(
        classes=classes, graph=g, systems=systems, mappings=mappings,
        eligible_class_uris={str(NS.Client)},
    )
    assert analysis.states == again.states
    assert analysis.reasons == again.reasons

