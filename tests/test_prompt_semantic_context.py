# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Prompt projection semantic-coverage disclosure tests."""

import json

from kairos_ontology.core.projector import run_projections


def test_prompt_projection_discloses_profile_closure_and_provenance(tmp_path):
    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "party.ttl").write_text(
        """\
@prefix ex: <https://example.org/party#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/party> a owl:Ontology ; rdfs:label "Party" .
ex:Party a owl:Class ; rdfs:label "Party" .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:label "Name" .
""",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    run_projections(
        ontologies_path=ontologies,
        catalog_path=None,
        output_path=output,
        target="prompt",
    )

    compact = json.loads(
        (output / "prompt" / "party-context.json").read_text(
            encoding="utf-8"
        )
    )
    detailed = json.loads(
        (output / "prompt" / "party-context-detailed.json").read_text(
            encoding="utf-8"
        )
    )
    metadata = compact["semantic_context"]
    assert metadata["semantic_profile"] == "kairos-design"
    assert len(metadata["closure_hash"]) == 64
    assert metadata["import_complete"] is True
    assert metadata["truncated"] is False
    assert metadata["included_class_count"] == 1
    assert detailed["entities"][0]["provenance"]["source_identity"] == (
        "https://example.org/party"
    )
