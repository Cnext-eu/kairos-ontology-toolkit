# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Relationship cardinality: declared in OWL, drawn from what each layer guarantees (DD-241).

#999: every ER renderer hard-coded ``||--o{``, so an optional foreign key was drawn as
mandatory and a one-to-one link could not be drawn at all; the DDD diagram drew one end;
and nothing said whether a relationship bound belongs in OWL or SHACL, so one hub declared
all 29 in both.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_ontology.core.cardinality_audit import (
    CONTRADICTS,
    DUPLICATES,
    SHACL_ONLY,
    audit_shacl_cardinality,
)
from kairos_ontology.core.compiler.kernel import _relationship_cardinality_diagnostics
from kairos_ontology.core.projections.dbt.silver_contract import canonical_data
from kairos_ontology.core.projections.dbt.specs import optional_field
from kairos_ontology.core.projections.shared import ER_EDGE_PATTERN, er_edge


@pytest.mark.parametrize(
    ("required", "one_to_one", "token"),
    [
        (True, False, "||--o{"),
        (False, False, "|o--o{"),
        (True, True, "||--o|"),
        (False, True, "|o--o|"),
    ],
)
def test_the_edge_token(required, one_to_one, token):
    import re

    assert er_edge(required, one_to_one) == token
    assert re.fullmatch(ER_EDGE_PATTERN, token)


def test_an_unset_optional_field_is_invisible_to_hashes_and_json():
    """A new spec field must not change every hub's model fingerprints and dbt package."""

    @dataclass(frozen=True)
    class Before:
        name: str

    @dataclass(frozen=True)
    class After:
        name: str
        extra: str = optional_field()

    assert canonical_data(After("x")) == canonical_data(Before("x"))
    assert canonical_data(After("x", "one-to-one")) == {"name": "x", "extra": "one-to-one"}


# --------------------------------------------------------------------------- SHACL audit

_ONTOLOGY = """
@prefix : <https://example.test/shop#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.test/shop> a owl:Ontology .
:Order a owl:Class ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :placedBy ; owl:minCardinality 1 ] ,
                    [ a owl:Restriction ; owl:onProperty :shipsTo ; owl:maxCardinality 1 ] .
:Customer a owl:Class . :Address a owl:Class . :Store a owl:Class .
:placedBy a owl:ObjectProperty ; rdfs:domain :Order ; rdfs:range :Customer .
:shipsTo a owl:ObjectProperty ; rdfs:domain :Order ; rdfs:range :Address .
:soldAt a owl:ObjectProperty ; rdfs:domain :Order ; rdfs:range :Store .
:orderNumber a owl:DatatypeProperty ; rdfs:domain :Order ; rdfs:range xsd:string .
"""

_SHAPES = """
@prefix : <https://example.test/shop#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
:OrderShape a sh:NodeShape ; sh:targetClass :Order ;
    sh:property [ sh:path :placedBy ; sh:minCount 1 ] ;
    sh:property [ sh:path :shipsTo ; sh:maxCount 2 ] ;
    sh:property [ sh:path :soldAt ; sh:minCount 1 ] ;
    sh:property [ sh:path :orderNumber ; sh:minCount 1 ] .
"""


def _audit(tmp_path: Path, shapes: str = _SHAPES, name: str = "shop.shacl.ttl"):
    ontologies = tmp_path / "ontologies"
    shapes_dir = tmp_path / "shapes"
    ontologies.mkdir()
    shapes_dir.mkdir()
    (ontologies / "shop.ttl").write_text(_ONTOLOGY, encoding="utf-8")
    (shapes_dir / name).write_text(shapes, encoding="utf-8")
    from rdflib import Graph

    from kairos_ontology.core.cardinality_audit import hand_authored_shapes

    parsed = [
        (path.name.removesuffix(".shacl.ttl"), Graph().parse(path, format="turtle"))
        for path in hand_authored_shapes(shapes_dir)
    ]
    return audit_shacl_cardinality([ontologies / "shop.ttl"], parsed)


def test_shacl_counts_on_relationships_are_judged_against_owl(tmp_path):
    found = {item.message.split(":")[0]: item.code for item in _audit(tmp_path)}
    assert found == {
        "Order.placedBy": DUPLICATES,  # min 1 in both
        "Order.shipsTo": CONTRADICTS,  # SHACL max 2, OWL max 1
        "Order.soldAt": SHACL_ONLY,  # no OWL bound
    }


def test_a_datatype_property_count_is_shacls_job(tmp_path):
    assert not any("orderNumber" in item.message for item in _audit(tmp_path))


def test_the_toolkit_managed_shapes_are_not_audited(tmp_path):
    assert _audit(tmp_path, name="kairos-prep-shapes.shacl.ttl") == []


def test_every_finding_is_a_warning(tmp_path):
    assert {item.level for item in _audit(tmp_path)} == {"warning"}


# --------------------------------------------------------------------- compile warnings


def _warn(bounds, *, missing_parent="null", cardinality="many-to-one"):
    """``bounds`` is ``(target min, source max)``, as ``resolve_scope`` precomputes it."""
    binding = SimpleNamespace(target_class=":Order", source_path="order.binding.yaml")
    relationship = SimpleNamespace(
        property=":placedBy", missing_parent=missing_parent, cardinality=cardinality
    )
    context = SimpleNamespace(
        klass=lambda ref: SimpleNamespace(uri="urn:Order"),
        relationship_bounds={("urn:Order", "urn:placedBy"): bounds},
    )
    prop = SimpleNamespace(uri="urn:placedBy")
    return [
        item.code
        for item in _relationship_cardinality_diagnostics(
            binding, relationship, "/relationships/0", prop, context
        )
    ]


def test_an_optional_binding_of_a_required_relationship_warns():
    assert _warn((1, None)) == ["relationship.optional-but-ontology-requires"]
    assert _warn((1, None), missing_parent="error") == []


def test_a_one_to_one_binding_the_ontology_does_not_bound_warns():
    assert _warn((None, None), cardinality="one-to-one", missing_parent="error") == [
        "relationship.one-to-one-not-in-ontology"
    ]
    assert _warn((None, 1), cardinality="one-to-one", missing_parent="error") == []


def test_an_unbounded_relationship_is_silent():
    assert _warn((None, None)) == []


# ------------------------------------------------------------------ Silver, end to end


def _billing_artifacts(tmp_path, cardinality="many-to-one"):
    import shutil

    from kairos_ontology.core.compiler.kernel import build_compile_plan

    hub = tmp_path / "hub"
    shutil.copytree(Path(__file__).parent / "scenarios" / "v5-product-hub", hub)
    binding = hub / "integration" / "bindings" / "invoice.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "cardinality: many-to-one", f"cardinality: {cardinality}"
        ),
        encoding="utf-8",
    )
    plan = build_compile_plan(hub, "billing")
    assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
    return plan


def _erd_and_constraints(plan):
    import json

    from kairos_ontology.core.projections.medallion_silver_projector import (
        _constraint_data,
        _render_erd,
    )

    physical = plan.materialization_plan.silver
    return _render_erd(physical), json.dumps(_constraint_data(physical))


def test_a_required_many_to_one_is_drawn_mandatory_and_adds_no_json_key(tmp_path):
    erd, constraints = _erd_and_constraints(_billing_artifacts(tmp_path))
    assert "CUSTOMER ||--o{ INVOICE" in erd  # missingParent: error, so NOT NULL
    assert "relationship_cardinality" not in constraints


def test_a_one_to_one_binding_reaches_the_erd_and_the_constraints(tmp_path):
    erd, constraints = _erd_and_constraints(_billing_artifacts(tmp_path, "one-to-one"))
    assert "CUSTOMER ||--o| INVOICE" in erd
    assert '"relationship_cardinality": "one-to-one"' in constraints
