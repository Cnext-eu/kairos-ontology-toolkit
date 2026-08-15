# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the grain materialization audit (#449, DD-159 additive explain).

Each grain column is classified into one of four mechanisms:

  direct-field     — a ``fields:`` entry maps the source column via ``ExprColumn``
  technical-field  — a ``technicalFields:`` entry carries the source column (DD-139)
  expression-only  — the source column appears only inside a multi-part expression
  absent           — no field or technical field references the source column
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import CompileMode, ExplainGrainMechanism, compile_domain

from discovery_fixtures import write_minimal_discovery_artifact

_NS = "https://example.test/party#"
_IRI = "https://example.test/party"

_ONTOLOGY = textwrap.dedent("""
    @prefix party: <https://example.test/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
    party:Customer a owl:Class ; rdfs:label "Customer" .
    party:customer_id a owl:DatatypeProperty ;
      rdfs:domain party:Customer ; rdfs:range xsd:string .
    party:customerName a owl:DatatypeProperty ;
      rdfs:domain party:Customer ; rdfs:range xsd:string .
    party:fullName a owl:DatatypeProperty ;
      rdfs:domain party:Customer ; rdfs:range xsd:string .
    party:score a owl:DatatypeProperty ;
      rdfs:domain party:Customer ; rdfs:range xsd:integer .
    """).strip()

_SOURCE = textwrap.dedent("""
    @prefix src: <https://example.test/source#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    src:crm a kb:SourceSystem ; rdfs:label "crm" ;
      kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
    src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
    src:id a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:name a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "true"^^xsd:boolean .
    src:acct a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "account_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:seq a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "seq_no" ; kb:dataType "int" ;
      kb:nullable "true"^^xsd:boolean .
    """).strip()


def _make_hub(tmp_path: Path, binding_body: str) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(_ONTOLOGY, encoding="utf-8")
    (source_dir / "crm.vocabulary.ttl").write_text(_SOURCE, encoding="utf-8")
    (binding_dir / "customer.binding.yaml").write_text(binding_body.strip(), encoding="utf-8")
    write_minimal_discovery_artifact(tmp_path)
    return tmp_path


_BINDING_HEADER = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-customer
      domain: party
    source:
      relation: crm.customers
    target:
      class: party:Customer
    load:
      mode: full-refresh
    """)


def test_grain_direct_field_mechanism(tmp_path: Path) -> None:
    """Grain column mapped directly via a ``fields:`` entry → ``direct-field``."""
    binding = _BINDING_HEADER + textwrap.dedent("""\
        grain:
          columns: [customer_id]
        identity:
          strategy: source-natural
          sourceKey: [customer_id]
        fields:
          - property: party:customer_id
            expression: customer_id
          - property: party:customerName
            expression: customer_name
        """)
    hub = _make_hub(tmp_path, binding)
    result = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert result.succeeded
    assert result.explain is not None
    entity = result.explain.entities[0]
    assert entity.grain == ("customer_id",)
    assert len(entity.grain_mechanisms) == 1
    m = entity.grain_mechanisms[0]
    assert m.column == "customer_id"
    assert m.mechanism == "direct-field"
    assert m.output == "party:customer_id"


def test_grain_technical_field_mechanism(tmp_path: Path) -> None:
    """Grain column carried only by ``technicalFields:`` → ``technical-field``."""
    binding = _BINDING_HEADER + textwrap.dedent("""\
        grain:
          columns: [account_id]
        identity:
          strategy: source-natural
          sourceKey: [account_id]
        fields:
          - property: party:customerName
            expression: customer_name
        technicalFields:
          - name: account_ref
            expression: account_id
            type: string
            nullable: true
            purpose: identity
        """)
    hub = _make_hub(tmp_path, binding)
    result = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert result.succeeded
    assert result.explain is not None
    entity = result.explain.entities[0]
    assert entity.grain == ("account_id",)
    assert len(entity.grain_mechanisms) == 1
    m = entity.grain_mechanisms[0]
    assert m.column == "account_id"
    assert m.mechanism == "technical-field"
    assert m.output == "account_ref"


def test_grain_expression_only_mechanism(tmp_path: Path) -> None:
    """Grain column appears only inside a multi-part expression → ``expression-only``.

    Uses a two-column grain: ``customer_id`` (direct-field, the identity key) and
    ``seq_no`` (expression-only — referenced only inside an ``op: add`` expression
    producing ``party:score``, never mapped as a standalone field).
    """
    binding = _BINDING_HEADER + textwrap.dedent("""\
        grain:
          columns: [customer_id, seq_no]
        identity:
          strategy: source-natural
          sourceKey: [customer_id]
        fields:
          - property: party:customer_id
            expression: customer_id
          - property: party:score
            expression:
              op: add
              args:
                - { literal: "1", datatype: integer }
                - column: seq_no
        """)
    hub = _make_hub(tmp_path, binding)
    result = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert result.succeeded
    assert result.explain is not None
    entity = result.explain.entities[0]
    assert entity.grain == ("customer_id", "seq_no")
    assert len(entity.grain_mechanisms) == 2
    m_id, m_seq = entity.grain_mechanisms
    assert m_id.column == "customer_id"
    assert m_id.mechanism == "direct-field"
    assert m_seq.column == "seq_no"
    assert m_seq.mechanism == "expression-only"
    assert m_seq.output == "party:score"


def test_grain_absent_mechanism(tmp_path: Path) -> None:
    """Grain column not referenced in any field or technical field → ``absent``.

    Uses a two-column grain: ``customer_id`` (direct-field, the identity key) and
    ``seq_no`` (absent — not referenced anywhere in fields or technicalFields).
    """
    binding = _BINDING_HEADER + textwrap.dedent("""\
        grain:
          columns: [customer_id, seq_no]
        identity:
          strategy: source-natural
          sourceKey: [customer_id]
        fields:
          - property: party:customer_id
            expression: customer_id
          - property: party:customerName
            expression: customer_name
        """)
    hub = _make_hub(tmp_path, binding)
    result = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert result.succeeded
    assert result.explain is not None
    entity = result.explain.entities[0]
    assert entity.grain == ("customer_id", "seq_no")
    # Find the absent mechanism for seq_no
    absent = [m for m in entity.grain_mechanisms if m.mechanism == "absent"]
    assert len(absent) == 1
    assert absent[0].column == "seq_no"
    assert absent[0].output == ""


def test_grain_mechanism_is_dataclass_and_frozen(tmp_path: Path) -> None:
    """ExplainGrainMechanism must be a frozen dataclass (part of the public API contract)."""
    m = ExplainGrainMechanism(column="x", mechanism="absent", output="")
    with pytest.raises(Exception):
        m.column = "y"  # type: ignore[misc]
