# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for scoped mapping, Silver, and class-property validation."""

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.design_validation import (
    validate_mapping_design,
    validate_silver_extension,
)
from kairos_ontology.core.claim_projection_sync import (
    ProjectionMigrationRequiredError,
    _require_current_managed_surface,
)
from rdflib import Namespace


ONTOLOGY = """\
@prefix ex: <https://example.test/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.test/domain> a owl:Ontology .
ex:Parent a owl:Class .
ex:Child a owl:Class ; rdfs:subClassOf ex:Parent .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Parent ; rdfs:range xsd:string .
"""

SOURCE = """\
@prefix src: <https://example.test/source#> .
@prefix bronze: <https://kairos.cnext.eu/bronze#> .
src:Table a bronze:SourceTable .
src:Column a bronze:SourceColumn ; bronze:sourceTable src:Table .
"""

MAPPING = """\
@prefix map: <https://example.test/map#> .
@prefix km: <https://kairos.cnext.eu/mapping#> .
@prefix src: <https://example.test/source#> .
@prefix ex: <https://example.test/domain#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
map:table a km:TableMapping ;
  km:sourceTable src:Table ; km:targetClass ex:Child ;
  km:mappingType "direct" ; km:matchType "exactMatch" .
src:Table skos:exactMatch ex:Child .
map:column a km:ColumnMapping ;
  km:sourceColumn src:Column ; km:targetProperty ex:name ;
  km:matchType "exactMatch" .
src:Column skos:exactMatch ex:name .
"""

SHAPES = """\
@prefix ex: <https://example.test/domain#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ext: <https://kairos.cnext.eu/ext#> .
ex:SilverShape a sh:NodeShape ;
  sh:targetSubjectsOf ext:silverInclude ;
  sh:property [ sh:path ext:businessGrain ; sh:minCount 1 ] .
"""


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    ontology = tmp_path / "domain.ttl"
    source_root = tmp_path / "sources"
    mapping = tmp_path / "mapping.ttl"
    source_root.mkdir()
    ontology.write_text(ONTOLOGY, encoding="utf-8")
    (source_root / "source.ttl").write_text(SOURCE, encoding="utf-8")
    mapping.write_text(MAPPING, encoding="utf-8")
    return ontology, source_root, mapping


def test_mapping_validation_accepts_inherited_property(tmp_path):
    ontology, sources, mapping = _files(tmp_path)

    result = validate_mapping_design(
        mapping_paths=[mapping],
        source_root=sources,
        ontology_path=ontology,
    )

    assert result["passed"]
    assert result["table_mappings"] == 1
    assert result["column_mappings"] == 1


def test_mapping_validation_names_unknown_source_resource(tmp_path):
    ontology, sources, mapping = _files(tmp_path)
    mapping.write_text(
        MAPPING.replace("src:Column ;", "src:Missing ;").replace(
            "src:Column skos:", "src:Missing skos:"
        ),
        encoding="utf-8",
    )

    result = validate_mapping_design(
        mapping_paths=[mapping],
        source_root=sources,
        ontology_path=ontology,
    )

    assert not result["passed"]
    diagnostic = next(
        item for item in result["diagnostics"] if item["code"] == "mapping.unknown-source-column"
    )
    assert diagnostic["resource_uri"] == "https://example.test/map#column"
    assert "https://example.test/source#Missing" in diagnostic["message"]


def test_mapping_validation_rejects_invalid_expression_type(tmp_path):
    ontology, sources, mapping = _files(tmp_path)
    mapping.write_text(
        MAPPING.replace(
            "km:sourceColumn src:Column ; km:targetProperty ex:name ;",
            "km:sourceColumn src:Column ; km:targetProperty ex:name ; "
            "km:expression map:expression ;",
        )
        + """\
map:expression a km:SourceColumnExpression ;
  km:sourceColumn src:Column ;
  km:outputType "mystery" ;
  km:nullable "false" ;
  km:nullPolicy "propagate" ;
  km:determinism "deterministic" ;
  km:requiresCapability "source-column" .
""",
        encoding="utf-8",
    )

    result = validate_mapping_design(
        mapping_paths=[mapping],
        source_root=sources,
        ontology_path=ontology,
    )

    assert not result["passed"]
    assert result["diagnostics"][0]["code"] == "mapping.invalid-expression-output-type"
    assert result["diagnostics"][0]["resource_uri"] == "https://example.test/map#expression"


def test_silver_extension_is_scoped_and_reports_focus_node(tmp_path):
    ontology, _, _ = _files(tmp_path)
    extension = tmp_path / "domain-silver-ext.ttl"
    shapes = tmp_path / "ext.shacl.ttl"
    extension.write_text(
        """\
@prefix ex: <https://example.test/domain#> .
@prefix ext: <https://kairos.cnext.eu/ext#> .
ex:Child ext:silverInclude true .
""",
        encoding="utf-8",
    )
    shapes.write_text(SHAPES, encoding="utf-8")
    (tmp_path / "unrelated-broken.ttl").write_text("@prefix broken:", encoding="utf-8")

    result = validate_silver_extension(
        extension_path=extension,
        ontology_path=ontology,
        shapes_path=shapes,
    )

    assert not result["passed"]
    assert result["diagnostics"][0]["resource_uri"] == "https://example.test/domain#Child"
    assert "businessGrain" in result["diagnostics"][0]["message"]


def test_silver_extension_passes_focused_shape(tmp_path):
    ontology, _, _ = _files(tmp_path)
    extension = tmp_path / "domain-silver-ext.ttl"
    shapes = tmp_path / "ext.shacl.ttl"
    extension.write_text(
        """\
@prefix ex: <https://example.test/domain#> .
@prefix ext: <https://kairos.cnext.eu/ext#> .
ex:Child ext:silverInclude true ; ext:businessGrain ex:name .
""",
        encoding="utf-8",
    )
    shapes.write_text(SHAPES, encoding="utf-8")

    result = validate_silver_extension(
        extension_path=extension,
        ontology_path=ontology,
        shapes_path=shapes,
    )

    assert result["passed"]
    assert result["diagnostics"] == []


def test_list_class_properties_includes_ranges_and_inheritance(tmp_path):
    ontology, _, _ = _files(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "list-class-properties",
            "https://example.test/domain#Child",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"origin": "inherited"' in result.output
    assert "http://www.w3.org/2001/XMLSchema#string" in result.output


def test_managed_block_diagnostic_names_offending_resource(tmp_path):
    path = tmp_path / "domain-silver-ext.ttl"
    path.write_text(
        """\
@prefix ex: <https://example.test/domain#> .
@prefix ext: <https://kairos.cnext.eu/ext#> .
ex:Imported ext:silverInclude true .
""",
        encoding="utf-8",
    )
    ext = Namespace("https://kairos.cnext.eu/ext#")

    try:
        _require_current_managed_surface(
            path,
            lambda triple: triple[1] == ext.silverInclude,
        )
    except ProjectionMigrationRequiredError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected a managed-block diagnostic")

    assert "https://example.test/domain#Imported" in message
    assert "kairos-ontology migrate --hub <hub>" in message
