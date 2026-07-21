# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the canonical ontology closure loader (DD-103)."""

from pathlib import Path

import pytest
from rdflib import RDF, URIRef

from kairos_ontology.core.ontology_loader import (
    OntologyLoadError,
    load_ontology,
)


OWL_CLASS = URIRef("http://www.w3.org/2002/07/owl#Class")


def _ttl(ontology: str, *, imports: tuple[str, ...] = (), cls: str | None = None) -> str:
    import_lines = "".join(f" ;\n    owl:imports <{item}>" for item in imports)
    class_line = f"\n<{cls}> a owl:Class .\n" if cls else ""
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"<{ontology}> a owl:Ontology{import_lines} .\n"
        f"{class_line}"
    )


def _catalog(path: Path, mappings: dict[str, str], *, next_catalog: str | None = None) -> Path:
    entries = "".join(
        f'  <uri name="{uri}" uri="{target}"/>\n'
        for uri, target in mappings.items()
    )
    chained = f'  <nextCatalog catalog="{next_catalog}"/>\n' if next_catalog else ""
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f"{entries}{chained}</catalog>\n",
        encoding="utf-8",
    )
    return path


def test_loads_transitive_three_level_import_closure(tmp_path):
    root = tmp_path / "a.ttl"
    child = tmp_path / "b.ttl"
    deepest = tmp_path / "c.ttl"
    root.write_text(_ttl("urn:a", imports=("urn:b",), cls="urn:A"), encoding="utf-8")
    child.write_text(_ttl("urn:b", imports=("urn:c",), cls="urn:B"), encoding="utf-8")
    deepest.write_text(_ttl("urn:c", cls="urn:C"), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:b": "b.ttl", "urn:c": "c.ttl"})

    result = load_ontology(root, catalog_path=catalog)

    assert result.complete
    assert (URIRef("urn:C"), RDF.type, OWL_CLASS) in result.graph
    assert [entry.import_depth for entry in result.manifest] == [0, 1, 2]


def test_import_cycle_terminates_with_diagnostic(tmp_path):
    root = tmp_path / "a.ttl"
    child = tmp_path / "b.ttl"
    root.write_text(_ttl("urn:a", imports=("urn:b",)), encoding="utf-8")
    child.write_text(_ttl("urn:b", imports=("urn:a",)), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:a": "a.ttl", "urn:b": "b.ttl"})

    result = load_ontology(root, catalog_path=catalog)

    assert result.complete
    assert len(result.manifest) == 2
    assert any(item.code == "import_cycle" for item in result.diagnostics)


def test_catalog_cycle_terminates_with_diagnostic(tmp_path):
    root = tmp_path / "root.ttl"
    root.write_text(_ttl("urn:root"), encoding="utf-8")
    first = _catalog(tmp_path / "first.xml", {}, next_catalog="second.xml")
    _catalog(tmp_path / "second.xml", {}, next_catalog="first.xml")

    result = load_ontology(root, catalog_path=first)

    assert result.complete
    assert any(item.code == "catalog_cycle" for item in result.diagnostics)


def test_missing_required_import_fails_closed(tmp_path):
    root = tmp_path / "root.ttl"
    root.write_text(_ttl("urn:root", imports=("urn:missing",)), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {})

    with pytest.raises(OntologyLoadError) as exc_info:
        load_ontology(root, catalog_path=catalog)

    assert not exc_info.value.result.complete
    assert any(item.code == "missing_import" for item in exc_info.value.result.diagnostics)


def test_degraded_and_optional_import_modes_are_explicit(tmp_path):
    root = tmp_path / "root.ttl"
    root.write_text(_ttl("urn:root", imports=("urn:missing",)), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {})

    degraded = load_ontology(root, catalog_path=catalog, degraded=True)
    optional = load_ontology(
        root,
        catalog_path=catalog,
        optional_imports={"urn:missing"},
    )

    assert not degraded.complete
    assert optional.complete


def test_legacy_facade_remains_lenient(tmp_path):
    from kairos_ontology.core.catalog_utils import load_graph_with_catalog

    root = tmp_path / "root.ttl"
    root.write_text(_ttl("urn:root", imports=("urn:missing",)), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {})

    result = load_graph_with_catalog(root, catalog, quiet=True)

    assert len(result.graph) > 0
    assert result.diagnostics[0]["level"] == "warning"
    assert "No catalog mapping for" in result.diagnostics[0]["message"]


def test_jsonld_import_uses_resolved_source_format(tmp_path):
    root = tmp_path / "root.ttl"
    imported = tmp_path / "child.jsonld"
    root.write_text(_ttl("urn:root", imports=("urn:child",)), encoding="utf-8")
    imported.write_text(
        """{
  "@context": {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  },
  "@id": "urn:Child",
  "@type": "owl:Class"
}""",
        encoding="utf-8",
    )
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:child": "child.jsonld"})

    result = load_ontology(root, catalog_path=catalog)

    assert (URIRef("urn:Child"), RDF.type, OWL_CLASS) in result.graph
    assert result.manifest[1].rdf_format == "json-ld"


def test_mixed_turtle_rdfxml_jsonld_and_owl_import_chain(tmp_path):
    root = tmp_path / "root.ttl"
    child = tmp_path / "child.rdf"
    grandchild = tmp_path / "grandchild.jsonld"
    leaf = tmp_path / "leaf.owl"
    root.write_text(_ttl("urn:a", imports=("urn:b",), cls="urn:A"), encoding="utf-8")
    child.write_text(
        """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="urn:b"><owl:imports rdf:resource="urn:c"/></owl:Ontology>
  <owl:Class rdf:about="urn:B"/>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    grandchild.write_text(
        """{
  "@context": {
    "owl": "http://www.w3.org/2002/07/owl#",
    "imports": {"@id": "owl:imports", "@type": "@id"}
  },
  "@graph": [
    {"@id": "urn:c", "@type": "owl:Ontology", "imports": "urn:d"},
    {"@id": "urn:C", "@type": "owl:Class"}
  ]
}""",
        encoding="utf-8",
    )
    leaf.write_text(
        """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="urn:d"/>
  <owl:Class rdf:about="urn:D"/>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    catalog = _catalog(
        tmp_path / "catalog.xml",
        {
            "urn:b": "child.rdf",
            "urn:c": "grandchild.jsonld",
            "urn:d": "leaf.owl",
        },
    )

    result = load_ontology(root, catalog_path=catalog)

    assert (URIRef("urn:D"), RDF.type, OWL_CLASS) in result.graph
    assert [entry.rdf_format for entry in result.manifest] == [
        "turtle",
        "xml",
        "json-ld",
        "xml",
    ]


def test_closure_hash_is_machine_root_independent_and_dependency_sensitive(tmp_path):
    def build(base: Path) -> tuple[Path, Path, Path]:
        base.mkdir()
        root = base / "root.ttl"
        child = base / "child.ttl"
        root.write_text(_ttl("urn:root", imports=("urn:child",)), encoding="utf-8")
        child.write_text(_ttl("urn:child", cls="urn:Child"), encoding="utf-8")
        catalog = _catalog(base / "catalog.xml", {"urn:child": "child.ttl"})
        return root, child, catalog

    root_a, _, catalog_a = build(tmp_path / "one")
    root_b, child_b, catalog_b = build(tmp_path / "two")

    first = load_ontology(root_a, catalog_path=catalog_a)
    second = load_ontology(root_b, catalog_path=catalog_b)
    assert first.closure_hash == second.closure_hash

    child_b.write_text(_ttl("urn:child", cls="urn:Changed"), encoding="utf-8")
    changed = load_ontology(root_b, catalog_path=catalog_b)
    assert changed.closure_hash != first.closure_hash
