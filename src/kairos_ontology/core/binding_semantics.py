# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ontology-only predicates shared by compiler and projection code."""

from rdflib import Graph, RDFS, URIRef

from .projections.shared import KAIROS_EXT


def is_discriminator_subclass(graph: Graph, class_uri: str) -> tuple[bool, str | None]:
    """Return whether a class is folded into a discriminator-strategy parent."""
    from .projections.uri_utils import extract_local_name

    for parent in graph.objects(URIRef(class_uri), RDFS.subClassOf):
        if not isinstance(parent, URIRef) or str(parent).startswith("http://www.w3.org/"):
            continue
        strategy = graph.value(parent, KAIROS_EXT.inheritanceStrategy)
        if strategy and str(strategy) == "discriminator":
            return True, extract_local_name(str(parent))
    return False, None
