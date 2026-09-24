# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DDD architecture practices over the whole overlay (DD-240, issue #996).

The consistency audit in ``ddd`` compares files. These judge the design they describe,
and need the domain ontologies as well as the overlays -- a relationship crosses a context
boundary only if its domain and range are known -- so they run over the same hub-wide
model the context diagrams are drawn from (``ddd_context_projector``).

Documentation only (DD-091): every finding is a warning in ``validate --ddd`` and a line
in the context design notes, and nothing here is read by Silver, Gold or dbt generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdflib import URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ..practices.exceptions import DddException, PracticeExceptionError, parse_ddd_exception
from .projections.shared import effective_domain_classes
from .projections.uri_utils import extract_local_name

DDD_NS = "https://kairos.cnext.eu/ddd#"

ONE_ROOT = "ddd.one-root-per-aggregate"
CROSS_CONTEXT = "ddd.cross-context-relationship-on-map"
BY_IDENTITY = "ddd.aggregate-reference-by-identity"


@dataclass(frozen=True)
class DddFinding:
    code: str
    kind: str
    #: The IRI of the class or property the finding is about.
    target: str
    message: str


def _name(iri) -> str:
    return extract_local_name(str(iri))


def authored_exceptions(graph) -> tuple[list[DddException], list[PracticeExceptionError]]:
    """Every ``kairos-ddd:practiceException`` in *graph*, parsed; and the ones that fail."""
    parsed: list[DddException] = []
    errors: list[PracticeExceptionError] = []
    for value in sorted(
        {str(item) for item in graph.objects(None, URIRef(DDD_NS + "practiceException"))}
    ):
        try:
            parsed.append(parse_ddd_exception(value))
        except PracticeExceptionError as exc:
            errors.append(exc)
    return parsed, errors


def _one_root(model) -> list[DddFinding]:
    graph = model.graph
    root_pred = URIRef(DDD_NS + "aggregateRoot")
    pattern_pred = URIRef(DDD_NS + "tacticalPattern")
    findings: list[DddFinding] = []
    members = sorted({member for member in graph.subjects(root_pred, None)}, key=str)
    for member in members:
        roots = sorted({root for root in graph.objects(member, root_pred)}, key=str)
        if len(roots) > 1:
            findings.append(
                DddFinding(
                    ONE_ROOT,
                    "class",
                    str(member),
                    (
                        f"{_name(member)} names {len(roots)} aggregate roots "
                        f"({', '.join(_name(root) for root in roots)}); a member belongs to "
                        "exactly one aggregate"
                    ),
                )
            )
    for root in sorted({root for root in graph.objects(None, root_pred)}, key=str):
        patterns = set(graph.objects(root, pattern_pred))
        nested = (root, root_pred, None) in graph
        if URIRef(DDD_NS + "AggregateRoot") not in patterns and not nested:
            findings.append(
                DddFinding(
                    ONE_ROOT,
                    "class",
                    str(root),
                    (
                        f"{_name(root)} is the aggregate root of "
                        + ", ".join(
                            sorted(_name(member) for member in graph.subjects(root_pred, root))
                        )
                        + " but is not tagged kairos-ddd:tacticalPattern "
                        "kairos-ddd:AggregateRoot"
                    ),
                )
            )
    return findings


def _object_properties(model) -> list[tuple[URIRef, list[URIRef], URIRef]]:
    graph = model.graph
    edges = []
    for prop in sorted(set(graph.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        if not isinstance(prop, URIRef):
            continue
        range_cls = graph.value(prop, RDFS.range)
        if not isinstance(range_cls, URIRef):
            continue
        domains = sorted(
            (item for item in effective_domain_classes(graph, prop) if isinstance(item, URIRef)),
            key=str,
        )
        if domains:
            edges.append((prop, domains, range_cls))
    return edges


def _cross_context(model) -> list[DddFinding]:
    mapped = {(src, tgt) for _rel, src, tgt, _pattern in model.relationships}
    findings: list[DddFinding] = []
    for prop, domains, range_cls in _object_properties(model):
        target_ctx = model.context_of.get(range_cls)
        if target_ctx is None:
            continue
        pairs = sorted(
            {
                (model.context_of[cls], cls)
                for cls in domains
                if model.context_of.get(cls) not in (None, target_ctx)
            },
            key=str,
        )
        for source_ctx, cls in pairs:
            if (source_ctx, target_ctx) in mapped or (target_ctx, source_ctx) in mapped:
                continue
            findings.append(
                DddFinding(
                    CROSS_CONTEXT,
                    "property",
                    str(prop),
                    (
                        f"{_name(prop)} links {_name(cls)} ({_name(source_ctx)}) to "
                        f"{_name(range_cls)} ({_name(target_ctx)}), but the context map "
                        f"has no relationship between {_name(source_ctx)} and "
                        f"{_name(target_ctx)}; add a kairos-ddd:ContextRelationship to "
                        "ddd-contexts-ext.ttl and choose its pattern"
                    ),
                )
            )
    return findings


def _by_identity(model) -> list[DddFinding]:
    members = model.members  # member -> root

    def roots(cls) -> list:
        chain, seen = [], set()
        while cls in members and cls not in seen:
            seen.add(cls)
            cls = members[cls]
            chain.append(cls)
        return chain

    is_root = set(members.values())
    findings: list[DddFinding] = []
    for prop, domains, range_cls in _object_properties(model):
        if range_cls not in members or range_cls in is_root:
            continue
        aggregate = set(roots(range_cls))
        outside = sorted(
            (cls for cls in domains if cls != range_cls and not ({cls, *roots(cls)} & aggregate)),
            key=str,
        )
        for cls in outside:
            root = members[range_cls]
            findings.append(
                DddFinding(
                    BY_IDENTITY,
                    "property",
                    str(prop),
                    (
                        f"{_name(prop)} points {_name(cls)} at {_name(range_cls)}, a member "
                        f"inside the {_name(root)} aggregate; reference the root "
                        f"{_name(root)} instead, so its invariants stay guarded"
                    ),
                )
            )
    return findings


def check_ddd_practices(
    model, exceptions: list[DddException]
) -> tuple[list[DddFinding], list[DddFinding], list[DddException]]:
    """Return ``(findings, excused findings, exceptions that excuse nothing)``."""
    findings = [*_one_root(model), *_cross_context(model), *_by_identity(model)]
    open_findings: list[DddFinding] = []
    excused: list[DddFinding] = []
    used: set[int] = set()
    for finding in findings:
        match = next(
            (
                index
                for index, item in enumerate(exceptions)
                if item.matches(finding.code, finding.kind, finding.target)
            ),
            None,
        )
        if match is None:
            open_findings.append(finding)
        else:
            used.add(match)
            excused.append(finding)
    unused = [item for index, item in enumerate(exceptions) if index not in used]
    return open_findings, excused, unused
