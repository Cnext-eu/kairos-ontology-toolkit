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
from ._provenance import prepend_provenance, strip_provenance

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


#: Extraction ``status`` (README.md:68) whose terms are excluded from the
#: glossary (C4, #417/#416b): the document was never actually read, so any
#: ``extracted_terms`` present would be stale/hypothetical rather than
#: confirmed evidence.
_EXCLUDED_STATUS = "skipped"


@dataclass
class GlossaryBuildResult:
    """Outcome of a glossary build (for CLI reporting)."""

    concepts: list[GlossaryConcept] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    skipped_terms: int = 0
    excluded_sources: list[str] = field(default_factory=list)
    #: Hand-authored concepts carried over from the file being replaced (#906).
    kept_authored: int = 0
    #: Of those, how many share an IRI with a generated concept and won over it.
    authored_overrides: int = 0


#: Marks a concept a human wrote, so every later rebuild keeps it (#906). Carried-over
#: concepts get it the first time, and a rebuild keeps any concept that has it -- the
#: file's own header says build-glossary wrote it by then, so the header alone would
#: forget them on the second run.
AUTHORED_PROVENANCE = "authored by hand; kept by build-glossary"


class GlossaryOverwriteRefused(Exception):
    """Writing would replace a glossary that holds concepts with one that holds none."""


def to_pascal_case(text: str) -> str:
    """Convert free text to a PascalCase local name.

    Example: ``"Transport Document"`` -> ``"TransportDocument"``; non-alphanumeric
    runs are treated as word separators.  Returns ``"Concept"`` for empty input.
    """
    words = re.split(r"[^A-Za-z0-9]+", text.strip())
    pascal = "".join(w[:1].upper() + w[1:] for w in words if w)
    return pascal or "Concept"


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


def collect_terms(
    extraction_dir: Path,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Load every extracted term across all extraction files in *extraction_dir*.

    Returns ``(terms, sources, excluded_sources)`` where *terms* is the flat list
    of term dicts (in deterministic file-then-order order), *sources* is the
    sorted list of extraction filenames whose terms were included, and
    *excluded_sources* is the sorted list of extraction filenames whose terms
    were excluded because their ``status`` is ``skipped`` (C4, #417/#416b) --
    ``processed`` and ``partial`` records are both included: a ``partial``
    record is real, confirmed evidence for the section(s) that *were* read;
    only a genuinely unread/skipped document contributes no terms. A record
    with a missing/unrecognized ``status`` is treated as included, for
    backward compatibility with extraction files written before ``status`` was
    read anywhere (C2).
    """
    terms: list[dict[str, Any]] = []
    sources: list[str] = []
    excluded_sources: list[str] = []
    if not extraction_dir.is_dir():
        return (terms, sources, excluded_sources)

    for path in sorted(extraction_dir.glob(f"*{EXTRACTION_SUFFIX}")):
        try:
            data = load_extraction(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            logger.warning("Skipping unreadable extraction %s: %s", path, exc)
            continue
        if data.get("status") == _EXCLUDED_STATUS:
            excluded_sources.append(path.name)
            continue
        sources.append(path.name)
        extracted = data.get("extracted_terms")
        if not isinstance(extracted, list):
            continue
        for entry in extracted:
            if isinstance(entry, dict):
                terms.append(entry)
    return (terms, sources, excluded_sources)


def _normalize_relation(value: Any) -> str:
    """Normalize a per-term ``link_relation`` to a supported value."""
    if isinstance(value, str) and value.strip() in _VALID_RELATIONS:
        return value.strip()
    return _SEE_ALSO


def _unique_local_name(pref_label: str, key: str, used: dict[str, str]) -> str:
    """A stable PascalCase local name for *pref_label*, unique within one build.

    Two distinct labels can PascalCase to the same name ("Port of loading" and
    "Port Of Loading"), and since #909 made the label the concept identity, a collision
    would silently merge two concepts in the emitted graph -- the same class of defect
    one level down. Collisions get a numeric suffix rather than being folded together.

    *used* maps local name -> the group key that claimed it, so re-deriving a name for a
    key that already owns it is idempotent.
    """
    base = to_pascal_case(pref_label)
    if used.get(base) in (None, key):
        used[base] = key
        return base
    index = 2
    while used.get(f"{base}{index}") not in (None, key):
        index += 1
    used[f"{base}{index}"] = key
    return f"{base}{index}"


def aggregate_concepts(
    terms: list[dict[str, Any]],
    *,
    company_specific_only: bool = False,
) -> tuple[list[GlossaryConcept], int]:
    """Group flat extracted terms into deduplicated SKOS concepts.

    Terms are grouped by their normalized ``prefLabel``.  ``altLabel`` values are
    collected and deduplicated per concept; the first non-empty ``definition`` wins,
    and the first non-empty ``linked_iri`` is carried as a cross-reference.

    **Grouping is by label, not by linked IRI** (DD-063 as amended, issue #909). The
    original rule keyed a concept on its ``linked_iri`` where one was present, which
    made the IRI the concept's *identity* rather than a reference. A business glossary
    exists precisely because many business words map onto few canonical classes, so on
    a real hub sixteen party roles -- cargo broker, freight forwarder, ship owner, ship
    manager, charterer and others -- all legitimately carried the same ``TradeParty``
    IRI, collapsed into one concept, and fifteen prefLabels with their authored
    definitions were discarded. The glossary went from 164 concepts to 82 by adding the
    links the discovery skill asks for.

    Several concepts referring to one class is correct and is what ``rdfs:seeAlso``
    means. Synonyms are what ``altLabel`` is for, and grouping by label still merges
    the same term recorded in two documents.

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
    used_local_names: dict[str, str] = {}
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
        key = f"label::{pref.lower()}"

        concept = grouped.get(key)
        if concept is None:
            concept = GlossaryConcept(
                local_name=_unique_local_name(pref, key, used_local_names),
                pref_label=pref,
                linked_iri=linked,
                link_relation=_normalize_relation(term.get("link_relation")),
            )
            grouped[key] = concept
            order.append(key)
        elif concept.linked_iri is None and linked is not None:
            # The same term recorded in two documents, linked in only one of them.
            concept.linked_iri = linked
            concept.link_relation = _normalize_relation(term.get("link_relation"))

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


def _authored_concepts(existing: Graph, *, whole_file_authored: bool) -> list[URIRef]:
    """Concepts in *existing* a human wrote: every one, or those carrying the mark."""
    concepts = [c for c in existing.subjects(RDF.type, SKOS.Concept) if isinstance(c, URIRef)]
    if whole_file_authored:
        return sorted(concepts)
    mark = Literal(AUTHORED_PROVENANCE)
    return sorted(c for c in concepts if (c, DCTERMS.provenance, mark) in existing)


def _read_existing_glossary(output_path: Path) -> tuple[Graph, bool] | None:
    """``(graph, whole_file_authored)`` for the file about to be replaced, or ``None``.

    A file without the ``build-glossary`` provenance header was written by a person:
    every concept in it is theirs. A file with the header holds generated concepts, plus
    any a previous rebuild carried over and marked.
    """
    if not output_path.is_file():
        return None
    from .ontology_loader import SemanticProfile, load_ontology

    text = output_path.read_text(encoding="utf-8")
    header = text[: len(text) - len(strip_provenance(text))]
    # Through the canonical loader (DD-103): a glossary has no imports, so the asserted
    # graph is exactly the file's own triples. Read-only -- the result may be cached.
    graph = load_ontology(output_path, profile=SemanticProfile.ASSERTED).graph
    return graph, "build-glossary" not in header


def build_glossary(
    *,
    extraction_dir: Path,
    output_path: Path,
    glossary_namespace: str,
    scheme_label: str,
    scheme_description: str | None = None,
    company_specific_only: bool = False,
    allow_empty: bool = False,
) -> GlossaryBuildResult:
    """End-to-end build: read extractions, aggregate concepts, write the TTL.

    Never destroys a glossary a person wrote (#906):

    * zero concepts over a file that has some raises :class:`GlossaryOverwriteRefused`,
      unless *allow_empty* -- the usual cause is that extraction has not run yet, and a
      green check over an emptied glossary is how 52 hand-written terms were lost;
    * a concept a person wrote that the build does not regenerate is carried over and
      marked (:data:`AUTHORED_PROVENANCE`), and one that shares an IRI with a generated
      concept wins over it, because it is the client's own wording.

    Returns a :class:`GlossaryBuildResult` describing what was written.
    """
    terms, sources, excluded_sources = collect_terms(extraction_dir)
    concepts, skipped = aggregate_concepts(terms, company_specific_only=company_specific_only)
    existing = _read_existing_glossary(output_path)
    if existing is not None and not concepts and not allow_empty:
        held = sum(1 for _ in existing[0].subjects(RDF.type, SKOS.Concept))
        if held:
            reason = (
                f"{len(sources)} extraction file(s) produced no concept"
                if sources
                else "no extraction files were found"
            )
            raise GlossaryOverwriteRefused(
                f"{reason}, and {output_path} already holds {held} concept(s). Writing "
                "now would replace it with an empty glossary. Run the extraction step "
                "first (kairos-design-discovery), or pass --allow-empty to overwrite it "
                "deliberately."
            )
    graph = build_glossary_graph(
        concepts,
        glossary_namespace=glossary_namespace,
        scheme_label=scheme_label,
        scheme_description=scheme_description,
    )
    kept = overrides = 0
    if existing is not None:
        old_graph, whole_file_authored = existing
        generated = set(graph.subjects(RDF.type, SKOS.Concept))
        mark = Literal(AUTHORED_PROVENANCE)
        for concept in _authored_concepts(old_graph, whole_file_authored=whole_file_authored):
            if concept in generated:
                overrides += 1
                for triple in list(graph.triples((concept, None, None))):
                    graph.remove(triple)
            for _s, predicate, obj in old_graph.triples((concept, None, None)):
                if predicate == SKOS.inScheme:
                    obj = URIRef(glossary_namespace)
                graph.add((concept, predicate, obj))
            graph.add((concept, DCTERMS.provenance, mark))
            kept += 1
    write_glossary_graph(graph, output_path)
    return GlossaryBuildResult(
        concepts=concepts,
        sources=sources,
        skipped_terms=skipped,
        excluded_sources=excluded_sources,
        kept_authored=kept,
        authored_overrides=overrides,
    )
