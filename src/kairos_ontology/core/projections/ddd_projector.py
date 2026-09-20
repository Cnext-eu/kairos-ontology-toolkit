# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DDD documentation projector (DD-091, DD-229).

One-way, documentation-only projection of the Domain-Driven Design overlay into:

- ``{domain}-aggregate-overview.mmd``— Mermaid aggregate/tactical-pattern overview
- ``{domain}-ddd-report.md``         — Markdown architecture report

The context map is hub-wide by nature and is drawn once, under ``contexts/``, by
:mod:`ddd_context_projector` (DD-230); the per-domain ``{domain}-context-map.mmd`` that
used to be written here rendered only the edges this domain's overlay declared (#846).

The graph rendered is the domain ontology + the hub-wide strategic file
(``ddd-contexts-ext.ttl``, DD-229) + the domain's own ``{domain}-ddd-ext.ttl`` overlay +
the packaged vocabulary. Only a domain that has its own overlay produces output: the
strategic file alone describes the hub, not a domain, and a hub-wide view of it is a
separate artifact.

Output is deterministic (sorted, no embedded timestamps) and never influences
silver/gold/dbt/Power BI generation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from .shared import mermaid_header
from .uri_utils import extract_local_name

DDD = Namespace("https://kairos.cnext.eu/ddd#")


def _sanitize(node_id: str) -> str:
    """Make a Mermaid-safe node id from a local name."""
    return re.sub(r"[^0-9A-Za-z_]", "_", node_id)


def _label(graph: Graph, uri: URIRef) -> str:
    """Return rdfs:label if present, else the local name."""
    lbl = graph.value(uri, RDFS.label)
    return str(lbl) if lbl else extract_local_name(str(uri))


def _merge_overlay(
    graph: Graph,
    overlay_path: Optional[Path],
    strategic_path: Optional[Path] = None,
) -> Graph:
    """Return a graph combining the domain graph, the strategic file, the overlay, and the vocab.

    The strategic file supplies the context declarations an overlay references by IRI
    (DD-229); the vocabulary is merged so controlled-individual labels (tactical patterns,
    relationship patterns, subdomain types) resolve for rendering.
    """
    merged = Graph()
    for triple in graph:
        merged.add(triple)
    if strategic_path and Path(strategic_path).exists():
        merged.parse(strategic_path, format="turtle")
    if overlay_path and Path(overlay_path).exists():
        merged.parse(overlay_path, format="turtle")
    from ..ddd import load_ddd_vocabulary

    for triple in load_ddd_vocabulary():
        merged.add(triple)
    return merged


def _collect(graph: Graph, overlay_graph: Graph) -> dict:
    """Extract DDD structures from a merged graph.

    *overlay_graph* is the domain's overlay alone; it decides which contexts this domain
    *participates in* -- those it declares itself (a pre-DD-229 layout) or assigns a class
    to -- so a per-domain report does not list every context in the hub.
    """
    contexts = sorted(set(graph.subjects(RDF.type, DDD.BoundedContext)), key=str)

    relationships = []
    for rel in sorted(set(graph.subjects(RDF.type, DDD.ContextRelationship)), key=str):
        src = graph.value(rel, DDD.sourceContext)
        tgt = graph.value(rel, DDD.targetContext)
        pattern = graph.value(rel, DDD.relationshipPattern)
        relationships.append((rel, src, tgt, pattern))

    # class -> tactical pattern
    tactical: dict[URIRef, URIRef] = {}
    for cls, pat in graph.subject_objects(DDD.tacticalPattern):
        tactical[cls] = pat

    # aggregate member -> root
    members: dict[URIRef, URIRef] = {}
    for member, root in graph.subject_objects(DDD.aggregateRoot):
        members[member] = root

    # class -> bounded context assignment
    assignments: dict[URIRef, URIRef] = {}
    for elem, ctx in graph.subject_objects(DDD.boundedContext):
        assignments[elem] = ctx

    # context -> subdomain type (DD-229)
    subdomain: dict[URIRef, URIRef] = {}
    for ctx, kind in graph.subject_objects(DDD.subdomainType):
        subdomain[ctx] = kind

    # class -> invariants (DD-229), sorted for determinism
    invariants: dict[URIRef, list[str]] = {}
    for cls, text in graph.subject_objects(DDD.invariant):
        invariants.setdefault(cls, []).append(str(text))
    for texts in invariants.values():
        texts.sort()

    published = set()
    for subj, val in graph.subject_objects(DDD.publishedLanguage):
        if str(val).lower() in ("true", "1"):
            published.add(subj)

    notes: list[tuple[URIRef, str]] = []
    for subj, note in graph.subject_objects(DDD.designNote):
        notes.append((subj, str(note)))
    notes.sort(key=lambda x: str(x[0]))

    declared_here = set(overlay_graph.subjects(RDF.type, DDD.BoundedContext))
    domain_contexts = declared_here | {
        ctx for ctx in assignments.values() if isinstance(ctx, URIRef)
    }

    return {
        "contexts": contexts,
        "relationships": relationships,
        "tactical": tactical,
        "members": members,
        "assignments": assignments,
        "subdomain": subdomain,
        "invariants": invariants,
        "published": published,
        "notes": notes,
        "domain_contexts": domain_contexts,
    }


def _has_content(data: dict) -> bool:
    """True when the overlay says anything about this domain.

    ``assignments`` counts: once contexts live in the strategic file (DD-229) an overlay
    that only places classes into contexts is the normal case, and dropping it would make
    the domain vanish from the output with nothing to say why.
    """
    return bool(
        data["contexts"]
        or data["relationships"]
        or data["tactical"]
        or data["members"]
        or data["assignments"]
    )


def _domain_relationships(data: dict) -> list[tuple]:
    """The context-map edges touching a context this domain participates in."""
    own = data["domain_contexts"]
    return [edge for edge in data["relationships"] if edge[1] in own or edge[2] in own]


def _aggregate_overview_mmd(graph: Graph, data: dict, domain: str) -> str:
    lines = [
        *mermaid_header(indent=""),
        "%% DDD aggregate overview",
        "graph TD",
    ]

    # Group aggregate members by root.
    roots: dict[URIRef, list[URIRef]] = {}
    for member, root in sorted(data["members"].items(), key=lambda x: str(x[0])):
        roots.setdefault(root, []).append(member)

    rendered: set[str] = set()

    def node(cls: URIRef) -> str:
        nid = _sanitize(extract_local_name(str(cls)))
        if nid not in rendered:
            pat = data["tactical"].get(cls)
            stereotype = f"«{extract_local_name(str(pat))}»<br/>" if pat is not None else ""
            lines.append(f'    {nid}["{stereotype}{_label(graph, cls)}"]')
            rendered.add(nid)
        return nid

    for root in sorted(roots, key=str):
        rnode = node(root)
        for member in roots[root]:
            mnode = node(member)
            lines.append(f"    {rnode} --> {mnode}")

    # Classes with a tactical pattern but not part of an aggregate edge.
    for cls in sorted(data["tactical"], key=str):
        if cls not in data["members"] and cls not in roots:
            node(cls)

    return "\n".join(lines) + "\n"


def _report_md(graph: Graph, data: dict, domain: str, meta: dict) -> str:
    version = meta.get("toolkit_version", "")
    lines = [
        f"# DDD Architecture Overview — {domain}",
        "",
        "> Generated by `kairos-ontology project --target ddd` (DD-091). "
        "Documentation only — not a governance or projection-control source.",
        "",
    ]
    if version:
        lines += [f"**Toolkit version:** {version}", ""]

    # Bounded contexts this domain participates in (DD-229)
    lines += ["## Bounded Contexts", ""]
    own = sorted(data["domain_contexts"], key=str)
    if own:
        lines += [
            "| Context | Subdomain | Published Language | Note |",
            "|---------|-----------|--------------------|------|",
        ]
        note_map = {s: n for s, n in data["notes"]}
        for ctx in own:
            kind = data["subdomain"].get(ctx)
            kind_label = _label(graph, kind) if kind is not None else "—"
            pub = "yes" if ctx in data["published"] else "—"
            note = note_map.get(ctx, "—")
            lines.append(f"| {_label(graph, ctx)} | {kind_label} | {pub} | {note} |")
        others = len(data["contexts"]) - len(
            [c for c in data["contexts"] if c in data["domain_contexts"]]
        )
        if others > 0:
            lines += [
                "",
                f"_{others} other bounded context(s) are declared hub-wide and not "
                "referenced by this domain._",
            ]
    else:
        lines.append("_No bounded contexts assigned in this domain's overlay._")
    lines.append("")

    # Context relationships touching this domain's contexts. The picture is hub-wide by
    # nature and lives beside this report as `contexts/context-map.mmd` (DD-230); a
    # per-domain map rendered only the edges the domain's own overlay declared, which
    # read as "no relationships" for every other domain (#846).
    lines += ["## Context Map", ""]
    lines += ["_Hub-wide map: `contexts/context-map.mmd`, beside this report._", ""]
    edges = _domain_relationships(data)
    if edges:
        lines += ["| Source | Pattern | Target |", "|--------|---------|--------|"]
        for _rel, src, tgt, pattern in edges:
            s = _label(graph, src) if src is not None else "—"
            t = _label(graph, tgt) if tgt is not None else "—"
            p = (
                _label(graph, pattern)
                if isinstance(pattern, URIRef)
                else (str(pattern) if pattern else "—")
            )
            lines.append(f"| {s} | {p} | {t} |")
        if len(edges) < len(data["relationships"]):
            lines += [
                "",
                "_Only the relationships touching this domain's contexts are listed; the "
                "strategic file holds the whole context map._",
            ]
    else:
        lines.append("_No context relationships touch this domain's contexts._")
    lines.append("")

    # Aggregates
    lines += ["## Aggregates & Tactical Patterns", ""]
    if data["tactical"] or data["members"]:
        roots: dict[URIRef, list[URIRef]] = {}
        for member, root in data["members"].items():
            roots.setdefault(root, []).append(member)
        lines += [
            "| Class | Tactical Pattern | Aggregate Root |",
            "|-------|------------------|----------------|",
        ]
        classes = sorted(set(data["tactical"]) | set(data["members"]) | set(roots), key=str)
        for cls in classes:
            pat = data["tactical"].get(cls)
            pat_label = extract_local_name(str(pat)) if pat is not None else "—"
            root = data["members"].get(cls)
            root_label = (
                _label(graph, root) if root is not None else ("(root)" if cls in roots else "—")
            )
            lines.append(f"| {_label(graph, cls)} | {pat_label} | {root_label} |")
    else:
        lines.append("_No tactical patterns declared._")
    lines.append("")

    # Invariants (DD-229)
    if data["invariants"]:
        lines += ["## Invariants", ""]
        lines.append(
            "_Prose rules the aggregate must always satisfy. Enforceable forms live in "
            "`model/shapes/` (SHACL) or in a binding's `DataQualityRule`._"
        )
        lines.append("")
        for cls in sorted(data["invariants"], key=str):
            for text in data["invariants"][cls]:
                lines.append(f"- **{_label(graph, cls)}:** {text}")
        lines.append("")

    # Design notes
    if data["notes"]:
        lines += ["## Design Notes", ""]
        for subj, note in data["notes"]:
            lines.append(f"- **{_label(graph, subj)}:** {note}")
        lines.append("")

    return "\n".join(lines)


def generate_ddd_artifacts(
    graph: Graph,
    namespace: str,
    ontology_name: str,
    overlay_path: Optional[Path] = None,
    ontology_metadata: Optional[dict] = None,
    strategic_path: Optional[Path] = None,
) -> dict:
    """Generate DDD documentation artifacts from the domain graph + strategic file + overlay.

    Returns ``{}`` when the domain has no overlay, or the overlay contains no DDD content
    (the feature is optional). The strategic file alone never produces per-domain output.
    """
    if overlay_path is None or not Path(overlay_path).exists():
        return {}
    overlay_graph = Graph()
    overlay_graph.parse(overlay_path, format="turtle")

    merged = _merge_overlay(graph, overlay_path, strategic_path)
    data = _collect(merged, overlay_graph)
    if not _has_content(data):
        return {}

    domain = ontology_name or "domain"
    meta = ontology_metadata or {}
    # No per-domain context map any more (DD-230): it rendered only the edges this
    # domain's overlay declared and so misled every other domain. The hub-wide map is
    # `contexts/context-map.mmd`, drawn once from every overlay and the strategic file.
    return {
        f"{domain}-aggregate-overview.mmd": _aggregate_overview_mmd(merged, data, domain),
        f"{domain}-ddd-report.md": _report_md(merged, data, domain, meta),
    }
