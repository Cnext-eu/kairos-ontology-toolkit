# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Determinism probe — generates acme-hub client dbt artifacts and prints a hash.

Run as a standalone script (see ``tests/test_determinism.py``).  The whole point
is to execute in a *fresh* process so we can vary ``PYTHONHASHSEED`` and prove the
generated artifact map is byte-stable when the generation timestamp is pinned via
``KAIROS_GENERATED_AT``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.uri_utils import extract_local_name

HUB_ROOT = Path(__file__).parent / "scenarios" / "acme-hub"
ONTOLOGIES_DIR = HUB_ROOT / "model" / "ontologies"
EXTENSIONS_DIR = HUB_ROOT / "model" / "extensions"
SHAPES_DIR = HUB_ROOT / "model" / "shapes"
MAPPINGS_DIR = HUB_ROOT / "model" / "mappings"
SOURCES_DIR = HUB_ROOT / "integration" / "sources"
TEMPLATE_DIR = (
    Path(__file__).parent.parent / "src" / "kairos_ontology" / "templates" / "dbt"
)


def _load_client() -> tuple[Graph, str, list[dict]]:
    g = Graph()
    g.parse(ONTOLOGIES_DIR / "client.ttl", format="turtle")
    ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    if ext.exists():
        g.parse(ext, format="turtle")
    namespace = None
    for onto in g.subjects(RDF.type, OWL.Ontology):
        uri = str(onto)
        namespace = uri + "#" if "#" not in uri else uri.rsplit("#", 1)[0] + "#"
        break
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        cls_uri = str(cls)
        if not cls_uri.startswith(namespace):
            continue
        local = extract_local_name(cls_uri)
        classes.append({
            "uri": cls_uri,
            "name": local,
            "label": str(g.value(cls, RDFS.label) or local),
            "comment": str(g.value(cls, RDFS.comment) or f"{local} entity"),
        })
    return g, namespace, classes


def build_artifacts() -> dict[str, str]:
    graph, namespace, classes = _load_client()
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


def artifact_hash(artifacts: dict) -> str:
    canonical = _canonical(artifacts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(artifacts: dict) -> str:
    import json

    return json.dumps(artifacts, sort_keys=True, ensure_ascii=False, default=str)


if __name__ == "__main__":
    print(artifact_hash(build_artifacts()))
