# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic SKOS glossary builder for business discovery (DD-062).

During business discovery the ``kairos-design-discovery`` skill records the
company's alternative/business terminology as structured data in per-document
extraction files (``businessdiscovery/_extractions/*.extraction.yaml``).  Each
``extracted_terms`` entry carries an ``altLabel``, a canonical ``prefLabel``, a
``definition``, a ``category`` bucket, a ``company_specific`` flag and an
optional resolved ``linked_iri``.

Historically the skill then *hand-wrote* a one-off ``rdflib`` script every run to
turn those records into the company glossary TTL.  That serialization is purely
mechanical and identical every time, so this module implements it once: it reads
the confirmed extractions and emits a valid SKOS ``ConceptScheme`` glossary
(``businessdiscovery/{company}-glossary.ttl``) deterministically via ``rdflib``.

The *judgement* (which prefLabel, which IRI to link, splitting multi-IRI terms)
stays in the interactive skill; only the AI-free TTL writing lives here so it is
consistent, testable and idempotent.  This mirrors the split already used for
discovery bookkeeping in :mod:`kairos_ontology.core.discovery_extraction`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import DCTERMS, RDFS, SKOS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from .discovery_extraction import EXTRACTION_SUFFIX, load_extraction
from ._provenance import prepend_provenance

logger = logging.getLogger(__name__)

# Per-term link relations supported in the extraction schema.  ``seeAlso`` is the
# default (a direct reference to a hub class/property); ``relatedMatch`` is used
# for cross-references to a reference-model concept the hub hasn't claimed yet.
_SEE_ALSO = "seeAlso"
_RELATED_MATCH = "relatedMatch"
_VALID_RELATIONS = (_SEE_ALSO, _RELATED_MATCH)

# DD-071: disclaimer stamped on every generated glossary ConceptScheme. The
# business-discovery glossary is initial inspiration only — it is NOT updated
# during modeling and its seeAlso/relatedMatch links may go stale by design.
_NON_AUTHORITATIVE_NOTE = (
    "Initial, inspirational artifact from business discovery. NOT an "
    "authoritative mapping kept in sync with the domain ontology. The "
    "seeAlso/relatedMatch links are inspiration only and are not reconciled "
    "during modeling."
)


@dataclass
class GlossaryConcept:
    """An aggregated SKOS concept built from one or more extracted terms."""

    local_name: str
    pref_label: str
    alt_labels: list[str] = field(default_factory=list)
    definition: str | None = None
    linked_iri: str | None = None
    link_relation: str = _SEE_ALSO


@dataclass
class GlossaryBuildResult:
    """Outcome of a glossary build (for CLI reporting)."""

    concepts: list[GlossaryConcept] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    skipped_terms: int = 0


def to_pascal_case(text: str) -> str:
    """Convert free text to a PascalCase local name.

    Example: ``"Transport Document"`` -> ``"TransportDocument"``; non-alphanumeric
    runs are treated as word separators.  Returns ``"Concept"`` for empty input.
    """
    words = re.split(r"[^A-Za-z0-9]+", text.strip())
    pascal = "".join(w[:1].upper() + w[1:] for w in words if w)
    return pascal or "Concept"


def _iri_fragment(iri: str) -> str:
    """Return the local fragment of an IRI (after ``#`` or last ``/``)."""
    tail = iri.split("#")[-1] if "#" in iri else iri.rstrip("/").split("/")[-1]
    return tail


def derive_glossary_namespace(company_domain: str) -> str:
    """Return the glossary namespace for a company domain.

    ``"acme.com"`` -> ``"https://acme.com/glossary#"``.  A bare scheme/host passed
    with a protocol is honoured as-is (its ``/glossary#`` suffix is appended).
    """
    host = company_domain.strip().rstrip("/")
    host = re.sub(r"^https?://", "", host)
    return f"https://{host}/glossary#"


def read_company_info(hub_root: Path) -> tuple[str | None, str | None]:
    """Best-effort parse of company name + domain from the hub ``README.md``.

    Reads the scaffold-generated company-context table.  Returns
    ``(company_name, company_domain)`` with ``None`` for any field not found.
    """
    readme = hub_root / "README.md"
    if not readme.is_file():
        return (None, None)
    text = readme.read_text(encoding="utf-8", errors="replace")
    name = _table_value(text, "Company name")
    domain = _table_value(text, "Company domain")
    return (name, domain)


def _table_value(markdown: str, field_label: str) -> str | None:
    """Extract a value from a two-column markdown table row by its bolded label."""
    pattern = rf"\|\s*\*\*{re.escape(field_label)}\*\*\s*\|\s*(.+?)\s*\|"
    m = re.search(pattern, markdown, re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip().strip("`").strip()
    return value or None


def collect_terms(extraction_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load every extracted term across all extraction files in *extraction_dir*.

    Returns ``(terms, sources)`` where *terms* is the flat list of term dicts (in
    deterministic file-then-order order) and *sources* is the sorted list of
    extraction filenames that were read.
    """
    terms: list[dict[str, Any]] = []
    sources: list[str] = []
    if not extraction_dir.is_dir():
        return (terms, sources)

    for path in sorted(extraction_dir.glob(f"*{EXTRACTION_SUFFIX}")):
        try:
            data = load_extraction(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            logger.warning("Skipping unreadable extraction %s: %s", path, exc)
            continue
        sources.append(path.name)
        extracted = data.get("extracted_terms")
        if not isinstance(extracted, list):
            continue
        for entry in extracted:
            if isinstance(entry, dict):
                terms.append(entry)
    return (terms, sources)


def _normalize_relation(value: Any) -> str:
    """Normalize a per-term ``link_relation`` to a supported value."""
    if isinstance(value, str) and value.strip() in _VALID_RELATIONS:
        return value.strip()
    return _SEE_ALSO


def aggregate_concepts(
    terms: list[dict[str, Any]],
    *,
    company_specific_only: bool = False,
) -> tuple[list[GlossaryConcept], int]:
    """Group flat extracted terms into deduplicated SKOS concepts.

    Terms are grouped by their resolved ``linked_iri`` when present, otherwise by
    their normalized ``prefLabel``.  ``altLabel`` values are collected and
    deduplicated per concept; the first non-empty ``definition`` wins.

    Args:
        terms: Flat list of extracted-term dicts.
        company_specific_only: When True, drop terms whose ``company_specific`` is
            not truthy (generic industry jargon).

    Returns:
        ``(concepts, skipped)`` — concepts sorted by local name, and the count of
        terms skipped (no ``prefLabel`` or filtered out).
    """
    grouped: dict[str, GlossaryConcept] = {}
    order: list[str] = []
    skipped = 0

    for term in terms:
        if company_specific_only and not term.get("company_specific"):
            skipped += 1
            continue

        pref = (term.get("prefLabel") or "").strip()
        if not pref:
            skipped += 1
            continue

        linked = term.get("linked_iri")
        linked = linked.strip() if isinstance(linked, str) and linked.strip() else None
        key = linked or f"label::{pref.lower()}"

        concept = grouped.get(key)
        if concept is None:
            local = _iri_fragment(linked) if linked else to_pascal_case(pref)
            concept = GlossaryConcept(
                local_name=local,
                pref_label=pref,
                linked_iri=linked,
                link_relation=_normalize_relation(term.get("link_relation")),
            )
            grouped[key] = concept
            order.append(key)

        alt = term.get("altLabel")
        if isinstance(alt, str) and alt.strip() and alt.strip() not in concept.alt_labels:
            concept.alt_labels.append(alt.strip())

        definition = term.get("definition")
        if not concept.definition and isinstance(definition, str) and definition.strip():
            concept.definition = definition.strip()

    concepts = [grouped[k] for k in order]
    concepts.sort(key=lambda c: (c.local_name.lower(), c.pref_label.lower()))
    return (concepts, skipped)


def build_glossary_graph(
    concepts: list[GlossaryConcept],
    *,
    glossary_namespace: str,
    scheme_label: str,
    scheme_description: str | None = None,
) -> Graph:
    """Build an rdflib :class:`~rdflib.Graph` for the SKOS glossary overlay."""
    graph = Graph()
    glossary = Namespace(glossary_namespace)
    graph.bind("skos", SKOS)
    graph.bind("rdfs", RDFS)
    graph.bind("dct", DCTERMS)
    graph.bind("glossary", glossary)

    scheme = URIRef(glossary_namespace)
    graph.add((scheme, RDF.type, SKOS.ConceptScheme))
    graph.add((scheme, RDFS.label, Literal(scheme_label)))
    if scheme_description:
        graph.add((scheme, DCTERMS.description, Literal(scheme_description)))
    # DD-071: stamp every generated glossary as inspirational / non-authoritative
    # so downstream modeling treats it as background context, not a binding source
    # that must be kept in sync (seeAlso/relatedMatch links may go stale by design).
    graph.add((scheme, RDFS.comment, Literal(_NON_AUTHORITATIVE_NOTE)))
    graph.add((scheme, SKOS.editorialNote, Literal(_NON_AUTHORITATIVE_NOTE)))

    for concept in concepts:
        node = glossary[concept.local_name]
        graph.add((node, RDF.type, SKOS.Concept))
        graph.add((node, SKOS.inScheme, scheme))
        graph.add((node, SKOS.prefLabel, Literal(concept.pref_label, lang="en")))
        for alt in concept.alt_labels:
            graph.add((node, SKOS.altLabel, Literal(alt, lang="en")))
        if concept.definition:
            graph.add((node, SKOS.definition, Literal(concept.definition)))
        if concept.linked_iri:
            predicate = (
                SKOS.relatedMatch if concept.link_relation == _RELATED_MATCH else RDFS.seeAlso
            )
            graph.add((node, predicate, URIRef(concept.linked_iri)))

    return graph


def write_glossary_graph(graph: Graph, output_path: Path) -> Path:
    """Serialize *graph* to Turtle at *output_path*, creating parent dirs."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ttl = prepend_provenance(graph.serialize(format="turtle"), "build-glossary")
    output_path.write_text(ttl, encoding="utf-8")
    logger.info("Wrote glossary to %s", output_path)
    return output_path


def build_glossary(
    *,
    extraction_dir: Path,
    output_path: Path,
    glossary_namespace: str,
    scheme_label: str,
    scheme_description: str | None = None,
    company_specific_only: bool = False,
) -> GlossaryBuildResult:
    """End-to-end build: read extractions, aggregate concepts, write the TTL.

    Returns a :class:`GlossaryBuildResult` describing what was written.
    """
    terms, sources = collect_terms(extraction_dir)
    concepts, skipped = aggregate_concepts(
        terms, company_specific_only=company_specific_only
    )
    graph = build_glossary_graph(
        concepts,
        glossary_namespace=glossary_namespace,
        scheme_label=scheme_label,
        scheme_description=scheme_description,
    )
    write_glossary_graph(graph, output_path)
    return GlossaryBuildResult(concepts=concepts, sources=sources, skipped_terms=skipped)
