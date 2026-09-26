# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the canonical ontology closure loader (DD-103)."""

from pathlib import Path

import pytest
from rdflib import RDF, URIRef

from kairos_ontology.core import ontology_loader
from kairos_ontology.core.ontology_loader import (
    OntologyLoadError,
    load_ontology,
)

OWL_CLASS = URIRef("http://www.w3.org/2002/07/owl#Class")


@pytest.fixture(autouse=True)
def _reset_ontology_cache():
    """Tier A and A2 (in-process) memoization is module-global state; isolate every test."""
    ontology_loader.reset_in_process_caches()
    yield
    ontology_loader.reset_in_process_caches()


def _count_turtle_parses(monkeypatch) -> list:
    """Patch Graph.parse to record every *Turtle* (not cached N-Triples) parse call."""
    parsed = []
    original_parse = ontology_loader.Graph.parse

    def counting_parse(self, source=None, **kwargs):
        if kwargs.get("format") == "turtle":
            parsed.append(source)
        return original_parse(self, source, **kwargs)

    monkeypatch.setattr(ontology_loader.Graph, "parse", counting_parse)
    return parsed


def _ttl(ontology: str, *, imports: tuple[str, ...] = (), cls: str | None = None) -> str:
    import_lines = "".join(f" ;\n    owl:imports <{item}>" for item in imports)
    class_line = f"\n<{cls}> a owl:Class .\n" if cls else ""
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"<{ontology}> a owl:Ontology{import_lines} .\n"
        f"{class_line}"
    )


def _catalog(path: Path, mappings: dict[str, str], *, next_catalog: str | None = None) -> Path:
    entries = "".join(f'  <uri name="{uri}" uri="{target}"/>\n' for uri, target in mappings.items())
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


def test_repeated_load_within_one_process_reuses_the_cached_result(tmp_path, monkeypatch):
    root = tmp_path / "a.ttl"
    root.write_text(_ttl("urn:a", cls="urn:A"), encoding="utf-8")
    parsed = _count_turtle_parses(monkeypatch)

    first = load_ontology(root, identity_root=tmp_path)
    assert len(parsed) == 1

    second = load_ontology(root, identity_root=tmp_path)
    assert len(parsed) == 1  # Tier A hit: no reparse
    assert second is first


def test_cached_result_is_not_reused_across_a_different_profile(tmp_path, monkeypatch):
    from kairos_ontology.core.ontology_loader import SemanticProfile

    root = tmp_path / "a.ttl"
    root.write_text(_ttl("urn:a", cls="urn:A"), encoding="utf-8")
    parsed = _count_turtle_parses(monkeypatch)

    asserted = load_ontology(root, identity_root=tmp_path, profile=SemanticProfile.ASSERTED)
    assert len(parsed) == 1

    rdfs = load_ontology(root, identity_root=tmp_path, profile=SemanticProfile.RDFS)
    # A different profile is a different Tier A key, so the result is rebuilt; the
    # unchanged file itself comes from Tier A2 rather than a second Turtle parse.
    assert rdfs is not asserted
    assert rdfs.profile != asserted.profile
    assert len(parsed) == 1


def test_repeated_load_reparses_when_a_transitively_imported_file_changes(tmp_path, monkeypatch):
    root = tmp_path / "a.ttl"
    child = tmp_path / "b.ttl"
    root.write_text(_ttl("urn:a", imports=("urn:b",), cls="urn:A"), encoding="utf-8")
    child.write_text(_ttl("urn:b", cls="urn:B"), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:b": "b.ttl"})
    parsed = _count_turtle_parses(monkeypatch)

    first = load_ontology(root, catalog_path=catalog)
    assert len(parsed) == 2  # root + child

    child.write_text(_ttl("urn:b", cls="urn:Changed"), encoding="utf-8")
    second = load_ontology(root, catalog_path=catalog)

    assert second is not first
    assert second.closure_hash != first.closure_hash
    assert (URIRef("urn:Changed"), RDF.type, OWL_CLASS) in second.graph
    # The stale Tier A entry was rejected; only the changed file is reparsed, because
    # Tier A2 is keyed on content and the root's content did not change.
    assert parsed[2:] == [child.resolve()]


def test_on_disk_cache_survives_a_simulated_new_process_without_reparsing_turtle(
    tmp_path, monkeypatch
):
    root = tmp_path / "a.ttl"
    root.write_text(_ttl("urn:a", cls="urn:A"), encoding="utf-8")

    with ontology_loader.cache_write_scope(True):
        load_ontology(root, identity_root=tmp_path)

    # Simulate a fresh process: Tier A (in-process memoization) does not survive this,
    # only Tier B (the on-disk, per-file parse cache) does.
    ontology_loader.reset_in_process_caches()
    parsed = _count_turtle_parses(monkeypatch)

    result = load_ontology(root, identity_root=tmp_path)

    assert not parsed  # served entirely from the on-disk N-Triples cache
    assert (URIRef("urn:A"), RDF.type, OWL_CLASS) in result.graph


def test_on_disk_cache_invalidates_only_the_file_that_actually_changed(tmp_path, monkeypatch):
    root = tmp_path / "a.ttl"
    child = tmp_path / "b.ttl"
    root.write_text(_ttl("urn:a", imports=("urn:b",), cls="urn:A"), encoding="utf-8")
    child.write_text(_ttl("urn:b", cls="urn:B"), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:b": "b.ttl"})

    with ontology_loader.cache_write_scope(True):
        load_ontology(root, catalog_path=catalog)

    ontology_loader.reset_in_process_caches()
    child.write_text(_ttl("urn:b", cls="urn:Changed"), encoding="utf-8")
    parsed = _count_turtle_parses(monkeypatch)

    with ontology_loader.cache_write_scope(True):
        result = load_ontology(root, catalog_path=catalog)

    assert parsed == [child.resolve()]  # only the changed file forced a Turtle reparse
    assert (URIRef("urn:Changed"), RDF.type, OWL_CLASS) in result.graph


def test_no_cache_write_scope_leaves_no_files_when_disabled(tmp_path):
    root = tmp_path / "a.ttl"
    root.write_text(_ttl("urn:a", cls="urn:A"), encoding="utf-8")

    with ontology_loader.cache_write_scope(False):
        load_ontology(root, identity_root=tmp_path)

    assert not (tmp_path / ".cache").exists()


def test_cache_write_scope_restores_previous_value_on_exception(tmp_path):
    ontology_loader.CACHE_WRITE_ENABLED = False
    with pytest.raises(RuntimeError):
        with ontology_loader.cache_write_scope(True):
            assert ontology_loader.CACHE_WRITE_ENABLED is True
            raise RuntimeError("boom")
    assert ontology_loader.CACHE_WRITE_ENABLED is False


def test_two_closures_sharing_an_import_parse_it_once(tmp_path, monkeypatch):
    """Tier A2 (#598): every domain imports the same shared modules."""
    shared = tmp_path / "shared.ttl"
    shared.write_text(_ttl("urn:shared", cls="urn:Shared"), encoding="utf-8")
    first = tmp_path / "a.ttl"
    second = tmp_path / "b.ttl"
    first.write_text(_ttl("urn:a", imports=("urn:shared",), cls="urn:A"), encoding="utf-8")
    second.write_text(_ttl("urn:b", imports=("urn:shared",), cls="urn:B"), encoding="utf-8")
    catalog = _catalog(tmp_path / "catalog.xml", {"urn:shared": "shared.ttl"})
    parsed = _count_turtle_parses(monkeypatch)

    loaded_a = load_ontology(first, catalog_path=catalog)
    loaded_b = load_ontology(second, catalog_path=catalog)

    assert sorted(parsed) == sorted([first.resolve(), shared.resolve(), second.resolve()])
    assert (URIRef("urn:Shared"), RDF.type, OWL_CLASS) in loaded_b.graph
    # The closures are separate graphs: one domain's triples never leak into another's.
    assert (URIRef("urn:A"), RDF.type, OWL_CLASS) not in loaded_b.graph
    assert (URIRef("urn:B"), RDF.type, OWL_CLASS) not in loaded_a.graph


def test_no_cache_bypasses_the_source_graph_memo(tmp_path, monkeypatch):
    root = tmp_path / "a.ttl"
    root.write_text(_ttl("urn:a", cls="urn:A"), encoding="utf-8")
    load_ontology(root, identity_root=tmp_path)
    monkeypatch.setattr(ontology_loader, "CACHE_ENABLED", False)
    parsed = _count_turtle_parses(monkeypatch)

    load_ontology(root, identity_root=tmp_path)

    assert parsed == [root.resolve()]


def test_a_graph_served_from_memory_still_warms_another_hubs_disk_cache(tmp_path):
    """Tier B is per hub; Tier A2 is per process. A second hub with the same file content
    must still get its own on-disk entry when it emits."""
    body = _ttl("urn:a", cls="urn:A")
    first_hub, second_hub = tmp_path / "one", tmp_path / "two"
    for hub in (first_hub, second_hub):
        hub.mkdir()
        (hub / "a.ttl").write_text(body, encoding="utf-8")

    load_ontology(first_hub / "a.ttl", identity_root=first_hub)
    with ontology_loader.cache_write_scope(True):
        load_ontology(second_hub / "a.ttl", identity_root=second_hub)

    assert list((second_hub / ".cache" / "ontology-parse").glob("*.nt"))
