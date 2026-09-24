# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-wide bounded-context diagrams for the ``ddd`` target (DD-230, #846).

Every other diagram target selects by *file*: one domain TTL at a time. A bounded
context deliberately cuts across domain ontologies, so no per-domain diagram can draw
one -- the ``kairos-ddd:boundedContext`` annotation was collected and thrown away. This
projector reads every domain graph the run has already loaded, every ``*-ddd-ext.ttl``
overlay and the hub-wide strategic file together, indexes classes by context, and emits
under ``architecture/ddd/contexts/``:

- ``context-map.mmd``   -- every context and every relationship, whichever file declared it
- ``all-contexts.mmd``  -- one ``classDiagram``, one ``namespace`` per context: the
                           subject-area view a context engineer draws by hand
- ``{context}.mmd``     -- one diagram per non-empty context, neighbours drawn as stubs
- ``design-notes.md``   -- per context: subdomain, classes, Silver status, invariants,
                           language, design notes; then the classes no context claims

**Silver status is read from authored inputs, never the CompilePlan.** A class is
``contract`` when a ``model/contracts/<domain>.contract.yaml`` declares it, ``bound`` when
an EntityBinding targets it, ``unbound`` otherwise. Direction is Silver -> documentation:
the DD-091 firewall (DDD never drives emission) is untouched. Styling and the Silver column
make "Silver is a subset of the architecture" visible instead of merely true.

Four findings from the hub prototype this replaces, all designed in:

1. A Mermaid ``namespace`` whose id equals a class inside it fails the render outright, so
   namespace ids come from the context IRI local name and are suffixed on collision.
2. ``note for`` with two hundred characters of rationale drags a leader across the canvas;
   design notes and invariants go to ``design-notes.md``.
3. Membership is annotation-gated: a reference-model class appears only as a memberless
   stub on an annotated class's edge, so the import closure never floods a namespace.
4. Multiplicities come from the canonical ERD's own helpers -- qualified cardinality,
   ancestor-inherited restrictions, functional properties -- not a weaker reimplementation.

Output is deterministic (sorted, no timestamps) and never influences silver/gold/dbt/Power
BI generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from .erd_projector import (
    _attribute_type,
    _datatype_properties,
    _declared_classes,
    _effective_bounds,
    _external_label,
    _multiplicity,
    _node_ids,
)
from .shared import _toolkit_version, class_ancestors, effective_domain_classes, mermaid_header
from .uri_utils import extract_local_name

DDD = Namespace("https://kairos.cnext.eu/ddd#")

#: Subdirectory of the ``ddd`` target's output the hub-wide artifacts are written to.
CONTEXTS_SUBDIR = "contexts"
CONTEXT_MAP_NAME = "context-map.mmd"
ALL_CONTEXTS_NAME = "all-contexts.mmd"
DESIGN_NOTES_NAME = "design-notes.md"

#: Silver status of a class, as read from authored inputs.
STATUS_CONTRACT = "contract"
STATUS_BOUND = "bound"
STATUS_UNBOUND = "unbound"

#: Second stereotype on every context member. An annotation is plain text, so it renders
#: on every Mermaid surface; `classDef`/`cssClass` styling in a *classDiagram* fails the
#: parse on mermaid-cli 11.12 (the `stroke-width` token), so status is never styling here.
_STATUS_STEREOTYPE = {
    STATUS_CONTRACT: "silver: contract",
    STATUS_BOUND: "silver: bound",
    STATUS_UNBOUND: "architecture only",
}

_SUBDOMAIN_CSS = {
    DDD.CoreDomain: "coreDomain",
    DDD.SupportingSubdomain: "supportingSubdomain",
    DDD.GenericSubdomain: "genericSubdomain",
}

_LEGEND = (
    "%% Legend -- first stereotype: DDD tactical pattern. Second stereotype: Silver status,",
    "%% read from the authored contracts and bindings -- <<silver: contract>> is declared in",
    "%% a Silver contract, <<silver: bound>> has an EntityBinding and no contract,",
    "%% <<architecture only>> is not in Silver yet. A class outside every namespace is a",
    "%% stub drawn only because a context member reaches it.",
)


@dataclass(frozen=True)
class ContextDomain:
    """One loaded domain, as the projector run already holds it."""

    name: str
    graph: Graph
    file: Optional[Path] = None
    local_graph: Optional[Graph] = None
    load_result: Any = None
    overlay_path: Optional[Path] = None


@dataclass
class _Model:
    """Everything the renderers need, collected once."""

    graph: Graph
    contexts: list[URIRef]
    subdomain: dict[URIRef, URIRef]
    published: set[URIRef]
    notes: dict[URIRef, list[str]]
    relationships: list[tuple[URIRef, URIRef, URIRef, Optional[URIRef]]]
    tactical: dict[URIRef, URIRef]
    members: dict[URIRef, URIRef]
    context_of: dict[URIRef, URIRef]
    invariants: dict[URIRef, list[str]]
    scope_notes: dict[URIRef, list[str]]
    examples: dict[URIRef, list[str]]
    alt_labels: dict[URIRef, list[str]]
    hub_classes: set[URIRef]
    hub_properties: set[URIRef]
    class_domain: dict[URIRef, str]
    silver: dict[URIRef, str]
    unresolved: list[str] = field(default_factory=list)
    dispositions: dict[URIRef, str] = field(default_factory=dict)

    def by_context(self) -> dict[URIRef, list[URIRef]]:
        grouped: dict[URIRef, list[URIRef]] = {ctx: [] for ctx in self.contexts}
        for cls, ctx in self.context_of.items():
            grouped.setdefault(ctx, []).append(cls)
        return {ctx: sorted(classes, key=str) for ctx, classes in grouped.items()}


def _sanitize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", text)


def _label(graph: Graph, uri: URIRef) -> str:
    value = graph.value(uri, RDFS.label)
    return str(value) if value else extract_local_name(str(uri))


def _literals(graph: Graph, subject: URIRef, predicate: URIRef) -> list[str]:
    return sorted(str(value) for value in graph.objects(subject, predicate))


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _union_graph(domains: list[ContextDomain], strategic_path: Optional[Path]) -> Graph:
    union = Graph()
    for domain in domains:
        for triple in domain.graph:
            union.add(triple)
    if strategic_path and Path(strategic_path).exists():
        union.parse(strategic_path, format="turtle")
    for domain in domains:
        if domain.overlay_path and Path(domain.overlay_path).exists():
            union.parse(domain.overlay_path, format="turtle")
    from ..ddd import load_ddd_vocabulary

    for triple in load_ddd_vocabulary():
        union.add(triple)
    return union


def _hub_declared(
    domains: list[ContextDomain], union: Graph
) -> tuple[set[URIRef], set[URIRef], dict]:
    """Return ``(classes, object properties, class -> domain name)`` the hub itself declares.

    With the domain file's own graph available, "declared" is subject-side declaration in
    that file (#805), so a reference-model IRI re-declared for a label counts and a class
    merely referenced does not. Without it -- the in-memory entry point -- every typed class
    in the domain graph counts, which is right for a graph that is the domain file alone.
    """
    classes: set[URIRef] = set()
    properties: set[URIRef] = set()
    class_domain: dict[URIRef, str] = {}
    for domain in domains:
        if domain.local_graph is not None:
            declared = _declared_classes(domain.local_graph, union)
            props = {
                subject
                for subject in set(domain.local_graph.subjects(None, None))
                if isinstance(subject, URIRef) and (subject, RDF.type, OWL.ObjectProperty) in union
            }
        else:
            declared = {
                cls
                for cls in set(domain.graph.subjects(RDF.type, OWL.Class))
                if isinstance(cls, URIRef)
            }
            props = {
                prop
                for prop in set(domain.graph.subjects(RDF.type, OWL.ObjectProperty))
                if isinstance(prop, URIRef)
            }
        classes |= declared
        properties |= props
        for cls in sorted(declared, key=str):
            class_domain.setdefault(cls, domain.name)
    return classes, properties, class_domain


def _resolve_class_token(domain: Optional[ContextDomain], token: str) -> Optional[str]:
    """Resolve a contract or binding class token (QName or IRI) to a full IRI.

    A loaded graph's namespace manager does not carry the source ``@prefix`` bindings, so
    resolution goes through the same helper ``fit-report`` uses, over the domain's load
    result. Without a load result only an absolute IRI resolves.
    """
    token = (token or "").strip()
    if not token:
        return None
    if "://" in token or token.startswith("urn:"):
        return token
    if domain is None or domain.load_result is None or domain.file is None:
        return None
    from ..fit_report import resolve_token_uri

    return resolve_token_uri(domain.load_result, Path(domain.file), token)


def _silver_status(
    domains: list[ContextDomain],
    contracts_dir: Optional[Path],
    bindings_dir: Optional[Path],
) -> tuple[dict[URIRef, str], list[str]]:
    """Read the authored contracts and bindings; return ``{class: status}`` and unresolved tokens."""
    by_name = {domain.name: domain for domain in domains}
    status: dict[URIRef, str] = {}
    unresolved: list[str] = []

    if bindings_dir is not None and Path(bindings_dir).is_dir():
        for path in sorted(Path(bindings_dir).glob("*.yaml")):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - a malformed binding is the compiler's problem
                continue
            if not isinstance(payload, dict):
                continue
            target = payload.get("target") or {}
            metadata = payload.get("metadata") or {}
            token = str(target.get("class") or "") if isinstance(target, dict) else ""
            domain_name = str(metadata.get("domain") or "") if isinstance(metadata, dict) else ""
            if not token:
                continue
            iri = _resolve_class_token(by_name.get(domain_name), token)
            if iri is None:
                unresolved.append(f"{path.name}: {token}")
                continue
            status.setdefault(URIRef(iri), STATUS_BOUND)

    if contracts_dir is not None and Path(contracts_dir).is_dir():
        from ..compiler.contracts import load_silver_contract

        for path in sorted(Path(contracts_dir).glob("*.contract.yaml")):
            contract = load_silver_contract(path.read_text(encoding="utf-8"), path=str(path))
            domain = by_name.get(contract.domain) or by_name.get(
                path.name.removesuffix(".contract.yaml")
            )
            for entity in contract.entities:
                iri = _resolve_class_token(domain, entity.target_class)
                if iri is None:
                    unresolved.append(f"{path.name}: {entity.target_class}")
                    continue
                status[URIRef(iri)] = STATUS_CONTRACT
    return status, sorted(unresolved)


def _collect(
    domains: list[ContextDomain],
    strategic_path: Optional[Path],
    contracts_dir: Optional[Path],
    bindings_dir: Optional[Path],
    hub_root: Optional[Path] = None,
) -> _Model:
    union = _union_graph(domains, strategic_path)
    hub_classes, hub_properties, class_domain = _hub_declared(domains, union)

    contexts = sorted(set(union.subjects(RDF.type, DDD.BoundedContext)), key=str)
    subdomain = {ctx: kind for ctx, kind in union.subject_objects(DDD.subdomainType)}
    published = {
        subject
        for subject, value in union.subject_objects(DDD.publishedLanguage)
        if str(value).lower() in ("true", "1")
    }
    notes: dict[URIRef, list[str]] = {}
    for subject, note in union.subject_objects(DDD.designNote):
        notes.setdefault(subject, []).append(str(note))
    for texts in notes.values():
        texts.sort()

    relationships = []
    for rel in sorted(set(union.subjects(RDF.type, DDD.ContextRelationship)), key=str):
        src = union.value(rel, DDD.sourceContext)
        tgt = union.value(rel, DDD.targetContext)
        if isinstance(src, URIRef) and isinstance(tgt, URIRef):
            pattern = union.value(rel, DDD.relationshipPattern)
            relationships.append((rel, src, tgt, pattern if isinstance(pattern, URIRef) else None))

    tactical = {cls: pat for cls, pat in union.subject_objects(DDD.tacticalPattern)}
    members = {member: root for member, root in union.subject_objects(DDD.aggregateRoot)}

    # Membership: an explicit assignment, else the aggregate root's context (finding 5 of the
    # plan review: fixtures carry members with a root and no context, and they must not
    # vanish). Iterate because a root may itself be a member of a larger aggregate.
    context_of: dict[URIRef, URIRef] = {
        subject: ctx
        for subject, ctx in union.subject_objects(DDD.boundedContext)
        if isinstance(ctx, URIRef)
    }
    changed = True
    while changed:
        changed = False
        for member, root in members.items():
            if member not in context_of and root in context_of:
                context_of[member] = context_of[root]
                changed = True

    def texts(predicate: URIRef) -> dict[URIRef, list[str]]:
        out: dict[URIRef, list[str]] = {}
        for subject, value in union.subject_objects(predicate):
            out.setdefault(subject, []).append(str(value))
        return {subject: sorted(values) for subject, values in out.items()}

    silver, unresolved = _silver_status(domains, contracts_dir, bindings_dir)
    return _Model(
        graph=union,
        contexts=contexts,
        subdomain=subdomain,
        published=published,
        notes=notes,
        relationships=relationships,
        tactical=tactical,
        members=members,
        context_of=context_of,
        invariants=texts(DDD.invariant),
        scope_notes=texts(SKOS.scopeNote),
        examples=texts(SKOS.example),
        alt_labels=texts(SKOS.altLabel),
        hub_classes=hub_classes,
        hub_properties=hub_properties,
        class_domain=class_domain,
        silver=silver,
        unresolved=unresolved,
        dispositions=_dispositions(hub_root),
    )


def collect_context_model(
    domains: list[ContextDomain], strategic_path: Optional[Path] = None
) -> _Model:
    """The hub-wide DDD model, for the practice checks (DD-240). No Silver status."""
    return _collect(domains, strategic_path, None, None)


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------


def _context_ids(model: _Model, class_ids: dict[URIRef, str]) -> dict[URIRef, str]:
    """One namespace id per context, from the IRI local name, never the label.

    Labels collide with class names routinely (the Party context holds the Party class),
    are language-tagged, and two contexts can share one -- which would silently overwrite
    a tracked file. A local name that still equals a member class id is suffixed: Mermaid
    treats a namespace as the parent of its classes and rejects a class as its own parent.
    """
    taken = set(class_ids.values())
    ids: dict[URIRef, str] = {}
    for ctx in model.contexts:
        candidate = _sanitize(extract_local_name(str(ctx))) or "context"
        while candidate in taken or candidate in ids.values():
            candidate = f"{candidate}_context"
        ids[ctx] = candidate
    return ids


def _silver_label(status: str, disposition: Optional[str] = None) -> str:
    """The Silver column: what Silver knows, and -- when recorded -- why it is not there.

    An unbound class with a DD-231 disposition reads ``not in Silver (architecture-only)``:
    the architecture view then says *why* a box is empty, not only that it is.
    """
    label = {
        STATUS_CONTRACT: "in Silver contract",
        STATUS_BOUND: "bound (no contract)",
        STATUS_UNBOUND: "not in Silver",
    }[status]
    if status == STATUS_UNBOUND and disposition:
        return f"{label} ({disposition})"
    return label


def _dispositions(hub_root: Optional[Path]) -> dict[URIRef, str]:
    """Recorded DD-231 dispositions, or ``{}`` without a hub root or a readable ledger.

    A ledger that cannot be parsed is `validate`'s error to report; the diagram simply
    shows no dispositions rather than failing the whole projection over it.
    """
    if hub_root is None:
        return {}
    from ..class_disposition import ClassDispositionError, load_ledger

    try:
        _present, entries = load_ledger(Path(hub_root))
    except ClassDispositionError:
        return {}
    return {
        URIRef(iri): str(entry.get("disposition") or "")
        for iri, entry in entries.items()
        if str(entry.get("disposition") or "")
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _context_map_mmd(model: _Model, hub_name: str) -> str:
    lines = [
        *mermaid_header(indent=""),
        f"%% DDD context map for {hub_name}: every bounded context and every relationship,",
        "%% whichever overlay or strategic file declared it (DD-230).",
        "%% Border: thick = core domain, normal = supporting subdomain, dashed = generic subdomain.",
        "graph LR",
    ]
    node_ids: dict[URIRef, str] = {}
    for ctx in model.contexts:
        candidate = "ctx_" + (_sanitize(extract_local_name(str(ctx))) or "context")
        while candidate in node_ids.values():
            candidate += "_"
        node_ids[ctx] = candidate
    for ctx in model.contexts:
        kind = model.subdomain.get(ctx)
        detail = f"<br/><i>{_label(model.graph, kind).lower()}</i>" if kind is not None else ""
        lines.append(f'    {node_ids[ctx]}["{_label(model.graph, ctx)}{detail}"]')
    for _rel, src, tgt, pattern in model.relationships:
        if src not in node_ids or tgt not in node_ids:
            continue
        label = _label(model.graph, pattern) if pattern is not None else ""
        arrow = f"-->|{label}|" if label else "-->"
        lines.append(f"    {node_ids[src]} {arrow} {node_ids[tgt]}")
    lines += [
        "    classDef coreDomain stroke-width:3px",
        "    classDef supportingSubdomain stroke-width:1.5px",
        "    classDef genericSubdomain stroke-dasharray:4,2",
    ]
    for ctx in model.contexts:
        css = _SUBDOMAIN_CSS.get(model.subdomain.get(ctx))
        if css:
            lines.append(f"    class {node_ids[ctx]} {css}")
    return "\n".join(lines) + "\n"


def _class_block(model: _Model, cls: URIRef, node_id: str, *, indent: str) -> list[str]:
    lines = [f"{indent}class {node_id} {{"]
    pattern = model.tactical.get(cls)
    if pattern is not None:
        lines.append(f"{indent}    <<{extract_local_name(str(pattern))}>>")
    status = model.silver.get(cls, STATUS_UNBOUND)
    lines.append(f"{indent}    <<{_STATUS_STEREOTYPE[status]}>>")
    for prop in _datatype_properties(model.graph, cls):
        lines.append(
            f"{indent}    {_attribute_type(model.graph, prop)} "
            f"{_sanitize(extract_local_name(str(prop)))}"
        )
    lines.append(f"{indent}}}")
    return lines


def _stub_block(
    model: _Model, cls: URIRef, node_id: str, context_ids: dict[URIRef, str]
) -> list[str]:
    ctx = model.context_of.get(cls)
    if ctx is not None:
        stereotype = f"context: {_label(model.graph, ctx)}"
    elif cls in model.hub_classes:
        stereotype = "unassigned"
    else:
        stereotype = _external_label(cls)
    return [f"    class {node_id} {{", f"        <<{stereotype}>>", "    }"]


def _edges_for(model: _Model, drawn: set[URIRef]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Return ``(aggregate, inheritance, association)`` edges among *drawn* classes.

    Associations come from the object properties the hub itself declares, applied to a
    drawn class directly or through an ancestor (labelled ``(inherited)``). Reference-model
    properties are left out on purpose: at architecture altitude a context diagram shows
    what the hub designed, and ``project --target erd`` shows the full inherited surface.
    """
    aggregate = [
        (root, member)
        for member, root in sorted(model.members.items(), key=lambda item: str(item[0]))
        if member in drawn and root in drawn
    ]
    inheritance: list[tuple[URIRef, URIRef]] = []
    for cls in sorted(drawn, key=str):
        for parent in model.graph.objects(cls, RDFS.subClassOf):
            if isinstance(parent, URIRef) and parent in drawn:
                inheritance.append((parent, cls))
    association: list[tuple] = []
    for prop in sorted(model.hub_properties, key=str):
        range_cls = model.graph.value(prop, RDFS.range)
        if not isinstance(range_cls, URIRef) or range_cls not in drawn:
            continue
        domains = effective_domain_classes(model.graph, prop)
        for cls in sorted(drawn, key=str):
            declared_on: Optional[URIRef] = None
            inherited = False
            if cls in domains:
                declared_on = cls
            else:
                for ancestor in class_ancestors(model.graph, cls):
                    if ancestor in domains:
                        declared_on, inherited = ancestor, True
                        break
            if declared_on is None:
                continue
            min_bound, max_bound = _effective_bounds(model.graph, cls, declared_on, prop)
            if max_bound is None and (prop, RDF.type, OWL.FunctionalProperty) in model.graph:
                max_bound = 1
            association.append(
                (cls, range_cls, prop, _multiplicity(min_bound, max_bound), inherited)
            )
    return aggregate, inheritance, association


def _reachable_outside(model: _Model, inside: set[URIRef]) -> set[URIRef]:
    """Classes outside *inside* that a member reaches: parent, aggregate partner, or range."""
    outside: set[URIRef] = set()
    for cls in inside:
        for parent in model.graph.objects(cls, RDFS.subClassOf):
            if isinstance(parent, URIRef) and parent not in inside:
                outside.add(parent)
    for member, root in model.members.items():
        if member in inside and root not in inside:
            outside.add(root)
        if root in inside and member not in inside:
            outside.add(member)
    for prop in model.hub_properties:
        range_cls = model.graph.value(prop, RDFS.range)
        if not isinstance(range_cls, URIRef):
            continue
        domains = effective_domain_classes(model.graph, prop)
        for cls in inside:
            applies = cls in domains or any(a in domains for a in class_ancestors(model.graph, cls))
            if applies and range_cls not in inside:
                outside.add(range_cls)
            if range_cls == cls:
                for domain_cls in domains:
                    if domain_cls not in inside and domain_cls in model.hub_classes:
                        outside.add(domain_cls)
    return outside


def _class_diagram(model: _Model, contexts: list[URIRef], hub_name: str, title: str) -> str:
    grouped = model.by_context()
    inside: set[URIRef] = set()
    for ctx in contexts:
        inside.update(grouped.get(ctx, []))
    outside = _reachable_outside(model, inside)
    drawn = inside | outside
    class_ids = _node_ids(drawn)
    context_ids = _context_ids(model, class_ids)

    lines = [
        *mermaid_header(indent=""),
        f"%% {title} ({hub_name}, DD-230)",
        *_LEGEND,
        "classDiagram",
    ]
    for ctx in contexts:
        classes = grouped.get(ctx, [])
        if not classes:
            continue
        lines.append(f"namespace {context_ids[ctx]} {{")
        for cls in classes:
            lines.extend(_class_block(model, cls, class_ids[cls], indent="    "))
        lines.append("}")
    for cls in sorted(outside, key=str):
        lines.extend(_stub_block(model, cls, class_ids[cls], context_ids))

    aggregate, inheritance, association = _edges_for(model, drawn)
    for root, member in aggregate:
        lines.append(f"    {class_ids[root]} *-- {class_ids[member]} : aggregate")
    for parent, child in inheritance:
        lines.append(f"    {class_ids[parent]} <|-- {class_ids[child]}")
    for cls, range_cls, prop, mult, inherited in association:
        label = _sanitize(extract_local_name(str(prop)))
        if inherited:
            label += " (inherited)"
        lines.append(f'    {class_ids[cls]} --> "{mult}" {class_ids[range_cls]} : {label}')
    return "\n".join(lines) + "\n"


def _design_notes_md(model: _Model, hub_name: str) -> str:
    graph = model.graph
    grouped = model.by_context()
    lines = [
        f"# Bounded contexts — design notes ({hub_name})",
        "",
        "> Generated by `kairos-ontology project --target ddd` (DD-230). Documentation only —",
        "> not a governance or projection-control source. Silver status is read from the",
        "> authored contracts and bindings, never from a CompilePlan.",
        "",
        f"**Toolkit version:** {_toolkit_version()}",
        "",
        "Silver status: **in Silver contract** = declared in `model/contracts/<domain>.contract.yaml`;",
        "**bound (no contract)** = an EntityBinding targets the class; **not in Silver** = the",
        "class is architecture only until a binding is authored.",
        "",
    ]
    for ctx in model.contexts:
        kind = model.subdomain.get(ctx)
        heading = f"## {_label(graph, ctx)}"
        if kind is not None:
            heading += f" — {_label(graph, kind)}"
        if ctx in model.published:
            heading += " (published language)"
        lines += [heading, ""]
        for note in model.notes.get(ctx, []):
            lines += [f"_{note}_", ""]
        classes = grouped.get(ctx, [])
        if not classes:
            lines += ["_No classes assigned._", ""]
            continue
        lines += [
            "| Class | Domain | Pattern | Aggregate root | Silver |",
            "|-------|--------|---------|----------------|--------|",
        ]
        for cls in classes:
            pattern = model.tactical.get(cls)
            root = model.members.get(cls)
            lines.append(
                f"| {_label(graph, cls)} | {model.class_domain.get(cls, '—')} | "
                f"{extract_local_name(str(pattern)) if pattern is not None else '—'} | "
                f"{_label(graph, root) if root is not None else '—'} | "
                f"{_silver_label(model.silver.get(cls, STATUS_UNBOUND), model.dispositions.get(cls))} |"
            )
        lines.append("")
        invariants = [(cls, text) for cls in classes for text in model.invariants.get(cls, [])]
        if invariants:
            lines += ["### Invariants", ""]
            lines += [f"- **{_label(graph, cls)}:** {text}" for cls, text in invariants]
            lines.append("")
        language = [
            cls
            for cls in classes
            if model.scope_notes.get(cls) or model.examples.get(cls) or model.alt_labels.get(cls)
        ]
        if language:
            lines += ["### Language", ""]
            for cls in language:
                parts = []
                if model.scope_notes.get(cls):
                    parts.append("scope: " + " ".join(model.scope_notes[cls]))
                if model.alt_labels.get(cls):
                    parts.append("also called: " + ", ".join(model.alt_labels[cls]))
                if model.examples.get(cls):
                    parts.append("examples: " + "; ".join(model.examples[cls]))
                lines.append(f"- **{_label(graph, cls)}** — " + " · ".join(parts))
            lines.append("")
        class_notes = [(cls, note) for cls in classes for note in model.notes.get(cls, [])]
        if class_notes:
            lines += ["### Design notes", ""]
            lines += [f"- **{_label(graph, cls)}:** {note}" for cls, note in class_notes]
            lines.append("")

    unassigned = sorted((cls for cls in model.hub_classes if cls not in model.context_of), key=str)
    lines += ["## Classes outside any bounded context", ""]
    if unassigned:
        lines += [
            "_The gap between the overlay and the hub: every hub class no context claims._",
            "",
            "| Class | Domain | Silver |",
            "|-------|--------|--------|",
        ]
        lines += [
            f"| {_label(graph, cls)} | {model.class_domain.get(cls, '—')} | "
            f"{_silver_label(model.silver.get(cls, STATUS_UNBOUND), model.dispositions.get(cls))} |"
            for cls in unassigned
        ]
    else:
        lines.append("_Every hub class is assigned to a bounded context._")
    lines.append("")
    lines += _practice_sections(model)
    if model.unresolved:
        lines += [
            "## Unresolved class references",
            "",
            "_These contract or binding class tokens did not resolve to an IRI, so their Silver",
            "status is not shown. Check the prefix in the file named._",
            "",
        ]
        lines += [f"- `{item}`" for item in model.unresolved]
        lines.append("")
    return "\n".join(lines)


def _practice_sections(model: _Model) -> list[str]:
    """DD-240 findings and recorded exceptions; nothing when there are neither.

    Absent rather than empty, so a hub whose design breaks no practice keeps its bytes.
    An exception that does not parse is `validate --ddd`'s to report, not the diagram's.
    """
    from ..ddd_practices import authored_exceptions, check_ddd_practices

    exceptions, _errors = authored_exceptions(model.graph)
    findings, excused, _unused = check_ddd_practices(model, exceptions)
    lines: list[str] = []
    if findings:
        lines += [
            "## Practice findings",
            "",
            "_DDD practices this design does not follow (docs/toolkit/practices/ddd.md). "
            "Reported by `validate --ddd` as warnings; documentation only._",
            "",
        ]
        lines += [f"- `{item.code}`: {item.message}" for item in findings]
        lines.append("")
    used = [
        item
        for item in exceptions
        if any(item.matches(finding.code, finding.kind, finding.target) for finding in excused)
    ]
    if used:
        lines += ["## Recorded exceptions", ""]
        lines += [
            f"- `{item.rule_id}` on {item.kind} `{item.target}`: {item.reason}" for item in used
        ]
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_context_artifacts(
    domains: list[ContextDomain],
    *,
    strategic_path: Optional[Path] = None,
    contracts_dir: Optional[Path] = None,
    bindings_dir: Optional[Path] = None,
    hub_name: str = "hub",
    hub_root: Optional[Path] = None,
) -> dict[str, str]:
    """Return ``{"contexts/<file>": content}`` for the whole hub, or ``{}`` without DDD input.

    Keys are relative to the ``ddd`` target's output directory. Nothing is produced when no
    overlay and no strategic file exist: the feature is opt-in and a hub without it must not
    start growing a ``contexts/`` directory.
    """
    has_input = (strategic_path is not None and Path(strategic_path).exists()) or any(
        domain.overlay_path is not None and Path(domain.overlay_path).exists() for domain in domains
    )
    if not has_input:
        return {}
    model = _collect(domains, strategic_path, contracts_dir, bindings_dir, hub_root)
    if not model.contexts and not model.context_of:
        return {}

    artifacts = {
        f"{CONTEXTS_SUBDIR}/{CONTEXT_MAP_NAME}": _context_map_mmd(model, hub_name),
        f"{CONTEXTS_SUBDIR}/{ALL_CONTEXTS_NAME}": _class_diagram(
            model, model.contexts, hub_name, "All bounded contexts"
        ),
        f"{CONTEXTS_SUBDIR}/{DESIGN_NOTES_NAME}": _design_notes_md(model, hub_name),
    }
    grouped = model.by_context()
    used: set[str] = set()
    for ctx in model.contexts:
        if not grouped.get(ctx):
            continue
        file_id = _sanitize(extract_local_name(str(ctx))) or "context"
        while file_id in used:
            file_id += "_"
        used.add(file_id)
        artifacts[f"{CONTEXTS_SUBDIR}/{file_id}.mmd"] = _class_diagram(
            model, [ctx], hub_name, f"Bounded context: {_label(model.graph, ctx)}"
        )
    return artifacts
