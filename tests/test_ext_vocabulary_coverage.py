# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Invariant: every kairos-ext annotation read by a projector must be declared.

The vocabulary file ``src/kairos_ontology/scaffold/kairos-ext.ttl`` is the single
source of truth for the ``kairos-ext:`` annotations hub authors may use. If a
projector reads an annotation that the vocabulary does not declare, authors get no
``rdfs:comment`` documentation, no IDE autocompletion, and no SHACL validation for
it. This test guards against that drift (see the extension-vocabulary-review doc,
naming-clarity recommendation 6.4).
"""

import re
from pathlib import Path

import rdflib

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTIONS_DIR = REPO_ROOT / "src" / "kairos_ontology" / "projections"
EXT_TTL = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "kairos-ext.ttl"
INT_TTL = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "kairos-int.ttl"
EXT_NS = "https://kairos.cnext.eu/ext#"
INT_NS = "https://kairos.cnext.eu/integration#"

# KAIROS_EXT.term("annotationName")
_TERM_RE = re.compile(r'KAIROS_EXT\.term\(\s*["\']([A-Za-z0-9_]+)["\']\s*\)')
# KAIROS_EXT.annotationName  (direct attribute access; excludes the .term helper)
_ATTR_RE = re.compile(r"KAIROS_EXT\.([A-Za-z_][A-Za-z0-9_]*)")
# KAIROS_INT.term("annotationName")
_INT_TERM_RE = re.compile(r'KAIROS_INT\.term\(\s*["\']([A-Za-z0-9_]+)["\']\s*\)')
# KAIROS_INT.annotationName
_INT_ATTR_RE = re.compile(r"KAIROS_INT\.([A-Za-z_][A-Za-z0-9_]*)")


def _annotations_used_in_projectors() -> dict[str, str]:
    """Map each kairos-ext annotation consumed in a projector to its source file."""
    used: dict[str, str] = {}
    for py_file in PROJECTIONS_DIR.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        for match in _TERM_RE.finditer(source):
            used[match.group(1)] = py_file.name
        for match in _ATTR_RE.finditer(source):
            name = match.group(1)
            if name != "term":
                used[name] = py_file.name
    return used


def _annotations_declared_in_vocabulary() -> set[str]:
    """Local names of all owl:AnnotationProperty declared in kairos-ext.ttl."""
    graph = rdflib.Graph()
    graph.parse(EXT_TTL, format="turtle")
    owl_annotation = rdflib.URIRef("http://www.w3.org/2002/07/owl#AnnotationProperty")
    rdf_type = rdflib.RDF.type
    declared: set[str] = set()
    for subject in graph.subjects(rdf_type, owl_annotation):
        subject_str = str(subject)
        if subject_str.startswith(EXT_NS):
            declared.add(subject_str[len(EXT_NS):])
    return declared


def test_vocabulary_parses():
    graph = rdflib.Graph()
    graph.parse(EXT_TTL, format="turtle")
    assert len(graph) > 0


def test_every_consumed_annotation_is_declared():
    used = _annotations_used_in_projectors()
    declared = _annotations_declared_in_vocabulary()
    missing = {name: src for name, src in used.items() if name not in declared}
    assert not missing, (
        "Projectors consume kairos-ext annotations that are not declared in "
        f"kairos-ext.ttl: {missing}. Declare each one (with rdfs:label + "
        "rdfs:comment) so the vocabulary stays the single source of truth."
    )


# ---------------------------------------------------------------------------
# kairos-int: vocabulary coverage
# ---------------------------------------------------------------------------


def _int_annotations_used_in_projectors() -> dict[str, str]:
    """Map each kairos-int annotation consumed in a projector to its source file."""
    used: dict[str, str] = {}
    for py_file in PROJECTIONS_DIR.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        for match in _INT_TERM_RE.finditer(source):
            used[match.group(1)] = py_file.name
        for match in _INT_ATTR_RE.finditer(source):
            name = match.group(1)
            if name != "term":
                used[name] = py_file.name
    return used


def _int_annotations_declared_in_vocabulary() -> set[str]:
    """Local names of all owl:AnnotationProperty declared in kairos-int.ttl."""
    graph = rdflib.Graph()
    graph.parse(INT_TTL, format="turtle")
    owl_annotation = rdflib.URIRef("http://www.w3.org/2002/07/owl#AnnotationProperty")
    rdf_type = rdflib.RDF.type
    declared: set[str] = set()
    for subject in graph.subjects(rdf_type, owl_annotation):
        subject_str = str(subject)
        if subject_str.startswith(INT_NS):
            declared.add(subject_str[len(INT_NS):])
    return declared


def test_int_vocabulary_parses():
    graph = rdflib.Graph()
    graph.parse(INT_TTL, format="turtle")
    assert len(graph) > 0


def test_every_consumed_int_annotation_is_declared():
    used = _int_annotations_used_in_projectors()
    declared = _int_annotations_declared_in_vocabulary()
    missing = {name: src for name, src in used.items() if name not in declared}
    assert not missing, (
        "Projectors consume kairos-int annotations that are not declared in "
        f"kairos-int.ttl: {missing}. Declare each one (with rdfs:label + "
        "rdfs:comment) so the vocabulary stays the single source of truth."
    )
