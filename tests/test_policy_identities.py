# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Two EntityBindings on one source.relation, targeting different classes (#809).

The documented "one source table, several canonical entities" pattern: `goodheaders`
binds to both `Consignee` and `Consignor`. `_normalize_identities` kept its
relation-to-identity-ref lookup keyed on the physical `table_uri` alone, so whichever
candidate was processed last silently overwrote the other's entry and one class was then
attributed the other's contributor -- surfacing as `safety.type-incompatible` /
`identity.source-contributor-mismatch` on a binding that was correct. The only workaround
was a contracted dbt passthrough model per class, purely to mint distinct
`virtual_source_iri` values.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from discovery_fixtures import write_minimal_discovery_artifact  # noqa: E402

from kairos_ontology.core.compiler import compile_domain  # noqa: E402

_ONTOLOGY = textwrap.dedent("""
    @prefix party: <https://example.test/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
    party:Consignee a owl:Class ; rdfs:label "Consignee" .
    party:Consignor a owl:Class ; rdfs:label "Consignor" .
    party:consigneeCode a owl:DatatypeProperty ;
      rdfs:domain party:Consignee ; rdfs:range xsd:string .
    party:consigneeName a owl:DatatypeProperty ;
      rdfs:domain party:Consignee ; rdfs:range xsd:string .
    party:consignorCode a owl:DatatypeProperty ;
      rdfs:domain party:Consignor ; rdfs:range xsd:string .
    party:consignorName a owl:DatatypeProperty ;
      rdfs:domain party:Consignor ; rdfs:range xsd:string .
    """).strip()

_VOCABULARY = textwrap.dedent("""
    @prefix src: <https://example.test/source#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    src:tms a kb:SourceSystem ; rdfs:label "tms" ;
      kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
    src:goodheaders a kb:SourceTable ; kb:sourceSystem src:tms ;
      kb:tableName "goodheaders" ; kb:primaryKeyColumns "consignee_code" .
    src:consignee_code a kb:SourceColumn ; kb:sourceTable src:goodheaders ;
      kb:columnName "consignee_code" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:consignee_name a kb:SourceColumn ; kb:sourceTable src:goodheaders ;
      kb:columnName "consignee_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "true"^^xsd:boolean .
    src:consignor_code a kb:SourceColumn ; kb:sourceTable src:goodheaders ;
      kb:columnName "consignor_code" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:consignor_name a kb:SourceColumn ; kb:sourceTable src:goodheaders ;
      kb:columnName "consignor_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "true"^^xsd:boolean .
    """).strip()


def _binding(role: str) -> str:
    return textwrap.dedent(f"""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: tms-{role}
          domain: party
        source:
          relation: tms.goodheaders
        target:
          class: party:{role.capitalize()}
        grain:
          columns: [{role}_code]
        identity:
          strategy: source-natural
          sourceKey: [{role}_code]
        load:
          mode: full-refresh
        fields:
          - property: party:{role}Code
            expression: {role}_code
          - property: party:{role}Name
            expression: {role}_name
        """).strip()


def _hub(tmp_path: Path, *, order: tuple[str, str]) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "tms"
    binding_dir = tmp_path / "integration" / "bindings"
    for directory in (ontology_dir, source_dir, binding_dir):
        directory.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(_ONTOLOGY, encoding="utf-8")
    (source_dir / "tms.vocabulary.ttl").write_text(_VOCABULARY, encoding="utf-8")
    # Filenames drive discovery order, so the pair is written under names that make the
    # requested processing order the one on disk -- the defect was order-dependent.
    for index, role in enumerate(order):
        (binding_dir / f"{index}-{role}.binding.yaml").write_text(
            _binding(role), encoding="utf-8"
        )
    write_minimal_discovery_artifact(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "order", [("consignee", "consignor"), ("consignor", "consignee")], ids=["ee-or", "or-ee"]
)
def test_two_classes_may_share_one_source_relation(tmp_path, order):
    result = compile_domain(_hub(tmp_path, order=order), "party")
    messages = " ".join(d.message for d in result.diagnostics.ordered)
    assert "source-contributor-mismatch" not in messages, messages
    assert result.succeeded, messages


def test_both_classes_reach_silver_from_the_shared_relation(tmp_path):
    result = compile_domain(_hub(tmp_path, order=("consignee", "consignor")), "party")
    artifacts = result.artifact_dict()
    assert "models/silver/party/consignee.sql" in artifacts
    assert "models/silver/party/consignor.sql" in artifacts
    # Each model selects its own columns: the collision attributed one class's identity
    # contributor to the other, so this is the property that has to hold.
    assert "consignee_code" in artifacts["models/silver/party/consignee.sql"]
    assert "consignor_code" in artifacts["models/silver/party/consignor.sql"]
