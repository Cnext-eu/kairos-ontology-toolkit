# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The ``mdm-profile`` projection target — emits an immutable MDM profile release.

This is the 8th projection target (ADR-1).  It reads a domain ontology merged with
its ``<domain>-mdm-ext.ttl`` policy and emits, under ``output/mdm/``:

* ``<domain>-mdm-profile.json`` — the canonical, runtime-neutral profile consumed by
  ``kairos-mdm-runtime`` and pinned by the dataplatform under ``contracts/mdm/``;
* ``<domain>-mdm-profile.md`` — a human-readable summary for governance review.

The JSON carries a ``content_digest`` (sha256 over the policy, excluding the volatile
generation timestamp) so the release is **content-addressed and immutable** — two
runs from the same reviewed hub state produce the same digest (ADR-11: durable state
is never regenerable; generated artifacts are replaceable but reproducible).

A domain without an ``*-mdm-ext.ttl`` (or with no mastered concepts) yields **no
artifacts** — MDM policy is opt-in per domain.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS

from kairos_ontology.mdm import vocabulary as V
from kairos_ontology.core.determinism import resolve_generated_at
from kairos_ontology.mdm.model import (
    DataQualityRule,
    MasteredConcept,
    MatchAttribute,
    MatchRule,
    MdmProfile,
    ProbabilisticArtifactRef,
    ProfileProvenance,
    ReferenceListPolicy,
    StewardRole,
    SurvivorshipRule,
    WorkflowPolicy,
)


def _as_bool(value: Any) -> bool:
    return value is not None and str(value).strip().lower() in ("true", "1")


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _local(iri: Any) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            return s.rsplit(sep, 1)[-1]
    return s


def _toolkit_version() -> str:
    try:
        from kairos_ontology import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _domain_properties(graph: Graph, cls: URIRef) -> List[URIRef]:
    """Properties whose rdfs:domain is *cls* or any (transitive) subclass of it.

    Subtype attributes matter for mastering: e.g. a mastered ``Client`` may match on
    ``vatNumber`` even when that property is declared on the ``CorporateClient``
    subclass.  ``transitive_subjects`` includes *cls* itself.
    """
    from rdflib.namespace import RDFS

    classes = set(graph.transitive_subjects(RDFS.subClassOf, cls))
    classes.add(cls)
    props: List[URIRef] = []
    for c in classes:
        props.extend(
            p for p in graph.subjects(RDFS.domain, c) if isinstance(p, URIRef)
        )
    return props


def extract_profile(
    graph: Graph,
    namespace: str,
    ontology_name: str,
    ontology_metadata: Optional[Dict[str, Any]] = None,
) -> MdmProfile:
    """Build an :class:`MdmProfile` from a merged domain+MDM-extension *graph*.

    Only classes in *namespace* are considered local; imported reference-model
    classes are ignored unless annotated locally.
    """
    meta = ontology_metadata or {}
    profile = MdmProfile()

    profile.provenance = ProfileProvenance(
        domain=ontology_name,
        ontology_iri=meta.get("namespace", namespace) or namespace,
        ontology_version=str(meta.get("version", "")),
        toolkit_version=_toolkit_version(),
        generated_at=resolve_generated_at().isoformat(),
    )

    # -- Mastered concepts -------------------------------------------------
    for cls in sorted(graph.subjects(V.MASTERED, None), key=str):
        if not _as_bool(graph.value(cls, V.MASTERED)):
            continue
        if not str(cls).startswith(namespace):
            continue

        props = _domain_properties(graph, cls)
        match_attrs = _extract_match_attributes(graph, props)
        survivorship = [
            SurvivorshipRule(
                property_iri=str(a.property_iri),
                strategy=a.survivorship,
                priority=a.survivorship_priority,
            )
            for a in match_attrs
            if a.survivorship
        ]

        concept = MasteredConcept(
            class_iri=str(cls),
            name=_local(cls),
            label=str(graph.value(cls, RDFS.label) or _local(cls)),
            mdm_style=_opt_str(graph.value(cls, V.MDM_STYLE)),
            match_attributes=match_attrs,
            match_rules=_extract_match_rules(graph, cls, props),
            survivorship=survivorship,
            workflow=WorkflowPolicy(
                maker_checker=_as_bool(graph.value(cls, V.MAKER_CHECKER)),
                auto_action_bound=_as_float(graph.value(cls, V.AUTO_ACTION_BOUND)),
                sla_hours=_as_int(graph.value(cls, V.SLA_HOURS)),
                escalation_role=_opt_str(graph.value(cls, V.ESCALATION_ROLE)),
            ),
            data_quality=_extract_dq_rules(graph, cls, props),
        )
        profile.mastered_concepts.append(concept)

    # -- Reference lists ---------------------------------------------------
    for cls in sorted(graph.subjects(V.REFERENCE_LIST, None), key=str):
        if not _as_bool(graph.value(cls, V.REFERENCE_LIST)):
            continue
        if not str(cls).startswith(namespace):
            continue
        profile.reference_lists.append(
            ReferenceListPolicy(
                class_iri=str(cls),
                name=_local(cls),
                owner=_opt_str(graph.value(cls, V.REFERENCE_OWNER)),
                release_policy=_opt_str(graph.value(cls, V.RELEASE_POLICY)),
                license=_opt_str(graph.value(cls, V.REFERENCE_LICENSE)),
            )
        )

    # -- Abstract steward roles -------------------------------------------
    for role in sorted(graph.subjects(RDF.type, V.STEWARD_ROLE), key=str):
        profile.steward_roles.append(
            StewardRole(
                role_iri=str(role),
                name=str(graph.value(role, V.ROLE_NAME) or _local(role)),
                scope=_opt_str(graph.value(role, V.ROLE_SCOPE)),
            )
        )

    # -- Probabilistic artifact reference (ADR-5) -------------------------
    for artifact in graph.objects(None, V.PROBABILISTIC_ARTIFACT):
        profile.probabilistic_artifact = ProbabilisticArtifactRef(
            digest=str(graph.value(artifact, V.ARTIFACT_DIGEST) or ""),
            version=_opt_str(graph.value(artifact, V.ARTIFACT_VERSION)),
            uri=_opt_str(graph.value(artifact, V.ARTIFACT_URI)),
        )
        break  # one probabilistic model per domain profile

    return profile


def _opt_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _extract_match_attributes(
    graph: Graph, props: List[URIRef]
) -> List[MatchAttribute]:
    attrs: List[MatchAttribute] = []
    for prop in sorted(props, key=str):
        is_match = _as_bool(graph.value(prop, V.MATCH_ATTRIBUTE))
        is_id = _as_bool(graph.value(prop, V.IS_IDENTIFIER))
        survivorship = _opt_str(graph.value(prop, V.SURVIVORSHIP))
        authorities = sorted(
            str(o) for o in graph.objects(prop, V.AUTHORITATIVE_SOURCE)
        )
        if not (is_match or is_id or survivorship or authorities):
            continue
        attrs.append(
            MatchAttribute(
                property_iri=str(prop),
                name=_local(prop),
                is_identifier=is_id,
                identifier_type=_opt_str(graph.value(prop, V.IDENTIFIER_TYPE)),
                authoritative_sources=authorities,
                survivorship=survivorship,
                survivorship_priority=_as_int(
                    graph.value(prop, V.SURVIVORSHIP_PRIORITY)
                ),
            )
        )
    return attrs


def _extract_match_rules(
    graph: Graph, cls: URIRef, props: List[URIRef]
) -> List[MatchRule]:
    prop_set = {str(p) for p in props}
    rules: List[MatchRule] = []
    for rule in sorted(graph.subjects(RDF.type, V.MATCH_RULE), key=str):
        applies_to = graph.value(rule, V.APPLIES_TO)
        on_attrs = sorted(str(o) for o in graph.objects(rule, V.ON_ATTRIBUTE))
        # A rule belongs to this concept if it explicitly appliesTo it, or (when
        # unscoped) all its attributes are on this concept's properties.
        if applies_to is not None:
            if str(applies_to) != str(cls):
                continue
        elif not on_attrs or not all(a in prop_set for a in on_attrs):
            continue
        rules.append(
            MatchRule(
                rule_iri=str(rule),
                on_attributes=on_attrs,
                comparator=str(graph.value(rule, V.COMPARATOR) or "exact"),
                threshold=_as_float(graph.value(rule, V.THRESHOLD)),
                action=str(graph.value(rule, V.MATCH_ACTION) or "candidate"),
            )
        )
    return rules


def _extract_dq_rules(
    graph: Graph, cls: URIRef, props: List[URIRef]
) -> List[DataQualityRule]:
    prop_set = {str(p) for p in props}
    rules: List[DataQualityRule] = []
    for dq in sorted(graph.subjects(RDF.type, V.DQ_RULE), key=str):
        applies_to = graph.value(dq, V.APPLIES_TO)
        on_attrs = sorted(str(o) for o in graph.objects(dq, V.ON_ATTRIBUTE))
        if applies_to is not None:
            if str(applies_to) != str(cls):
                continue
        elif not on_attrs or not all(a in prop_set for a in on_attrs):
            continue
        rules.append(
            DataQualityRule(
                rule_iri=str(dq),
                dimension=str(graph.value(dq, V.DQ_DIMENSION) or ""),
                on_attributes=on_attrs,
                expression=_opt_str(graph.value(dq, V.DQ_EXPRESSION)),
                scorecard_threshold=_as_float(
                    graph.value(dq, V.DQ_SCORECARD_THRESHOLD)
                ),
                severity=str(graph.value(dq, V.DQ_SEVERITY) or "warning"),
            )
        )
    return rules


def _content_digest(profile_dict: Dict[str, Any]) -> str:
    """sha256 over the policy, excluding the volatile generation timestamp.

    Two runs from the same reviewed hub state produce the same digest.
    """
    stable = json.loads(json.dumps(profile_dict))  # deep copy
    stable.get("provenance", {}).pop("generated_at", None)
    stable.get("provenance", {}).pop("toolkit_version", None)
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _render_markdown(profile: MdmProfile, digest: str) -> str:
    p = profile
    lines: List[str] = []
    lines.append(f"# MDM profile — {p.provenance.domain}")
    lines.append("")
    lines.append(f"- **Ontology:** `{p.provenance.ontology_iri}`")
    lines.append(f"- **Ontology version:** {p.provenance.ontology_version or '—'}")
    lines.append(f"- **Toolkit version:** {p.provenance.toolkit_version}")
    lines.append(f"- **Generated:** {p.provenance.generated_at}")
    lines.append(f"- **Content digest:** `{digest}`")
    lines.append("")

    lines.append("## Mastered concepts")
    lines.append("")
    if not p.mastered_concepts:
        lines.append("_None._")
    for c in p.mastered_concepts:
        lines.append(f"### {c.label} (`{c.name}`)")
        lines.append("")
        lines.append(f"- **MDM style:** {c.mdm_style or '—'}")
        lines.append(
            f"- **Maker/checker:** {'yes' if c.workflow.maker_checker else 'no'}"
            + (
                f" · auto-action ≥ {c.workflow.auto_action_bound}"
                if c.workflow.auto_action_bound is not None
                else ""
            )
            + (f" · SLA {c.workflow.sla_hours}h" if c.workflow.sla_hours else "")
        )
        if c.match_attributes:
            lines.append("- **Match attributes:**")
            for a in c.match_attributes:
                tags = []
                if a.is_identifier:
                    tags.append(f"identifier{f' ({a.identifier_type})' if a.identifier_type else ''}")
                if a.survivorship:
                    tags.append(f"survivorship={a.survivorship}")
                if a.authoritative_sources:
                    tags.append(f"authority={','.join(a.authoritative_sources)}")
                suffix = f" — {'; '.join(tags)}" if tags else ""
                lines.append(f"    - `{a.name}`{suffix}")
        if c.match_rules:
            lines.append("- **Deterministic match rules:**")
            for r in c.match_rules:
                attrs = ", ".join(_local(a) for a in r.on_attributes)
                thr = f" @ {r.threshold}" if r.threshold is not None else ""
                lines.append(
                    f"    - {r.comparator}({attrs}){thr} → {r.action}"
                )
        if c.data_quality:
            lines.append("- **Data-quality rules:**")
            for d in c.data_quality:
                attrs = ", ".join(_local(a) for a in d.on_attributes) or "—"
                thr = (
                    f" ≥ {d.scorecard_threshold}"
                    if d.scorecard_threshold is not None
                    else ""
                )
                lines.append(
                    f"    - [{d.dimension}/{d.severity}] {attrs}{thr}"
                )
        lines.append("")

    if p.reference_lists:
        lines.append("## Reference lists")
        lines.append("")
        for r in p.reference_lists:
            lines.append(
                f"- **{r.name}** — owner: {r.owner or '—'}, "
                f"release: {r.release_policy or '—'}, license: {r.license or '—'}"
            )
        lines.append("")

    if p.steward_roles:
        lines.append("## Abstract steward roles")
        lines.append("")
        for role in p.steward_roles:
            lines.append(f"- **{role.name}** — scope: {role.scope or '—'}")
        lines.append("")

    if p.probabilistic_artifact:
        a = p.probabilistic_artifact
        lines.append("## Probabilistic matching artifact (ADR-5)")
        lines.append("")
        lines.append(f"- **Digest:** `{a.digest}`")
        if a.version:
            lines.append(f"- **Version:** {a.version}")
        if a.uri:
            lines.append(f"- **URI:** {a.uri}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_mdm_profile_artifacts(
    graph: Graph,
    namespace: str,
    ontology_name: str,
    mdm_ext_path: Optional[Path] = None,
    ontology_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Project the ``mdm-profile`` target for one domain.

    Merges *graph* with the discovered ``*-mdm-ext.ttl`` (*mdm_ext_path*), extracts
    the profile, and returns ``{filename: content}``.  Returns ``{}`` when there is
    no MDM policy (no extension file or no mastered concepts) — MDM is opt-in.
    """
    from kairos_ontology.core.projections.shared import merge_ext_graph

    if mdm_ext_path is None or not Path(mdm_ext_path).exists():
        return {}

    merged = merge_ext_graph(graph, Path(mdm_ext_path))
    profile = extract_profile(merged, namespace, ontology_name, ontology_metadata)

    if not profile.mastered_concepts and not profile.reference_lists:
        return {}

    profile_dict = profile.to_dict()
    digest = _content_digest(profile_dict)
    profile_dict["content_digest"] = digest

    json_content = json.dumps(profile_dict, indent=2, sort_keys=True) + "\n"
    md_content = _render_markdown(profile, digest)

    return {
        f"{ontology_name}-mdm-profile.json": json_content,
        f"{ontology_name}-mdm-profile.md": md_content,
    }
