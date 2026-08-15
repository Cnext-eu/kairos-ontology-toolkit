# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Concept-level source evidence for discovery judgments (issue #507, Layer C of #505).

The problem this closes: during discovery, an ``optional``-tier concept with real source data
behind it was still routinely judged ``not-applicable``, which is the one outcome
:mod:`kairos_ontology.core.design_landscape` treats as the *opposite* of demand evidence. On
the CLdN hub that deferred 20 optional-tier concepts, including a 289K-row cost-accounting
table that BI reports actively used. The rule the discovery skill should follow is simple --
**if data exists and the concept is optional, model it** -- but nothing deterministic ever told
the skill (or the human reviewing it) that data existed for a given concept.

DD-160 (#496/#498) already joined source affinity to modeled/bound state, but at **domain**
granularity: it answers "does this domain have source tables nobody bound?", not "does this
*concept* have source data?". This module is the concept-level half, and it is deliberately
built from artifacts that already exist:

* ``integration/sources/_analysis/*-alignment.yaml`` -- ``propose-alignment``'s per-table
  ``ref_class``, which lives in the same identifier space as an archetype concept ``uri``.
  This is direct, concept-level evidence.
* ``integration/sources/_analysis/*-affinity.yaml`` -- ``analyse-sources``' per-table domain
  assignment, usable for a concept only once something says which domain(s) that concept
  informs (its ``likely_domains``). Weaker, and labelled as such.

Both are persisted, deterministic reads of an LLM pass that already ran at Stage 1, well before
discovery-conformance at Stage 2 -- so no new LLM call, no new artifact, and no new ordering
constraint on the lifecycle.

Resolution is scoped to **the archetype's own concept catalog**, not the accelerator class
universe. That is a deliberate narrowing from :func:`design_landscape._resolve_alignment_class`,
which cannot be reused here for two reasons: it needs the full activated-module class record,
and it prefers ``likely_entity_uri`` -- a field ``propose-alignment`` only populates once a
conformance artifact already exists, which is circular for the pre-discovery case this module
serves.

Leaf module: no :mod:`kairos_ontology.cli` imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import yaml

from .archetype_loader import Archetype

SCHEMA_VERSION = 1

#: Direct, concept-level: a source table was aligned to this very class.
KIND_ALIGNMENT = "alignment"
#: Indirect: source tables were assigned to a domain this concept is tagged to inform.
KIND_AFFINITY = "affinity"

_ANALYSIS_SUBDIR = Path("integration") / "sources" / "_analysis"


@dataclass(frozen=True)
class ConceptSourceEvidence:
    """Why we believe source data exists for one archetype concept."""

    concept_uri: str
    kind: str
    #: ``"<system>.<table>"`` strings, sorted. Never empty when this object exists.
    tables: tuple[str, ...]
    #: Domains the evidence came through (affinity only; empty for alignment evidence).
    domains: tuple[str, ...] = ()

    def describe(self, *, limit: int = 3) -> str:
        """One-line, human-facing summary naming real tables -- never a bare count.

        A warning that says "source evidence exists" without naming it is unactionable; the
        reviewer's next question is always *which* data, and they should not have to go
        looking for it.
        """
        shown = ", ".join(self.tables[:limit])
        extra = f" (+{len(self.tables) - limit} more)" if len(self.tables) > limit else ""
        if self.kind == KIND_ALIGNMENT:
            return f"{len(self.tables)} source table(s) aligned to this concept: {shown}{extra}"
        domains = ", ".join(self.domains) or "?"
        return (
            f"{len(self.tables)} source table(s) with affinity to domain(s) "
            f"{domains}: {shown}{extra}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tables": list(self.tables),
            "domains": list(self.domains),
        }


def _local_name(uri: str) -> str:
    parsed = urlsplit(uri)
    return (parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]).strip()


def _concept_index(concept_uris: Iterable[str]) -> tuple[set[str], dict[str, str | None]]:
    """Return ``({uris}, casefolded local name -> uri | None)``.

    A local name shared by two concepts maps to ``None``: matching it either way would be a
    coin flip, and silently picking one would put fabricated evidence in front of a reviewer.
    """
    uris = {uri for uri in concept_uris if isinstance(uri, str) and uri.strip()}
    by_name: dict[str, str | None] = {}
    for uri in sorted(uris):
        key = _local_name(uri).casefold()
        if not key:
            continue
        by_name[key] = None if key in by_name else uri
    return uris, by_name


def archetype_concept_uris(archetype: Archetype) -> tuple[str, ...]:
    """Convenience projection for callers that hold a resolved archetype."""
    return tuple(concept.uri for concept in archetype.core_concepts)


def _read_analysis_documents(analysis_dir: Path, suffix: str) -> Iterable[tuple[Path, dict]]:
    if not analysis_dir.is_dir():
        return []
    documents = []
    for path in sorted(analysis_dir.glob(f"*{suffix}")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue  # advisory input: a corrupt report must never break discovery
        if isinstance(document, dict):
            documents.append((path, document))
    return documents


def _alignment_evidence(
    analysis_dir: Path, concept_uris: Iterable[str]
) -> tuple[dict[str, set[str]], list[str]]:
    """Map concept URI -> ``{"<system>.<table>"}`` from ``propose-alignment`` output."""

    known, by_name = _concept_index(concept_uris)
    hits: dict[str, set[str]] = {}
    gaps: list[str] = []
    for path, document in _read_analysis_documents(analysis_dir, "-alignment.yaml"):
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            system = str(table.get("system") or "").strip()
            name = str(table.get("table") or "").strip()
            if not system or not name:
                continue
            # likely_entity_uri first when present (the already-disambiguated anchor), then
            # ref_class, which is usually a bare local name.
            resolved: str | None = None
            for candidate in (table.get("likely_entity_uri"), table.get("ref_class")):
                token = str(candidate or "").strip()
                if not token:
                    continue
                if "://" in token:
                    resolved = token if token in known else None
                else:
                    key = token.casefold()
                    if key in by_name:
                        resolved = by_name[key]
                        if resolved is None:
                            gaps.append(
                                f"{path.name}: alignment class {token!r} matches more than one "
                                "archetype concept by local name; skipped."
                            )
                if resolved is not None:
                    break
            if resolved is not None:
                hits.setdefault(resolved, set()).add(f"{system}.{name}")
    return hits, gaps


def _affinity_evidence(
    analysis_dir: Path, concept_domains: Mapping[str, Iterable[str]]
) -> dict[str, tuple[set[str], set[str]]]:
    """Map concept URI -> ``({tables}, {domains})`` via each concept's ``likely_domains``.

    A concept with no ``likely_domains`` gets nothing: an empty tag means *cross-cutting*
    (it applies to every domain), so treating it as "matches every domain's tables" would
    manufacture evidence for exactly the concepts least likely to have a source table.
    """

    tables_by_domain: dict[str, set[str]] = {}
    for _, document in _read_analysis_documents(analysis_dir, "-affinity.yaml"):
        if document.get("schema_version") != 2:
            continue
        system = str(document.get("system") or "").strip()
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            name = str(table.get("table") or "").strip()
            domain = str(table.get("domain") or "").strip()
            if not name or not domain:
                continue
            label = f"{system}.{name}" if system else name
            tables_by_domain.setdefault(domain.casefold(), set()).add(label)
            for extra in table.get("secondary_domains") or ():
                if isinstance(extra, dict):
                    secondary = str(extra.get("domain") or "").strip()
                    if secondary:
                        tables_by_domain.setdefault(secondary.casefold(), set()).add(label)

    hits: dict[str, tuple[set[str], set[str]]] = {}
    for uri, domains in concept_domains.items():
        matched_tables: set[str] = set()
        matched_domains: set[str] = set()
        for domain in domains or ():
            key = str(domain or "").strip().casefold()
            if key and key in tables_by_domain:
                matched_tables |= tables_by_domain[key]
                matched_domains.add(str(domain).strip())
        if matched_tables:
            hits[uri] = (matched_tables, matched_domains)
    return hits


def collect_concept_source_evidence(
    concept_uris: Iterable[str],
    hub_root: Path,
    *,
    concept_domains: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, ConceptSourceEvidence]:
    """Return the source evidence available for each concept in *concept_uris*.

    Takes plain URIs rather than an :class:`Archetype` so every caller can use it: ``build``
    and ``judgments-template`` hold a resolved archetype (see :func:`archetype_concept_uris`),
    but ``summarize`` only ever holds a list of judgment entries.

    *concept_domains* maps concept URI -> its authored ``likely_domains``. Supply it when the
    caller has judgments (``build``/``validate``); omit it in ``judgments-template``, where the
    tags do not exist yet -- alignment evidence still works there, which is the stronger signal
    anyway.

    Alignment evidence always wins over affinity evidence for the same concept: it names the
    concept directly, where affinity only says "something in this concept's domain has data".
    """

    hub_root = Path(hub_root)
    analysis_dir = hub_root / _ANALYSIS_SUBDIR
    known = {uri for uri in concept_uris if isinstance(uri, str) and uri.strip()}
    evidence: dict[str, ConceptSourceEvidence] = {}

    aligned, _gaps = _alignment_evidence(analysis_dir, known)
    for uri, tables in aligned.items():
        evidence[uri] = ConceptSourceEvidence(
            concept_uri=uri, kind=KIND_ALIGNMENT, tables=tuple(sorted(tables))
        )

    if concept_domains:
        scoped = {uri: doms for uri, doms in concept_domains.items() if uri in known}
        for uri, (tables, domains) in _affinity_evidence(analysis_dir, scoped).items():
            if uri in evidence:
                continue  # direct alignment evidence already recorded, and it is stronger
            evidence[uri] = ConceptSourceEvidence(
                concept_uri=uri,
                kind=KIND_AFFINITY,
                tables=tuple(sorted(tables)),
                domains=tuple(sorted(domains)),
            )
    return evidence


def concept_domains_from_outcomes(
    outcomes: Iterable[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Project ``core_concepts`` judgment entries to ``{concept uri: likely_domains}``."""

    mapping: dict[str, list[str]] = {}
    for entry in outcomes:
        if not isinstance(entry, Mapping):
            continue
        uri = entry.get("uri")
        domains = entry.get("likely_domains")
        if isinstance(uri, str) and uri.strip() and isinstance(domains, list):
            mapping[uri] = [str(item).strip() for item in domains if str(item or "").strip()]
    return mapping
