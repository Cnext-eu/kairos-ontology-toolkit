# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Structural validation for ``*-mdm-ext.ttl`` MDM extension files.

This is a *design-time* gate (mdmhubdesignv2.md §5.1: "The extension is reviewed by
data governance").  It checks that the MDM policy declared against ontology IRIs is
internally consistent before the ``mdm-profile`` projection is trusted:

* enumerated values (``mdmStyle``, ``survivorship``, comparator, match action, DQ
  dimension, DQ severity) are drawn from the controlled vocabularies;
* thresholds / scorecard thresholds / auto-action bounds are decimals in ``0..1``;
* every deterministic ``MatchRule`` names at least one attribute and a valid action;
* the probabilistic-artifact reference carries a content-addressed digest (ADR-5 —
  no probabilistic weights in Turtle, only an immutable reference);
* mastered concepts declare at least one match attribute or identifier (warning).

Returns a result dict shaped like :func:`kairos_ontology.core.validator.validate_content`
(``{"passed": bool, "errors": [...], "warnings": [...]}``) so callers can treat MDM
validation uniformly alongside syntax/SHACL results.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from kairos_ontology.mdm import vocabulary as V


def _as_bool(value: Any) -> bool:
    return value is not None and str(value).strip().lower() in ("true", "1")


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _local(iri: Any) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            return s.rsplit(sep, 1)[-1]
    return s


def validate_mdm_extension(
    graph: Graph,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate MDM policy triples in *graph*.

    *graph* should be the domain ontology merged with its ``*-mdm-ext.ttl`` (the
    projector merges these before calling; tests may pass the ext graph alone).
    *namespace*, when given, restricts "mastered concept" checks to local classes.

    Returns ``{"passed", "errors", "warnings"}``.  ``passed`` is ``False`` iff there
    is at least one error.
    """
    errors: List[str] = []
    warnings: List[str] = []

    def _in_ns(iri: Any) -> bool:
        return namespace is None or str(iri).startswith(namespace)

    # -- Mastered concepts -------------------------------------------------
    mastered_classes = [
        s for s in graph.subjects(V.MASTERED, None)
        if _as_bool(graph.value(s, V.MASTERED)) and _in_ns(s)
    ]
    for cls in mastered_classes:
        style = graph.value(cls, V.MDM_STYLE)
        if style is not None and str(style) not in V.MDM_STYLES:
            errors.append(
                f"{_local(cls)}: mdmStyle '{style}' not in {sorted(V.MDM_STYLES)}"
            )
        # Match capability: at least one match attribute / identifier on any property.
        has_match_attr = any(
            _as_bool(graph.value(p, V.MATCH_ATTRIBUTE))
            or _as_bool(graph.value(p, V.IS_IDENTIFIER))
            for p in _domain_properties(graph, cls)
        )
        has_rule = any(
            _class_of_rule(graph, r) == cls
            for r in graph.subjects(RDF.type, V.MATCH_RULE)
        )
        if not has_match_attr and not has_rule:
            warnings.append(
                f"{_local(cls)}: mastered concept has no match attribute, "
                "identifier or match rule — identity resolution cannot run."
            )

    # -- Attribute-level policy -------------------------------------------
    for prop in set(graph.subjects(V.SURVIVORSHIP, None)):
        strat = str(graph.value(prop, V.SURVIVORSHIP))
        if strat not in V.SURVIVORSHIP_STRATEGIES:
            errors.append(
                f"{_local(prop)}: survivorship '{strat}' not in "
                f"{sorted(V.SURVIVORSHIP_STRATEGIES)}"
            )

    # -- Deterministic match rules ----------------------------------------
    for rule in graph.subjects(RDF.type, V.MATCH_RULE):
        attrs = list(graph.objects(rule, V.ON_ATTRIBUTE))
        if not attrs:
            errors.append(f"{_local(rule)}: MatchRule has no onAttribute")
        comparator = graph.value(rule, V.COMPARATOR)
        if comparator is not None and str(comparator) not in V.COMPARATORS:
            errors.append(
                f"{_local(rule)}: comparator '{comparator}' not in {sorted(V.COMPARATORS)}"
            )
        action = graph.value(rule, V.MATCH_ACTION)
        if action is not None and str(action) not in V.MATCH_ACTIONS:
            errors.append(
                f"{_local(rule)}: matchAction '{action}' not in {sorted(V.MATCH_ACTIONS)}"
            )
        thr = _as_float(graph.value(rule, V.THRESHOLD))
        if thr is not None and not (0.0 <= thr <= 1.0):
            errors.append(f"{_local(rule)}: threshold {thr} out of range 0..1")

    # -- Probabilistic artifact reference (ADR-5) -------------------------
    for artifact in set(graph.objects(None, V.PROBABILISTIC_ARTIFACT)):
        digest = graph.value(artifact, V.ARTIFACT_DIGEST)
        if digest is None or not str(digest).strip():
            errors.append(
                f"{_local(artifact)}: probabilisticArtifact must declare an "
                "artifactDigest (content-addressed reference — ADR-5)"
            )

    # -- Auto-action bounds ------------------------------------------------
    for cls in set(graph.subjects(V.AUTO_ACTION_BOUND, None)):
        bound = _as_float(graph.value(cls, V.AUTO_ACTION_BOUND))
        if bound is not None and not (0.0 <= bound <= 1.0):
            errors.append(f"{_local(cls)}: autoActionBound {bound} out of range 0..1")

    # -- Data-quality rules (§11) -----------------------------------------
    for dq in graph.subjects(RDF.type, V.DQ_RULE):
        dim = graph.value(dq, V.DQ_DIMENSION)
        if dim is None or str(dim) not in V.DQ_DIMENSIONS:
            errors.append(
                f"{_local(dq)}: DataQualityRule dimension '{dim}' not in "
                f"{sorted(V.DQ_DIMENSIONS)}"
            )
        sev = graph.value(dq, V.DQ_SEVERITY)
        if sev is not None and str(sev) not in V.DQ_SEVERITIES:
            errors.append(
                f"{_local(dq)}: DQ severity '{sev}' not in {sorted(V.DQ_SEVERITIES)}"
            )
        score = _as_float(graph.value(dq, V.DQ_SCORECARD_THRESHOLD))
        if score is not None and not (0.0 <= score <= 1.0):
            errors.append(
                f"{_local(dq)}: scorecardThreshold {score} out of range 0..1"
            )

    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _domain_properties(graph: Graph, cls: URIRef) -> List[URIRef]:
    """Return properties whose rdfs:domain is *cls* or a subclass (datatype + object)."""
    from rdflib.namespace import RDFS

    classes = set(graph.transitive_subjects(RDFS.subClassOf, cls))
    classes.add(cls)
    props: List[URIRef] = []
    for c in classes:
        props.extend(
            p for p in graph.subjects(RDFS.domain, c) if isinstance(p, URIRef)
        )
    return props


def _class_of_rule(graph: Graph, rule: URIRef) -> Optional[URIRef]:
    """Return the owl:Class a MatchRule appliesTo, if declared."""
    target = graph.value(rule, V.APPLIES_TO)
    return target if isinstance(target, URIRef) else None
