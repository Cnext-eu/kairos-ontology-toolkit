# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the complete-package dbt pre-write gate."""

from pathlib import Path

import pytest

from kairos_ontology.core.projector import ProjectionRunError, run_projections

_ONTOLOGY = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://example.com/{name}#> .

<https://example.com/{name}> a owl:Ontology ;
  rdfs:label "{name}" ;
  owl:versionInfo "1.0.0" .
ex:Entity a owl:Class ;
  rdfs:label "Entity" ;
  rdfs:comment "An entity." .
"""


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    ontologies = hub / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    for name in ("alpha", "beta"):
        (ontologies / f"{name}.ttl").write_text(
            _ONTOLOGY.format(name=name),
            encoding="utf-8",
        )
    return hub


def test_retired_dbt_projection_fails_before_report_or_partial_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    hub = _hub(tmp_path)
    output = hub / "output"

    def fake_projection(*args, **kwargs):
        raise AssertionError("retired dbt path must fail before domain projection")

    monkeypatch.setattr(
        "kairos_ontology.core.projector._run_projection",
        fake_projection,
    )

    with pytest.raises(ProjectionRunError, match=r"compile <domain> --emit"):
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "missing.xml",
            output_path=output,
            target="dbt",
        )

    assert not output.exists()
