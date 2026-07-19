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
from kairos_ontology.core.claim_registry import Claim, ClaimRegistry
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
        has_sources=True, discriminator_subclass=True, is_eligible=True, stubs_enabled=True
    ) == ba.BOUND
    # Unbound discriminator subtype folds.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=True, is_eligible=True, stubs_enabled=True
    ) == ba.FOLDED
    # Unbound eligible claim stubs only when enabled.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=False, is_eligible=True, stubs_enabled=True
    ) == ba.STUB
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=False, is_eligible=True, stubs_enabled=False
    ) == ba.SKIPPED
    # Unbound, unclaimed.
    assert ba.classify_binding(
        has_sources=False, discriminator_subclass=False, is_eligible=False, stubs_enabled=True
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


def test_build_stub_vs_skipped_no_sources():
    g = Graph()
    _class(g, "Client")
    _class(g, "Prospect")
    classes = _cls_dicts("Client", "Prospect")
    mappings = {"table_maps": {}, "column_maps": {}}

    # Client is an eligible claim → STUB when enabled; Prospect is not eligible → SKIPPED.
    analysis = ba.build(
        classes=classes, graph=g, systems=[], mappings=mappings,
        eligible_class_uris={str(NS.Client)}, stubs_enabled=True,
    )
    assert analysis.state(str(NS.Client)) == ba.STUB
    assert analysis.is_aspirational(str(NS.Client))
    assert analysis.state(str(NS.Prospect)) == ba.SKIPPED

    # Flag off → no stubs.
    analysis_off = ba.build(
        classes=classes, graph=g, systems=[], mappings=mappings,
        eligible_class_uris={str(NS.Client)}, stubs_enabled=False,
    )
    assert analysis_off.state(str(NS.Client)) == ba.SKIPPED
    assert not analysis_off.is_aspirational(str(NS.Client))


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


