# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""design-landscape core logic: a read-only synthesis report over existing evidence.

Deciding *which* accelerator class to design next is today ad hoc, per-domain, by
convention. This module joins several already-existing, already-deterministic evidence
signals **by accelerator class** so an author can see, before doing any design work,
which classes have real multi-source coverage and confirmed business demand versus which
have none:

1. **Source coverage** — :func:`kairos_ontology.core.fit_report.run_fit_report`,
   generalized from one table (its original scope) to every ``<system>.<table>`` already
   recorded in a ``propose-alignment`` output (``integration/sources/_analysis/*-alignment.yaml``).
2. **Business-discovery demand** — the committed ``discovery-conformance`` artifact
   (``integration/discovery/core-concepts-conformance.yaml``, DD-090), whose
   ``core_concepts[].uri`` are already full accelerator class URIs.
3. **BI/report weight** — ``import-tmdl``'s Concept Mapping YAML output
   (``integration/discovery/bi/**/*-concept-mapping.yaml``; the legacy
   ``integration/sources/**`` location is still read for back-compat), for whichever
   ``reference_model_match`` a modeler has already filled in.
4. **Current binding state** — ``EntityBinding``s' ``target.class``/``metadata.tier``.

**This report is a deterministic aggregation only — no LLM calls, no raw TTL text reads**
(DD-103): every ontology fact is read through :mod:`kairos_ontology.core.ontology_loader`
via the already-resolved :mod:`kairos_ontology.core.reference_modules` module context, or
through :func:`kairos_ontology.core.fit_report.run_fit_report` itself.

**BI/report (``import-tmdl``) evidence is advisory only, never fact** (non-negotiable):
it is kept in the structurally separate :attr:`ClassLandscapeEntry.bi_weight` field, and it
never contributes to a class's ``bound``/``demanded`` state or its ``discovery`` field. It
may only nudge a class's rank within the ``demanded-but-unbound`` backlog.

This is intentionally the "0a" minimal cut: a flat, structured, per-class report. It does
not attempt domain clustering/regrouping suggestions or an LLM narrative pass — that is
explicitly out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .compiler.kernel import _binding_domain, _binding_target_class, _binding_tier
from .conformance_artifact import ARTIFACT_RELPATH, ConformanceArtifactError, read_artifact
from .fit_report import FitReportError, resolve_token_uri, run_fit_report
from .ontology_loader import SemanticProfile, load_ontology
from .reference_modules import build_reference_module_context, resolve_hub_accelerator_detailed

SCHEMA_VERSION = 1

ADVISORY_NOTICE = (
    "design-landscape is a deterministic aggregation of already-existing evidence signals; "
    "no LLM calls, no raw TTL reads. BI/report (import-tmdl) evidence is advisory only, "
    "never fact -- see the structurally separate bi_weight field on each class."
)

#: DD-090 outcome codes that count as *confirmed* business demand. Every other outcome
#: (``partial``, ``deviates``) still counts as discovery *evidence* (the class was in
#: scope for the interview, something was found) but never as confirmed demand.
CONFIRMED_DISCOVERY_OUTCOMES = frozenset({"conforms", "conforms-with-rename"})

#: DD-090 outcome codes that mean the SME explicitly confirmed the concept does **not**
#: apply to this business. This is itself a real, deliberate interview finding -- it still
#: surfaces in ``discovery_demand`` -- but it is the *opposite* of demand evidence, so it
#: must never rescue a class out of ``no-evidence`` the way any other outcome would.
NON_EVIDENCE_DISCOVERY_OUTCOMES = frozenset({"not-applicable"})

_ANALYSIS_SUBDIR = Path("integration") / "sources" / "_analysis"
_SOURCES_SUBDIR = Path("integration") / "sources"
_BINDINGS_SUBDIR = Path("integration") / "bindings"
_BI_DISCOVERY_SUBDIR = Path("integration") / "discovery" / "bi"


class DesignLandscapeError(ValueError):
    """Raised when design-landscape cannot resolve the minimum required inputs."""


# --------------------------------------------------------------------------------------
# Result shape (plain frozen dataclasses, JSON/dict friendly, no CLI dependency).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceTableCoverage:
    """One ``<system>.<table>`` fit-report call's populated/unpopulated counts."""

    system: str
    table: str
    populated_count: int
    unpopulated_count: int
    evidence_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "table": self.table,
            "populated_count": self.populated_count,
            "unpopulated_count": self.unpopulated_count,
            "evidence_path": self.evidence_path,
        }


@dataclass(frozen=True, slots=True)
class DiscoveryDemand:
    """One class's ``discovery-conformance`` (DD-090) outcome — first-class evidence."""

    outcome: str
    tier: str
    confirmed: bool
    artifact_path: str
    rename_to: str | None = None
    deviation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "tier": self.tier,
            "confirmed": self.confirmed,
            "artifact_path": self.artifact_path,
            "rename_to": self.rename_to,
            "deviation_reason": self.deviation_reason,
        }


@dataclass(frozen=True, slots=True)
class BiWeightSignal:
    """One ``import-tmdl`` Concept Mapping row pointing at this class — advisory ONLY.

    Never merged into :class:`SourceTableCoverage` or :class:`DiscoveryDemand` — this is
    the non-negotiable structural separation: BI/report evidence must never be reported
    with the same confidence as source-structure or discovery-conformance evidence.
    """

    concept_mapping_path: str
    tmdl_table: str
    reference_model_match: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_mapping_path": self.concept_mapping_path,
            "tmdl_table": self.tmdl_table,
            "reference_model_match": self.reference_model_match,
        }


@dataclass(frozen=True, slots=True)
class BoundBinding:
    """One existing ``EntityBinding`` already targeting this class."""

    path: str
    tier: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "tier": self.tier}


#: Fixed classification vocabulary (task 0a scope — never invented ad hoc).
CLASSIFICATIONS = (
    "canonical-candidate",
    "passthrough-candidate",
    "demanded-but-unbound",
    "bound-but-undemanded",
    "no-evidence",
)


@dataclass(frozen=True, slots=True)
class ClassLandscapeEntry:
    """One accelerator class's joined evidence + deterministic classification."""

    class_uri: str
    class_name: str
    module_id: str
    classification: str
    rank: int | None
    source_tables: tuple[SourceTableCoverage, ...]
    source_count: int
    property_universe_size: int
    populated_property_count: int
    unpopulated_property_count: int
    discovery: DiscoveryDemand | None
    bi_weight: tuple[BiWeightSignal, ...]
    bindings: tuple[BoundBinding, ...]
    bound: bool
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_uri": self.class_uri,
            "class_name": self.class_name,
            "module_id": self.module_id,
            "classification": self.classification,
            "rank": self.rank,
            "source_coverage": {
                "source_count": self.source_count,
                "tables": [item.to_dict() for item in self.source_tables],
                "property_universe_size": self.property_universe_size,
                "populated_property_count": self.populated_property_count,
                "unpopulated_property_count": self.unpopulated_property_count,
            },
            "discovery_demand": self.discovery.to_dict() if self.discovery else None,
            # Structurally separate from source_coverage/discovery_demand above (see
            # BiWeightSignal docstring) -- advisory only, never fact.
            "bi_weight": {
                "advisory_only": True,
                "reference_count": len(self.bi_weight),
                "signals": [item.to_dict() for item in self.bi_weight],
            },
            "binding_state": {
                "bound": self.bound,
                "bindings": [item.to_dict() for item in self.bindings],
            },
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class DesignLandscapeResult:
    """The complete, deterministic design-landscape report."""

    accelerator: str | None
    domain: str | None
    classes: tuple[ClassLandscapeEntry, ...]
    gaps: tuple[str, ...]
    advisory: str = ADVISORY_NOTICE
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "advisory": self.advisory,
            "accelerator": self.accelerator,
            "domain": self.domain,
            "classes": [item.to_dict() for item in self.classes],
            "gaps": list(self.gaps),
        }


# --------------------------------------------------------------------------------------
# Token/class resolution helpers.
# --------------------------------------------------------------------------------------
def _resolve_universe_token(
    token: str,
    class_record: dict[str, Any],
    name_to_uris: dict[str, set[str]],
) -> str | None:
    """Resolve a full IRI or bare local name to an in-scope accelerator class URI."""
    token = (token or "").strip()
    if not token:
        return None
    if "://" in token or token.startswith("urn:"):
        return token if token in class_record else None
    local = token.rsplit(":", 1)[-1]
    candidates = name_to_uris.get(local, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _resolve_alignment_class(
    table_dict: dict[str, Any],
    class_record: dict[str, Any],
    name_to_uris: dict[str, set[str]],
    gaps: list[str],
) -> str | None:
    """Resolve one ``propose-alignment`` table entry to an in-scope accelerator class URI.

    Prefers ``likely_entity_uri`` (the uri-anchor-contract's already-disambiguated,
    discovery-confirmed anchor) over the bare ``ref_class`` name, which may be ambiguous
    across activated modules.
    """
    likely_uri = str(table_dict.get("likely_entity_uri") or "").strip()
    if likely_uri:
        if likely_uri in class_record:
            return likely_uri
        gaps.append(
            f"alignment likely_entity_uri {likely_uri} is not part of the activated "
            "accelerator module scope; ignored for that table."
        )

    ref_class = str(table_dict.get("ref_class") or "").strip()
    if not ref_class:
        return None
    if "://" in ref_class:
        return ref_class if ref_class in class_record else None
    candidates = name_to_uris.get(ref_class, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        gaps.append(
            f"alignment ref_class {ref_class!r} is ambiguous across {len(candidates)} "
            "activated accelerator classes with the same local name; skipped."
        )
    return None


def _resolve_binding_target(
    token: str,
    *,
    binding_domain: str | None,
    hub_root: Path,
    catalog_path: Path | None,
    class_record: dict[str, Any],
    gaps: list[str],
    binding_path: Path,
) -> str | None:
    """Resolve an ``EntityBinding``'s ``target.class`` token to an in-scope class URI.

    A binding's ``target.class`` may be a local (domain) class that merely inherits from
    an accelerator class (DD-144's normal pattern) or the accelerator class directly. Both
    are resolved through the binding's own ``metadata.domain`` ontology closure -- never by
    reading raw TTL text -- so subclass-of-accelerator ancestry is honored exactly like the
    compiler kernel itself resolves it.
    """
    if binding_domain:
        domain_ontology_path = hub_root / "model" / "ontologies" / f"{binding_domain}.ttl"
        if domain_ontology_path.is_file():
            try:
                loaded = load_ontology(
                    domain_ontology_path,
                    catalog_path=catalog_path,
                    profile=SemanticProfile.KAIROS_DESIGN,
                )
            except Exception as exc:  # noqa: BLE001 - one bad binding must not block the report
                gaps.append(
                    f"binding {binding_path}: could not load domain ontology "
                    f"{domain_ontology_path}: {exc}"
                )
                return None
            local_uri = resolve_token_uri(loaded, domain_ontology_path, token)
            if local_uri is None:
                gaps.append(
                    f"binding {binding_path}: target class token {token!r} did not resolve "
                    f"against {domain_ontology_path}; skipped."
                )
                return None
            if local_uri in class_record:
                return local_uri
            local_cls = loaded.semantic_index.class_by_uri(local_uri)
            if local_cls is not None:
                for ancestor in local_cls.ancestors:
                    if ancestor.uri in class_record:
                        return ancestor.uri
            gaps.append(
                f"binding {binding_path}: target class {local_uri} has no ancestor in the "
                "activated accelerator module scope; skipped."
            )
            return None
        gaps.append(
            f"binding {binding_path}: domain ontology {domain_ontology_path} not found for "
            f"metadata.domain {binding_domain!r}; skipped."
        )
        return None

    # No metadata.domain to resolve a local qname against -- only a bare full IRI that is
    # itself an accelerator class can still be matched.
    if ("://" in token or token.startswith("urn:")) and token in class_record:
        return token
    gaps.append(
        f"binding {binding_path}: target class {token!r} has no metadata.domain to resolve "
        "a local qname against; skipped."
    )
    return None


# --------------------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------------------
def run_design_landscape(
    hub_root: Path,
    *,
    ref_models_dir: Path | None,
    accelerator: str | None = None,
    domain: str | None = None,
    catalog_path: Path | None = None,
) -> DesignLandscapeResult:
    """Compute the deterministic design-landscape report for one accelerator/domain scope.

    Args:
        hub_root: The ontology hub root (``model/ontologies/``, ``integration/`` live here).
        ref_models_dir: The reference-models checkout (activated accelerator modules).
        accelerator: Explicit accelerator id, else resolved the same way every other
            accelerator-aware command resolves it (:func:`resolve_hub_accelerator_detailed`).
        domain: Restrict the activated module scope to one hub data domain. Omitted means
            every configured module profile in the resolved accelerator's registry.
        catalog_path: Optional explicit XML catalog for import resolution (default:
            ``<hub_root>/catalog-v001.xml`` when present).

    Returns:
        A :class:`DesignLandscapeResult`. Raises :class:`DesignLandscapeError` only when the
        activated accelerator module scope itself cannot be resolved -- every other gap (no
        conformance artifact, no propose-alignment output, an unresolvable binding, ...) is
        reported advisory-style in ``gaps`` rather than raised (degrade gracefully).
    """
    hub_root = Path(hub_root)
    gaps: list[str] = []

    if catalog_path is None:
        default_catalog = hub_root / "catalog-v001.xml"
        catalog_path = default_catalog if default_catalog.is_file() else None

    if ref_models_dir is None or not Path(ref_models_dir).is_dir():
        raise DesignLandscapeError(
            "no reference-models checkout found; design-landscape needs one to enumerate "
            "activated accelerator classes. Pass --ref-models-dir or set "
            "KAIROS_REFMODELS_ROOT."
        )
    ref_models_dir = Path(ref_models_dir)

    try:
        resolution = resolve_hub_accelerator_detailed(
            explicit=accelerator,
            hub_root=hub_root,
            ref_models_dir=ref_models_dir,
            domain_hint=[domain] if domain else (),
        )
    except ValueError as exc:
        raise DesignLandscapeError(str(exc)) from exc
    resolved_accelerator = resolution.accelerator
    if resolved_accelerator is None:
        raise DesignLandscapeError("no accelerator could be resolved; pass --accelerator explicitly.")

    context = build_reference_module_context(
        ref_models_dir,
        catalog_path=catalog_path,
        accelerator=resolved_accelerator,
        requested_domains=[domain] if domain else None,
    )
    if context is None or not context.modules:
        scope = f" for domain {domain!r}" if domain else ""
        raise DesignLandscapeError(
            f"accelerator {resolved_accelerator!r} has no resolvable activated module(s){scope}."
        )
    for diagnostic in context.diagnostics:
        gaps.append(f"module diagnostic [{diagnostic.level}] {diagnostic.code}: {diagnostic.message}")

    # --- Activated accelerator class universe (module-scoped, never the whole registry) --
    class_owner: dict[str, str] = {}
    class_record: dict[str, Any] = {}
    name_to_uris: dict[str, set[str]] = {}
    module_root_path: dict[str, Path] = {}
    module_by_id = {module.profile.id: module for module in context.modules}

    for module in context.modules:
        root_entry = next((item for item in module.manifest if item.import_depth == 0), None)
        if root_entry is not None:
            module_root_path[module.profile.id] = Path(root_entry.source_path)
        for cls in module.semantic_index.classes:
            class_owner.setdefault(cls.uri, module.profile.id)
            class_record.setdefault(cls.uri, cls)
            name_to_uris.setdefault(cls.name, set()).add(cls.uri)

    if not class_record:
        gaps.append("activated accelerator module(s) declare no classes.")

    # --- 2. Business-discovery demand (DD-090 discovery-conformance) ----------------------
    demand_by_class: dict[str, DiscoveryDemand] = {}
    conformance_path = hub_root / ARTIFACT_RELPATH
    if conformance_path.is_file():
        try:
            artifact = read_artifact(conformance_path)
        except ConformanceArtifactError as exc:
            gaps.append(f"could not read discovery-conformance artifact {conformance_path}: {exc}")
            artifact = None
        if artifact is not None:
            for concept in artifact.get("core_concepts", []) or []:
                if not isinstance(concept, dict):
                    continue
                uri = str(concept.get("uri") or "").strip()
                outcome = str(concept.get("outcome") or "").strip()
                if not uri or not outcome:
                    continue
                if uri not in class_record:
                    gaps.append(
                        f"discovery-conformance concept {uri} is not part of the activated "
                        "accelerator module scope; skipped."
                    )
                    continue
                demand_by_class[uri] = DiscoveryDemand(
                    outcome=outcome,
                    tier=str(concept.get("tier") or ""),
                    confirmed=outcome in CONFIRMED_DISCOVERY_OUTCOMES,
                    artifact_path=str(conformance_path),
                    rename_to=concept.get("rename_to"),
                    deviation_reason=concept.get("deviation_reason"),
                )
    else:
        gaps.append(
            f"no discovery-conformance artifact found at {conformance_path}; "
            "business-discovery demand evidence is unavailable."
        )

    # --- 1. Source coverage (propose-alignment output, generalized fit-report) ------------
    analysis_dir = hub_root / _ANALYSIS_SUBDIR
    tables_by_class: dict[str, set[tuple[str, str]]] = {}
    if analysis_dir.is_dir():
        alignment_files = sorted(analysis_dir.glob("*-alignment.yaml"))
        if not alignment_files:
            gaps.append(f"no propose-alignment output (*-alignment.yaml) found under {analysis_dir}.")
        for alignment_path in alignment_files:
            try:
                document = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                gaps.append(f"could not read {alignment_path}: {exc}")
                continue
            if not isinstance(document, dict):
                continue
            for table_dict in document.get("tables", ()) or ():
                if not isinstance(table_dict, dict):
                    continue
                system = str(table_dict.get("system") or "").strip()
                table = str(table_dict.get("table") or "").strip()
                if not system or not table:
                    continue
                resolved_uri = _resolve_alignment_class(table_dict, class_record, name_to_uris, gaps)
                if resolved_uri is None:
                    continue
                tables_by_class.setdefault(resolved_uri, set()).add((system, table))
    else:
        gaps.append(
            f"no propose-alignment analysis directory found ({analysis_dir}); "
            "source-coverage evidence is unavailable."
        )

    source_coverage_by_class: dict[str, list[SourceTableCoverage]] = {}
    populated_union: dict[str, set[str]] = {}
    for class_uri, refs in tables_by_class.items():
        module_id = class_owner.get(class_uri)
        ontology_path = module_root_path.get(module_id) if module_id else None
        if ontology_path is None or not ontology_path.is_file():
            gaps.append(
                f"cannot resolve a physical ontology document for class {class_uri}; "
                "source-coverage fit-report skipped for it."
            )
            continue
        for system, table in sorted(refs):
            try:
                fit = run_fit_report(
                    ontology_path,
                    class_uri,
                    catalog_path=catalog_path,
                    source=f"{system}.{table}",
                    analysis_dir=analysis_dir,
                )
            except FitReportError as exc:
                gaps.append(f"fit-report failed for {class_uri} against {system}.{table}: {exc}")
                continue
            source_coverage_by_class.setdefault(class_uri, []).append(
                SourceTableCoverage(
                    system=system,
                    table=table,
                    populated_count=len(fit.populated),
                    unpopulated_count=len(fit.unpopulated),
                    evidence_path=fit.evidence_path,
                )
            )
            populated_union.setdefault(class_uri, set()).update(
                item.property_uri for item in fit.populated
            )

    # --- 3. BI/report weight (import-tmdl Concept Mapping) -- ADVISORY ONLY ---------------
    bi_weight_by_class: dict[str, list[BiWeightSignal]] = {}
    bi_dir = hub_root / _BI_DISCOVERY_SUBDIR
    legacy_bi_dir = hub_root / _SOURCES_SUBDIR
    if bi_dir.is_dir() or legacy_bi_dir.is_dir():
        mapping_files: list[Path] = []
        if bi_dir.is_dir():
            mapping_files.extend(bi_dir.rglob("*-concept-mapping.yaml"))
        if legacy_bi_dir.is_dir():
            mapping_files.extend(legacy_bi_dir.rglob("*-concept-mapping.yaml"))
        mapping_files = sorted(set(mapping_files))
        unfilled = 0
        for mapping_path in mapping_files:
            try:
                document = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                gaps.append(f"could not read {mapping_path}: {exc}")
                continue
            if not isinstance(document, dict):
                continue
            for table_dict in document.get("tables", ()) or ():
                if not isinstance(table_dict, dict):
                    continue
                match = str(table_dict.get("reference_model_match") or "").strip()
                tmdl_name = str(table_dict.get("tmdl_name") or "")
                if not match:
                    # Not a bug: import-tmdl leaves this blank for a human to fill in.
                    unfilled += 1
                    continue
                resolved_uri = _resolve_universe_token(match, class_record, name_to_uris)
                if resolved_uri is None:
                    gaps.append(
                        f"BI concept-mapping {mapping_path.name}: reference_model_match "
                        f"{match!r} for table {tmdl_name!r} does not resolve to an activated "
                        "accelerator class; skipped."
                    )
                    continue
                bi_weight_by_class.setdefault(resolved_uri, []).append(
                    BiWeightSignal(
                        concept_mapping_path=str(mapping_path),
                        tmdl_table=tmdl_name,
                        reference_model_match=match,
                    )
                )
        if unfilled:
            gaps.append(
                f"{unfilled} TMDL concept-mapping table(s) have an empty "
                "reference_model_match (not yet filled in by a modeler); no BI weight "
                "evidence is available for them. design-landscape never infers this "
                "itself -- no LLM classification is performed in this pass."
            )
    else:
        gaps.append(
            f"no {bi_dir} directory found; BI/report weight evidence is unavailable."
        )

    # --- 4. Current binding state -----------------------------------------------------------
    bindings_by_class: dict[str, list[BoundBinding]] = {}
    bindings_dir = hub_root / _BINDINGS_SUBDIR
    if bindings_dir.is_dir():
        for binding_path in sorted(bindings_dir.glob("*.binding.yaml")):
            try:
                text = binding_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                gaps.append(f"could not read {binding_path}: {exc}")
                continue
            token = _binding_target_class(text)
            if not token:
                continue
            tier = _binding_tier(text)
            binding_domain = _binding_domain(text)
            resolved_uri = _resolve_binding_target(
                token,
                binding_domain=binding_domain,
                hub_root=hub_root,
                catalog_path=catalog_path,
                class_record=class_record,
                gaps=gaps,
                binding_path=binding_path,
            )
            if resolved_uri is None:
                continue
            bindings_by_class.setdefault(resolved_uri, []).append(
                BoundBinding(path=str(binding_path), tier=tier)
            )
    else:
        gaps.append(f"no {bindings_dir} directory found; binding-state evidence is unavailable.")

    # --- Join + classify --------------------------------------------------------------------
    scope_uris = set(tables_by_class) | set(demand_by_class) | set(bindings_by_class)
    entries: list[ClassLandscapeEntry] = []
    for class_uri in sorted(scope_uris):
        cls = class_record.get(class_uri)
        if cls is None:
            continue  # already reported via a gap at resolution time
        module_id = class_owner.get(class_uri, "")
        owner_module = module_by_id.get(module_id)
        universe = owner_module.semantic_index.class_properties(class_uri) if owner_module else []
        universe_size = len(universe)

        source_tables = tuple(
            sorted(source_coverage_by_class.get(class_uri, ()), key=lambda item: (item.system, item.table))
        )
        source_count = len({(item.system, item.table) for item in source_tables})
        populated_count = len(populated_union.get(class_uri, ()))
        unpopulated_count = max(universe_size - populated_count, 0)

        demand = demand_by_class.get(class_uri)
        bi_weight = tuple(bi_weight_by_class.get(class_uri, ()))
        bindings = tuple(bindings_by_class.get(class_uri, ()))
        bound = bool(bindings)
        has_discovery_evidence = demand is not None and demand.outcome not in NON_EVIDENCE_DISCOVERY_OUTCOMES
        has_confirmed_demand = bool(demand and demand.confirmed)

        if not bound and source_count == 0 and not has_discovery_evidence:
            classification = "no-evidence"
        elif bound and source_count == 0 and not has_discovery_evidence:
            classification = "bound-but-undemanded"
        elif source_count >= 2 and has_confirmed_demand:
            classification = "canonical-candidate"
        elif source_count == 1:
            classification = "passthrough-candidate"
        else:
            classification = "demanded-but-unbound"

        entries.append(
            ClassLandscapeEntry(
                class_uri=class_uri,
                class_name=cls.name,
                module_id=module_id,
                classification=classification,
                rank=None,
                source_tables=source_tables,
                source_count=source_count,
                property_universe_size=universe_size,
                populated_property_count=populated_count,
                unpopulated_property_count=unpopulated_count,
                discovery=demand,
                bi_weight=bi_weight,
                bindings=bindings,
                bound=bound,
            )
        )

    # Rank the real backlog: confirmed demand first, then source structure, then BI weight
    # as a tie-break ONLY -- BI evidence may raise a class's priority in the ranking, never
    # its classification or confidence tier (non-negotiable, see module docstring).
    backlog_order = sorted(
        (entry for entry in entries if entry.classification == "demanded-but-unbound"),
        key=lambda entry: (
            0 if (entry.discovery and entry.discovery.confirmed) else 1,
            -entry.source_count,
            -len(entry.bi_weight),
            entry.class_name,
        ),
    )
    rank_by_uri = {entry.class_uri: index + 1 for index, entry in enumerate(backlog_order)}
    ranked_entries = tuple(
        replace(entry, rank=rank_by_uri[entry.class_uri]) if entry.class_uri in rank_by_uri else entry
        for entry in sorted(entries, key=lambda entry: entry.class_name)
    )

    return DesignLandscapeResult(
        accelerator=resolved_accelerator,
        domain=domain,
        classes=ranked_entries,
        gaps=tuple(gaps),
    )
