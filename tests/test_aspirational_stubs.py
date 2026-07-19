# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for aspirational Silver stub emission (target-first stub → bind loop).

Covers the flag-gated behaviour of ``generate_dbt_artifacts``:

* feature-off (default) is byte-identical to today — an approved-but-unmapped
  class produces **no** ``.sql`` model;
* feature-on emits a typed, zero-row stub (``where 1 = 0`` + ``cast(null as ...)``)
  for eligible classes and marks it ``meta.is_aspirational`` in the schema YAML;
* binding a source (a mapping) always wins — a mapped class projects a real model,
  never a stub, even with the flag on.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)

NS = "http://kairos.example/ontology/"

ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ;
        rdfs:label "Client" ;
        rdfs:comment "A client entity" .

    ex:clientId a owl:DatatypeProperty ;
        rdfs:label "client ID" ;
        rdfs:comment "Unique identifier" ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:string .

    ex:isActive a owl:DatatypeProperty ;
        rdfs:label "is active" ;
        rdfs:comment "Whether the client is active" ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:boolean .
""")


@pytest.fixture
def graph():
    g = Graph()
    g.parse(data=ONTOLOGY_TTL, format="turtle")
    return g


@pytest.fixture
def classes():
    return [{
        "uri": f"{NS}Client",
        "name": "Client",
        "label": "Client",
        "comment": "A client entity",
    }]


@pytest.fixture
def template_dir():
    return Path(__file__).parent.parent / "src" / "kairos_ontology" / "templates" / "dbt"


def _silver_sql(artifacts: dict) -> list[str]:
    return [k for k in artifacts if "models/silver/" in k and k.endswith(".sql")]


def test_feature_off_produces_no_stub(graph, classes, template_dir):
    """Default (flag off): an unmapped approved class yields no silver .sql."""
    artifacts = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=NS,
        ontology_name="client",
        eligible_class_uris={f"{NS}Client"},
    )
    assert not _silver_sql(artifacts)


def _file_artifacts(artifacts: dict) -> dict:
    """Drop internal ``__...__`` analysis keys that never reach disk."""
    return {k: v for k, v in artifacts.items() if not k.startswith("__")}


def test_feature_off_byte_identical_ignores_eligibility(graph, classes, template_dir):
    """With stubs disabled, passing eligible_class_uris changes no on-disk file.

    ``__unbound_eligible__`` is an internal (release-gate) key stripped by the
    orchestrator before writing, so the file artifacts must be byte-identical.
    """
    baseline = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
    )
    with_eligible = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
        eligible_class_uris={f"{NS}Client"},
    )
    assert _file_artifacts(baseline) == _file_artifacts(with_eligible)


def test_feature_on_emits_typed_zero_row_stub(graph, classes, template_dir):
    """Flag on: eligible unmapped class emits a typed, zero-row stub model."""
    artifacts = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=NS,
        ontology_name="client",
        emit_aspirational_stubs=True,
        eligible_class_uris={f"{NS}Client"},
    )
    sql = _silver_sql(artifacts)
    assert len(sql) == 1
    content = artifacts[sql[0]]
    # Zero-row guard so tests are vacuous until bound.
    assert "where 1 = 0" in content
    # Structural + datatype columns are typed via cast(null as ...).
    assert "cast(null as" in content
    assert "client_sk" in content
    assert "client_iri" in content
    assert "is_active" in content
    assert "kairos_aspirational_stub" in content
    assert "'is_aspirational': true" in content


def test_feature_on_schema_yaml_marks_aspirational(graph, classes, template_dir):
    """The stub's schema YAML entry carries read-only meta.is_aspirational."""
    artifacts = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=NS,
        ontology_name="client",
        emit_aspirational_stubs=True,
        eligible_class_uris={f"{NS}Client"},
    )
    models_yml = [k for k in artifacts if k.endswith("_models.yml")]
    assert models_yml
    yml = artifacts[models_yml[0]]
    assert "is_aspirational" in yml


def test_unbound_eligible_surfaced_regardless_of_stub_flag(graph, classes, template_dir):
    """D3: an eligible unbound class is reported in ``__unbound_eligible__``.

    The release gate must see approved-but-unbound targets whether or not stub
    emission is enabled, so the set is surfaced in both modes.
    """
    off = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
        eligible_class_uris={f"{NS}Client"},
    )
    on = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
        emit_aspirational_stubs=True, eligible_class_uris={f"{NS}Client"},
    )
    assert off.get("__unbound_eligible__") == ["Client"]
    assert on.get("__unbound_eligible__") == ["Client"]


def test_unbound_eligible_absent_when_no_eligible_set(graph, classes, template_dir):
    """No eligible set → no unbound-eligible report (nothing for the gate to block)."""
    artifacts = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
    )
    assert "__unbound_eligible__" not in artifacts


def test_coverage_data_is_stub_agnostic(graph, classes, template_dir):
    """D2: emitting a stub must not change coverage numbers.

    Coverage is computed from classes + mappings (not from generated artifacts), so
    an unbound eligible class reports zero-populated whether or not a stub is emitted.
    The ``__coverage_data__`` payload must be identical with the flag on vs off.
    """
    off = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
        eligible_class_uris={f"{NS}Client"},
    )
    on = generate_dbt_artifacts(
        classes=classes, graph=graph, template_dir=template_dir,
        namespace=NS, ontology_name="client",
        emit_aspirational_stubs=True, eligible_class_uris={f"{NS}Client"},
    )
    assert off.get("__coverage_data__") == on.get("__coverage_data__")


def test_feature_on_ineligible_class_not_stubbed(graph, classes, template_dir):
    """Flag on but class not eligible → still skipped (no stub)."""
    artifacts = generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=NS,
        ontology_name="client",
        emit_aspirational_stubs=True,
        eligible_class_uris=set(),
    )
    assert not _silver_sql(artifacts)
