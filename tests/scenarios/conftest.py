# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared fixtures for scenario-based integration tests.

The ``acme-hub`` directory contains a synthetic ontology hub with two domains
(client, invoice), two source systems (AdminPulse, BillingPro), and enough
complexity to exercise split patterns, cross-domain FKs, deduplication,
default values, SHACL shapes, and gold star-schema annotations.
"""

from pathlib import Path

import pytest
from rdflib import Graph

# ---------------------------------------------------------------------------
# Hub paths
# ---------------------------------------------------------------------------
HUB_ROOT = Path(__file__).parent / "acme-hub"
ONTOLOGIES_DIR = HUB_ROOT / "model" / "ontologies"
EXTENSIONS_DIR = HUB_ROOT / "model" / "extensions"
SHAPES_DIR = HUB_ROOT / "model" / "shapes"
MAPPINGS_DIR = HUB_ROOT / "model" / "mappings"
SOURCES_DIR = HUB_ROOT / "integration" / "sources"

TEMPLATE_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "kairos_ontology"
    / "templates"
    / "dbt"
)


def _load_ontology(name: str) -> tuple[Graph, str, list[dict]]:
    """Load a domain ontology and return (graph, namespace, classes).

    Also merges the corresponding silver-ext file if it exists.
    """
    from rdflib.namespace import OWL, RDF

    ttl_path = ONTOLOGIES_DIR / f"{name}.ttl"
    g = Graph()
    g.parse(ttl_path, format="turtle")

    # Merge silver extension if present
    ext_path = EXTENSIONS_DIR / f"{name}-silver-ext.ttl"
    if ext_path.exists():
        g.parse(ext_path, format="turtle")

    # Detect namespace from owl:Ontology declaration
    namespace = None
    for onto in g.subjects(RDF.type, OWL.Ontology):
        uri = str(onto)
        namespace = uri + "#" if "#" not in uri else uri.rsplit("#", 1)[0] + "#"
        break
    assert namespace, f"No owl:Ontology found in {ttl_path}"

    # Extract classes
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        cls_uri = str(cls)
        if not cls_uri.startswith(namespace):
            continue
        from kairos_ontology.projections.uri_utils import extract_local_name
        local = extract_local_name(cls_uri)
        label = g.value(cls, OWL.Class) or local
        for lbl in g.objects(cls, OWL.Class):
            break
        # Use rdfs:label
        from rdflib import RDFS
        label = str(g.value(cls, RDFS.label) or local)
        comment = str(g.value(cls, RDFS.comment) or f"{local} entity")
        classes.append({
            "uri": cls_uri,
            "name": local,
            "label": label,
            "comment": comment,
        })

    return g, namespace, classes


def _load_ontology_with_imports(name: str) -> tuple[Graph, str, list[dict]]:
    """Load a domain ontology, merge reference model imports, and apply DD-021 whitelisting.

    Simulates what ``_run_projection()`` does: loads the domain .ttl, parses
    any ``_refmodel-*.ttl`` files into the same graph (mimicking catalog-based
    import resolution), then uses ``_discover_whitelisted_imports()`` to build
    the class list that includes both local and whitelisted imported classes.
    """
    from rdflib.namespace import OWL, RDF, RDFS

    ttl_path = ONTOLOGIES_DIR / f"{name}.ttl"
    g = Graph()
    g.parse(ttl_path, format="turtle")

    # Simulate catalog import resolution: parse _refmodel-*.ttl files
    for ref_file in sorted(ONTOLOGIES_DIR.glob("_refmodel-*.ttl")):
        g.parse(ref_file, format="turtle")

    # Merge silver extension if present
    ext_path = EXTENSIONS_DIR / f"{name}-silver-ext.ttl"
    if ext_path.exists():
        g.parse(ext_path, format="turtle")

    # Detect namespace from owl:Ontology declaration
    namespace = None
    for onto in g.subjects(RDF.type, OWL.Ontology):
        uri = str(onto)
        # Pick the ontology that matches the domain name
        if name in uri:
            namespace = uri + "#" if "#" not in uri else uri.rsplit("#", 1)[0] + "#"
            break
    assert namespace, f"No owl:Ontology for domain '{name}' found in {ttl_path}"

    # Extract local classes (domain namespace)
    from kairos_ontology.projections.uri_utils import extract_local_name
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        cls_uri = str(cls)
        if not cls_uri.startswith(namespace):
            continue
        local = extract_local_name(cls_uri)
        label = str(g.value(cls, RDFS.label) or local)
        comment = str(g.value(cls, RDFS.comment) or f"{local} entity")
        classes.append({
            "uri": cls_uri, "name": local, "label": label, "comment": comment,
        })

    # DD-021: Discover whitelisted imports
    from kairos_ontology.projector import _discover_whitelisted_imports

    # Build all_class_rows (mimics _run_projection SPARQL query)
    all_class_rows = []
    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?class ?label ?comment
    WHERE {
        ?class a owl:Class .
        OPTIONAL { ?class rdfs:label ?label }
        OPTIONAL { ?class rdfs:comment ?comment }
        FILTER(isIRI(?class))
    }
    """
    for row in g.query(query):
        all_class_rows.append((str(row['class']), row))

    # Collect hub domain namespaces (peer exclusion)
    hub_ns = set()
    for onto_file in ONTOLOGIES_DIR.glob("*.ttl"):
        if onto_file.name.startswith("_"):
            continue
        tmp = Graph()
        tmp.parse(onto_file, format="turtle")
        for onto in tmp.subjects(RDF.type, OWL.Ontology):
            uri = str(onto)
            ns = uri + "#" if "#" not in uri else uri.rsplit("#", 1)[0] + "#"
            hub_ns.add(ns)
            hub_ns.add(ns.rstrip("#"))

    imported = _discover_whitelisted_imports(
        g, namespace, all_class_rows,
        projection_ext_path=ext_path if ext_path.exists() else None,
        gold_ext_path=None,
        target="silver",
        hub_domain_namespaces=hub_ns,
    )
    classes.extend(imported)

    return g, namespace, classes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client_ontology():
    """Load the client domain ontology with silver-ext merged."""
    return _load_ontology("client")


@pytest.fixture(scope="module")
def invoice_ontology():
    """Load the invoice domain ontology with silver-ext merged."""
    return _load_ontology("invoice")


@pytest.fixture(scope="module")
def client_dbt_artifacts(client_ontology):
    """Generate dbt artifacts for the client domain."""
    from kairos_ontology.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = client_ontology
    gold_ext = EXTENSIONS_DIR / "client-gold-ext.ttl"
    silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )


@pytest.fixture(scope="module")
def invoice_dbt_artifacts(invoice_ontology):
    """Generate dbt artifacts for the invoice domain."""
    from kairos_ontology.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = invoice_ontology
    gold_ext = EXTENSIONS_DIR / "invoice-gold-ext.ttl"
    silver_ext = EXTENSIONS_DIR / "invoice-silver-ext.ttl"
    # Cross-domain FK: issuedTo → Client needs client's silver-ext for NK resolution
    client_silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    peer_exts = [client_silver_ext] if client_silver_ext.exists() else []
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="invoice",
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
        peer_ext_paths=peer_exts,
    )


@pytest.fixture(scope="module")
def logistics_ontology():
    """Load the logistics domain (import-only, DD-021) with whitelisted imports."""
    return _load_ontology_with_imports("logistics")


@pytest.fixture(scope="module")
def logistics_dbt_artifacts(logistics_ontology):
    """Generate dbt artifacts for the logistics domain (ref-model classes)."""
    from kairos_ontology.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = logistics_ontology
    silver_ext = EXTENSIONS_DIR / "logistics-silver-ext.ttl"
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="logistics",
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
    )
