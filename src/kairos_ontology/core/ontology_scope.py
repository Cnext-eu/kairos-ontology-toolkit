# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim-independent ontology scope discovery."""

from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF


def collect_hub_domain_bases(ontologies_dir: Path) -> set[str]:
    """Collect ontology document IRIs declared by hub ontology files."""
    bases: set[str] = set()
    if not ontologies_dir.is_dir():
        return bases
    for path in sorted(ontologies_dir.glob("*.ttl")):
        graph = Graph().parse(path, format="turtle")
        bases.update(
            str(subject).rstrip("#/")
            for subject in graph.subjects(RDF.type, OWL.Ontology)
            if isinstance(subject, URIRef)
        )
    return bases
