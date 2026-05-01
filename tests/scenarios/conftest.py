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
    )


@pytest.fixture(scope="module")
def invoice_dbt_artifacts(invoice_ontology):
    """Generate dbt artifacts for the invoice domain."""
    from kairos_ontology.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    graph, namespace, classes = invoice_ontology
    gold_ext = EXTENSIONS_DIR / "invoice-gold-ext.ttl"
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
    )
