# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The concept guide: the hub's business concepts and how they relate, generated (DD-232).

The human-readable counterpart of the ubiquitous-language vocabulary, in the shape a context
engineer would otherwise write by hand for the SMEs and the data engineer: every concept has
three names -- what the source calls it, what the canonical model calls it, what the industry
model calls it -- and the guide lists them side by side, then describes each concept in its
bounded context (definition, scope, synonyms, examples, invariants, Silver status, sources,
relationships), then gives the relationship reference and the concept-mapping table.

Everything here is derived: labels and comments from the ontology, language and invariants
from the DDD overlay, synonyms from the discovery glossary, sources and realised
relationships from the bindings, Silver status from contracts and bindings. What a
generator cannot write -- the narrative, the workshop quotes, "flow versus containment" --
stays human-authored in a context's ``designNote`` or a companion page.

**Sample values are opt-in and off by default.** Source ``kairos-bronze:sampleValues`` are
pipe-separated strings that can carry e-mail addresses even in fixtures, and this guide
lives in a tracked lane. ``kairos.yaml`` ``projections.concept_guide.samples: true`` turns
them on, capped at ``max_samples`` (default 3) per property.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from .ddd_context_projector import STATUS_UNBOUND, _label, _silver_label
from .shared import _toolkit_version, class_ancestors, effective_domain_classes
from .ubiquitous_language_projector import LanguageModel
from .uri_utils import extract_local_name

CONCEPT_GUIDE_NAME = "concept-guide.md"

BRONZE = Namespace("https://kairos.cnext.eu/bronze#")


def _external_label(iri: URIRef) -> str:
    text = str(iri).split("://", 1)[-1].split("#", 1)[0].rstrip("/")
    segments = [s for s in text.split("/") if s][1:]
    return "/".join(segments[-2:]) if segments else text


def _industry_name(model: LanguageModel, parent: URIRef) -> str:
    return f"`{_external_label(parent)}:{extract_local_name(str(parent))}`"


def _relationships(model: LanguageModel) -> list[tuple[URIRef, URIRef, URIRef, bool]]:
    """``(class, property, range, inherited)`` for every hub object property between hub classes."""
    graph = model.graph
    edges: list[tuple[URIRef, URIRef, URIRef, bool]] = []
    hub = model.base.hub_classes
    for prop in sorted(model.base.hub_properties, key=str):
        range_cls = graph.value(prop, RDFS.range)
        if not isinstance(range_cls, URIRef):
            continue
        domains = effective_domain_classes(graph, prop)
        for cls in sorted(hub, key=str):
            if cls in domains:
                edges.append((cls, prop, range_cls, False))
            elif any(a in domains for a in class_ancestors(graph, cls)):
                edges.append((cls, prop, range_cls, True))
    return edges


def load_samples(sources_dir: Optional[Path]) -> dict[tuple[str, str, str], list[str]]:
    """``{(system, table, column): [value, ...]}`` from the imported source vocabularies.

    Reads ``kairos-bronze:sampleValues`` -- the import step's already-redacted samples -- and
    nothing else. Called only when the hub opted in.
    """
    samples: dict[tuple[str, str, str], list[str]] = {}
    if sources_dir is None or not Path(sources_dir).is_dir():
        return samples
    for system_dir in sorted(Path(sources_dir).iterdir()):
        if not system_dir.is_dir() or system_dir.name.startswith(("_", ".")):
            continue
        for path in sorted(system_dir.glob("*.ttl")):
            graph = Graph()
            try:
                graph.parse(path, format="turtle")
            except Exception:  # noqa: BLE001 - source syntax is validate's to report
                continue
            for column in graph.subjects(RDF.type, BRONZE.SourceColumn):
                name = graph.value(column, BRONZE.columnName)
                table = graph.value(column, BRONZE.sourceTable)
                values = graph.value(column, BRONZE.sampleValues)
                if name is None or table is None or values is None:
                    continue
                table_name = graph.value(table, BRONZE.tableName)
                if table_name is None:
                    continue
                key = (system_dir.name, str(table_name), str(name))
                samples[key] = [v.strip() for v in str(values).split(" | ") if v.strip()]
    return samples


def render_concept_guide(
    model: LanguageModel,
    *,
    samples_per_property: int = 0,
    sources_dir: Optional[Path] = None,
) -> str:
    graph = model.graph
    base = model.base
    samples = load_samples(sources_dir) if samples_per_property > 0 else {}
    edges = _relationships(model)
    edges_by_class: dict[URIRef, list[tuple[URIRef, URIRef, bool]]] = {}
    for cls, prop, range_cls, inherited in edges:
        edges_by_class.setdefault(cls, []).append((prop, range_cls, inherited))

    def name(cls: URIRef) -> str:
        return _label(graph, cls)

    def canonical(cls: URIRef) -> str:
        return f"`{base.class_domain.get(cls, 'hub')}:{extract_local_name(str(cls))}`"

    lines = [
        f"# Concept guide — {model.hub_name}",
        "",
        "> Generated by `kairos-ontology project --target ddd` (DD-232). Everything below is",
        "> derived from the ontology, the DDD overlay, the discovery glossary and the",
        "> bindings; regenerate it, never edit it. The narrative — why the model is shaped this",
        "> way, the workshop's own words — belongs in a context's design note or a companion page.",
        "",
        f"**Toolkit version:** {_toolkit_version()} · "
        f"**Sample values:** {'included' if samples_per_property else 'off (opt in with `projections.concept_guide.samples: true`)'}",
        "",
        "## Three names, one concept",
        "",
        "Every concept has up to three names, deliberately different: what the **source** system",
        "calls it (changes per system), what the **canonical** model calls it (one per concept),",
        "and what the **industry** reference model it specialises calls it. Source names are",
        "handled by bindings and never leak into the canonical vocabulary.",
        "",
    ]

    groups = model.groups()
    lines += [
        "## Concepts by bounded context" if base.contexts else "## Concepts by domain",
        "",
    ]
    for _group_id, label, classes in groups:
        lines += [f"### {label}", ""]
        ctx = next((c for c in base.contexts if _label(graph, c) == label), None)
        if ctx is not None:
            kind = base.subdomain.get(ctx)
            meta = []
            if kind is not None:
                meta.append(_label(graph, kind))
            if ctx in base.published:
                meta.append("published language")
            if meta:
                lines += [f"_{' · '.join(meta)}_", ""]
            for note in base.notes.get(ctx, []):
                lines += [note, ""]
        if not classes:
            lines += ["_No concepts assigned._", ""]
            continue
        for cls in classes:
            lines += _concept_section(
                model, cls, edges_by_class, samples, samples_per_property, name, canonical
            )

    unassigned = model.unassigned()
    if unassigned:
        lines += ["### Outside every bounded context", ""]
        lines += ["_Concepts the hub declares that no context claims yet._", ""]
        for cls in unassigned:
            lines += _concept_section(
                model, cls, edges_by_class, samples, samples_per_property, name, canonical
            )

    lines += ["## Relationship reference", ""]
    if edges:
        lines += [
            'Read `A --property--> B` as "A refers to B"; the many side is A. *(realised)* marks',
            "a relationship an EntityBinding realises today.",
            "",
            "```",
        ]
        width = max(len(extract_local_name(str(cls))) for cls, _, _, _ in edges)
        for cls, prop, range_cls, inherited in edges:
            marker = " (realised)" if (cls, prop) in model.bound_relationships else ""
            suffix = " (inherited)" if inherited else ""
            lines.append(
                f"{extract_local_name(str(cls)):<{width}} --{extract_local_name(str(prop))}--> "
                f"{extract_local_name(str(range_cls))}{suffix}{marker}"
            )
        lines += ["```", ""]
    else:
        lines += ["_No object properties between hub classes._", ""]

    lines += [
        "## Concept mapping table",
        "",
        "| Concept | Source | Canonical class | Industry model | Silver |",
        "|---------|--------|-----------------|----------------|--------|",
    ]
    for cls in model.classes():
        sources = ", ".join(f"`{s}`" for s in model.sources.get(cls, [])) or "—"
        industry = (
            ", ".join(_industry_name(model, p) for p in model.industry.get(cls, [])) or "hub-local"
        )
        silver = _silver_label(base.silver.get(cls, STATUS_UNBOUND), base.dispositions.get(cls))
        lines.append(f"| {name(cls)} | {sources} | {canonical(cls)} | {industry} | {silver} |")
    lines.append("")

    if model.stale_glossary:
        lines += [
            "## Stale discovery terms",
            "",
            "_Glossary concepts whose link points at an IRI the ontology no longer declares. The",
            "discovery glossary is inspiration and is not reconciled during modelling (DD-071); this",
            "list is where that drift becomes visible._",
            "",
        ]
        lines += [f"- `{concept}` → `{linked}`" for concept, linked in model.stale_glossary]
        lines.append("")
    if base.unresolved:
        lines += ["## Unresolved class references", ""]
        lines += [f"- `{item}`" for item in base.unresolved]
        lines.append("")
    return "\n".join(lines)


def _concept_section(
    model: LanguageModel,
    cls: URIRef,
    edges_by_class: dict,
    samples: dict,
    samples_per_property: int,
    name,
    canonical,
) -> list[str]:
    graph = model.graph
    base = model.base
    lines = [f"#### {name(cls)}", ""]
    comment = graph.value(cls, RDFS.comment)
    lines.append(f"- **Canonical:** {canonical(cls)}" + (f" — {comment}" if comment else ""))
    for definition in model.glossary_definitions.get(cls, []):
        lines.append(f"- **The business says:** {definition}")
    for note in base.scope_notes.get(cls, []):
        lines.append(f"- **In this context:** {note}")
    alt = sorted(set(base.alt_labels.get(cls, [])) | set(model.glossary_alt.get(cls, [])))
    if alt:
        lines.append(f"- **Also called:** {', '.join(alt)}")
    if base.examples.get(cls):
        lines.append(f"- **Examples:** {'; '.join(base.examples[cls])}")
    industry = model.industry.get(cls, [])
    if industry:
        lines.append(
            f"- **Industry model:** {', '.join(_industry_name(model, p) for p in industry)}"
        )
    pattern = base.tactical.get(cls)
    root = base.members.get(cls)
    if pattern is not None or root is not None:
        detail = extract_local_name(str(pattern)) if pattern is not None else "—"
        if root is not None:
            detail += f", in the {name(root)} aggregate"
        lines.append(f"- **Design:** {detail}")
    for text in base.invariants.get(cls, []):
        lines.append(f"- **Invariant:** {text}")
    sources = model.sources.get(cls, [])
    lines.append(
        f"- **Sources:** {', '.join(f'`{s}`' for s in sources) if sources else 'none yet'}"
    )
    lines.append(
        f"- **Silver:** {_silver_label(base.silver.get(cls, STATUS_UNBOUND), base.dispositions.get(cls))}"
    )
    for prop, range_cls, inherited in edges_by_class.get(cls, []):
        marker = " *(realised)*" if (cls, prop) in model.bound_relationships else ""
        suffix = " *(inherited)*" if inherited else ""
        lines.append(
            f"- **Refers to:** {name(range_cls)} via `{extract_local_name(str(prop))}`{suffix}{marker}"
        )
    if samples_per_property and model.columns.get(cls):
        for prop in sorted(model.columns[cls], key=str):
            values: list[str] = []
            for system, table, column in model.columns[cls][prop]:
                for value in samples.get((system, table, column), []):
                    if value not in values:
                        values.append(value)
                    if len(values) >= samples_per_property:
                        break
                if len(values) >= samples_per_property:
                    break
            if values:
                lines.append(
                    f"- **Sample `{extract_local_name(str(prop))}`:** "
                    + ", ".join(f"`{v}`" for v in values)
                )
    lines.append("")
    return lines


def generate_concept_guide(
    model: LanguageModel,
    *,
    samples_per_property: int = 0,
    sources_dir: Optional[Path] = None,
) -> dict[str, str]:
    """``{"concept-guide.md": content}``; empty only when the hub declares no class."""
    if not model.base.hub_classes:
        return {}
    return {
        CONCEPT_GUIDE_NAME: render_concept_guide(
            model, samples_per_property=samples_per_property, sources_dir=sources_dir
        )
    }
