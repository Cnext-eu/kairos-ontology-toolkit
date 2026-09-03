# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-input snapshot gatherer for ``kairos-ontology next`` (DD-137).

This is the **I/O half** of the readiness proposal. It inspects an authored hub on disk and
the canonical compiler, then returns an in-memory :class:`HubInputSnapshot` that the pure
:func:`kairos_ontology.core.next_actions.propose_next_actions` proposer consumes.

Boundary rules: this module may import :mod:`kairos_ontology.core.compiler`; it never imports
:mod:`kairos_ontology.mdm`. It reuses the existing binding loader and compiler entry points
rather than adding an alternate YAML/scope resolver, and it reports only defensible presence
observations — never "complete".
"""

from __future__ import annotations

from pathlib import Path

from .adapters import UnsupportedAdapterError, resolve_adapter

import yaml

from .compiler import (
    CompileMode,
    CompileError,
    build_compile_plan,
    compile_plan_result,
    order_compile_diagnostics,
)
from .compiler.kernel import _binding_domain, _binding_tier
from .conformance_artifact import (
    ARTIFACT_RELPATH,
    ConformanceArtifactError,
    has_unresolved_fleet_items,
    read_artifact,
)
from .hub_utils import is_authored_discovery_ttl, is_domain_ontology_stem
from .next_actions import (
    BiConceptMappingObservation,
    CompileStatus,
    DiagnosticView,
    DiscoveryConformanceStatus,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
    SourceDispositionObservation,
    SourceDomainCoverageObservation,
    SourceSampleObservation,
    SourceSampleStatus,
)

# Thin alias kept for existing call sites (below). The actual predicate lives in
# hub_utils.is_domain_ontology_stem — a leaf module shared with core/projector.py,
# core/validator.py, and core/catalog_test.py — so the four copies cannot drift
# apart again (issue #289).
_is_domain_ontology_stem = is_domain_ontology_stem


def _dir_status(root: Path, predicate) -> InputStatus:
    """Return a defensible presence observation for authored content under *root*."""
    if not root.exists():
        return InputStatus.MISSING
    try:
        for path in root.rglob("*"):
            if path.is_file() and predicate(path):
                return InputStatus.PRESENT
    except OSError:
        return InputStatus.UNREADABLE
    return InputStatus.MISSING


# Thin alias kept for existing call sites/tests (e.g. tests/test_cli_next.py imports this
# name directly). The actual predicate lives in hub_utils.is_authored_discovery_ttl — a leaf
# module shared with conformance_artifact.check_discovery_gate's DD-148 hard gate — so a
# scaffold-provided template (init's businessdiscovery/glossary-template.ttl) cannot be
# miscounted as authored evidence in one place while still being excluded in the other (#288).
_authored_ttl = is_authored_discovery_ttl


def _authored_dbt_transform(path: Path) -> bool:
    """Return True when *path* is authored dbt transform content under the transforms tree.

    A ``.sql`` model, or (#586 stage b) an authored seed CSV under ``seeds/``. The probe used
    to be ``.sql``-only, so a hub whose entire authored transform layer was one reference
    seed reported ``dbt_transforms: missing`` to ``kairos-ontology next`` and was told to go
    author the transforms it had already written. Seed *column-docs* YAML deliberately does
    not count on its own: docs without the CSV they describe are not authored content.
    """
    if path.suffix == ".sql":
        return True
    return path.suffix.lower() == ".csv" and "seeds" in path.parts


def _emitted_dbt_status(root: Path) -> InputStatus:
    """Observe the unified emitted dbt project (presence only, never freshness)."""
    from .hub_utils import publish_root

    project_file = publish_root(root) / "medallion" / "dbt" / "dbt_project.yml"
    if not project_file.exists():
        return InputStatus.MISSING
    try:
        project_file.read_text(encoding="utf-8")
    except OSError:
        return InputStatus.UNREADABLE
    return InputStatus.PRESENT


def _discovery_conformance_status(root: Path) -> DiscoveryConformanceStatus:
    """Observe the discovery conformance artifact's validity (DD-148), read defensively.

    Deliberately lighter than full ``validate_artifact()`` (no outcome-codes catalog
    resolution) — same rationale as ``check_discovery_gate()``: this must never crash
    ``kairos-ontology next``, and it only needs to detect unresolved fleet-mode items.
    """
    path = root / ARTIFACT_RELPATH
    if not path.is_file():
        return DiscoveryConformanceStatus.NOT_RUN
    try:
        artifact = read_artifact(path)
    except ConformanceArtifactError:
        return DiscoveryConformanceStatus.INVALID
    if has_unresolved_fleet_items(artifact):
        return DiscoveryConformanceStatus.UNRESOLVED_FLEET
    return DiscoveryConformanceStatus.VALID


def _source_sample_status(sources_dir: Path) -> SourceSampleObservation:
    """Observe whether discovered source tables carry any sample-value evidence (#298).

    Parses the already-generated source vocabulary TTL under *sources_dir* (only files
    ``_authored_ttl`` accepts — a scaffold template is never counted) via the existing
    ``analyse_sources.parse_source_vocabulary`` helper (DD-103: bronze-vocabulary TTL is
    read there, not via the canonical semantic loader, and this reuses that single
    established parse site rather than opening a new one) looking for
    ``kairos-bronze:SourceTable``s and whether any column has a ``kairos-bronze:sampleValues``
    value. Deliberately defensive, same spirit as :func:`_discovery_conformance_status`:
    a malformed vocabulary file must reduce coverage, never crash ``kairos-ontology next``.

    Tables are keyed by ``(source-system directory, table name)`` — the first path segment
    under *sources_dir* is the source system — so same-named tables from different systems
    (e.g. two systems both having a ``customers`` table) are never conflated into one.
    """
    if not sources_dir.is_dir():
        return SourceSampleObservation()

    from .analyse_sources import parse_source_vocabulary

    try:
        paths = [p for p in sources_dir.rglob("*") if p.is_file() and _authored_ttl(p)]
    except OSError:
        return SourceSampleObservation()

    tables: set[str] = set()
    tables_with_samples: set[str] = set()
    for path in paths:
        try:
            system = path.relative_to(sources_dir).parts[0]
        except ValueError:
            system = path.parent.name
        try:
            parsed = parse_source_vocabulary(path)
        except Exception:
            continue
        for table_name, columns in parsed.items():
            key = f"{system}::{table_name}"
            tables.add(key)
            if any(column.get("samples") for column in columns):
                tables_with_samples.add(key)

    if not tables:
        return SourceSampleObservation()

    total = len(tables)
    with_samples = len(tables_with_samples & tables)
    if with_samples == 0:
        status = SourceSampleStatus.NONE
    elif with_samples == total:
        status = SourceSampleStatus.FULL
    else:
        status = SourceSampleStatus.PARTIAL
    return SourceSampleObservation(
        status=status, tables_with_samples=with_samples, tables_total=total
    )


def _bi_concept_mapping_status(root: Path) -> BiConceptMappingObservation:
    """Observe import-tmdl concept-mapping worksheet triage state (issue #421, DD-157).

    Delegates to the shared ``evidence_loaders.scan_concept_mapping_worksheets`` helper
    (the same count ``design-landscape`` reports) so the two surfaces can never diverge.
    Wrapped defensively — a malformed worksheet tree must never crash
    ``kairos-ontology next``; failure degrades to the no-observation default.
    """
    from .evidence_loaders import scan_concept_mapping_worksheets

    try:
        scan = scan_concept_mapping_worksheets(root)
    except Exception:
        return BiConceptMappingObservation()
    return BiConceptMappingObservation(
        tables_total=scan.tables_total, tables_unfilled=scan.tables_unfilled
    )


def _source_domain_coverage_status(root: Path) -> SourceDomainCoverageObservation:
    """Observe source-affinity vs modeled/bound domain coverage (issue #496/#498, DD-160).

    Reuses ``build_domain_coverage_report`` so ``next`` and ``domain-coverage`` can never
    disagree about which domains hold unbound source data. Accelerator resolution is
    deliberately best-effort here: the statuses this observation reads
    (``not-modeled``/``deferred``) are derived from affinity x ontology x bindings and
    never from the blueprint column, so a hub with no accelerator installed still gets
    the signal.

    Wrapped defensively — a malformed affinity report or ontology must never crash
    ``kairos-ontology next``; failure degrades to the no-observation default.
    """
    from .domain_coverage import (
        STATUS_DEFERRED,
        STATUS_NOT_MODELED,
        build_domain_coverage_report,
    )

    try:
        accelerator: str | None = None
        ref_models_dir = None
        try:
            from .reference_modules import resolve_hub_accelerator_detailed

            resolution = resolve_hub_accelerator_detailed(
                explicit=None, hub_root=root, ref_models_dir=None
            )
            accelerator = resolution.accelerator
        except Exception:
            accelerator = None

        report = build_domain_coverage_report(
            ontologies_dir=root / "model" / "ontologies",
            bindings_dir=root / "integration" / "bindings",
            master_path=root / "model" / "ontologies" / "_master.ttl",
            ref_models_dir=ref_models_dir,
            accelerator=accelerator,
            analysis_dir=root / "integration" / "sources" / "_analysis",
        )
    except Exception:
        return SourceDomainCoverageObservation()

    if not report.has_affinity_evidence:
        return SourceDomainCoverageObservation()

    def _domains(status: str) -> tuple[str, ...]:
        return tuple(row.domain for row in report.rows if row.status == status)

    return SourceDomainCoverageObservation(
        not_modeled=_domains(STATUS_NOT_MODELED),
        deferred=_domains(STATUS_DEFERRED),
        unassigned_tables=len(report.unassigned_source_tables),
    )


def _source_disposition_status(root: Path) -> SourceDispositionObservation:
    """Count source tables with no recorded outcome (DD-164).

    Degrades to the no-observation default on any failure: a hub mid-import can have a
    half-written vocabulary, and a crashing observer must not take `next` down with it.
    The audit itself is the authority -- this only reads its counts.
    """
    try:
        from .source_disposition import audit_source_dispositions

        report = audit_source_dispositions(hub_root=root)
    except Exception:
        return SourceDispositionObservation()
    if not report.tables_total:
        return SourceDispositionObservation()
    return SourceDispositionObservation(
        tables_total=report.tables_total,
        tables_undecided=report.tables_undecided,
    )


def _registered_concepts_unbound(root: Path) -> int:
    """Count registered concepts (#505 Layer B) no EntityBinding targets yet.

    Matches by the binding's ``target.class`` **URI**, read with a plain YAML load: a binding
    that does not parse is ``compile --check``'s problem to report, and treating it as "targets
    nothing" would only inflate this count. Bindings usually write ``target.class`` as a
    ``prefix:Local`` token rather than a URI, so a token that happens to resolve to a
    registered concept is *not* matched here -- the count can therefore overstate, never
    understate, which is the safe direction for an advisory nudge.

    Wrapped defensively: a malformed registrations file must never crash ``next``.
    """
    from .registered_concepts import read_registered

    try:
        registered = read_registered(root)
    except Exception:  # noqa: BLE001 - advisory observation only
        return 0
    if not registered:
        return 0

    targeted: set[str] = set()
    bindings_dir = root / "integration" / "bindings"
    if bindings_dir.is_dir():
        for path in sorted(bindings_dir.glob("*.binding.yaml")):
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            target = document.get("target") if isinstance(document, dict) else None
            if isinstance(target, dict) and isinstance(target.get("class"), str):
                targeted.add(target["class"].strip())
    return sum(1 for entry in registered if str(entry.get("uri") or "") not in targeted)




def _configured_adapter(root: Path) -> str:
    """Return the supported adapter from kairos.yaml, or '' when absent/unsupported."""
    import yaml

    try:
        config = yaml.safe_load((root / "kairos.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    adapter = config.get("adapter", "") if isinstance(config, dict) else ""
    try:
        canonical, _ = resolve_adapter(str(adapter))
    except UnsupportedAdapterError:
        return ""
    return canonical


def configured_modes_served(root: Path) -> list[str] | None:
    """Return the ``modes_served`` list from kairos.yaml, or ``None`` when absent.

    Backward compatible: when the field is absent or empty, ``None`` is returned
    (meaning "all modes served"). Duplicates are stripped and values are stripped
    of surrounding whitespace.
    """
    import yaml

    try:
        config = yaml.safe_load((root / "kairos.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(config, dict):
        return None
    raw = config.get("modes_served")
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    modes = [str(item).strip() for item in raw if item is not None and str(item).strip()]
    if not modes:
        return None
    # Deduplicate while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for mode in modes:
        if mode not in seen:
            seen.add(mode)
            result.append(mode)
    return result


def _ontology_domains(ontologies_dir: Path) -> tuple[set[str], set[str]]:
    """Return (domain stems, unreadable stems) from ``model/ontologies``."""
    domains: set[str] = set()
    unreadable: set[str] = set()
    if not ontologies_dir.is_dir():
        return domains, unreadable
    for path in sorted(ontologies_dir.glob("*.ttl")):
        stem = path.stem
        if not _is_domain_ontology_stem(stem):
            continue
        try:
            path.read_text(encoding="utf-8")
        except OSError:
            unreadable.add(stem)
            continue
        domains.add(stem)
    return domains, unreadable


def _binding_domains(bindings_dir: Path) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Return (count per declared ``metadata.domain``, tier tally per domain).

    The tier tally carries ``metadata.tier`` (DD-1xx two-tier Silver) alongside the
    existing domain count so ``next``/``coverage-report`` can report tier-1 (passthrough)
    vs. tier-2 (canonical) coverage separately without a second pass over the bindings
    directory. This is data collection only — it does not change the readiness ladder.
    """
    counts: dict[str, int] = {}
    tier_counts: dict[str, dict[str, int]] = {}
    if not bindings_dir.is_dir():
        return counts, tier_counts
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        domain = _binding_domain(text)
        if not domain:
            continue
        counts[domain] = counts.get(domain, 0) + 1
        tier = _binding_tier(text)
        domain_tiers = tier_counts.setdefault(domain, {})
        domain_tiers[tier] = domain_tiers.get(tier, 0) + 1
    return counts, tier_counts


def _extension_status(extensions_dir: Path, domain: str, suffix: str) -> InputStatus:
    candidate = extensions_dir / f"{domain}{suffix}"
    if candidate.is_file():
        return InputStatus.PRESENT
    return InputStatus.MISSING


def _check_domain(hub_root: Path, domain: str) -> tuple[CompileStatus, tuple[DiagnosticView, ...]]:
    """Run the canonical compile check for *domain* without rendering artifacts."""
    try:
        plan = build_compile_plan(hub_root, domain)
        result = compile_plan_result(plan, CompileMode.CHECK, render=False)
        diagnostics = result.diagnostics.ordered
        status = CompileStatus.FAILED if result.diagnostics.has_errors else CompileStatus.PASSED
    except CompileError as exc:
        diagnostics = order_compile_diagnostics(exc.diagnostics)
        status = CompileStatus.FAILED
    except Exception as exc:  # defensive: environment/parse failure, never readiness
        return (
            CompileStatus.UNAVAILABLE,
            (
                DiagnosticView(
                    code="next.compile-unavailable",
                    message=f"compile check could not run: {exc}",
                    severity="error",
                    location=str(hub_root),
                    rule_id="DD-137",
                ),
            ),
        )
    views = tuple(
        DiagnosticView(
            code=item.code,
            message=item.message,
            severity=item.severity.value,
            location=item.location.render(),
            rule_id=item.rule_id,
        )
        for item in diagnostics
    )
    return status, views


def gather_hub_input_snapshot(
    hub_root: str | Path,
    domains: "list[str] | tuple[str, ...] | None" = None,
    run_compile: bool = True,
) -> HubInputSnapshot:
    """Inspect *hub_root* and return a defensible :class:`HubInputSnapshot`.

    ``domains`` restricts compilation/reporting to the given set (still validated against the
    discovered union). ``run_compile=False`` yields ``compile_status=not_run`` so downstream
    readiness is reported as indeterminate rather than falsely ready.
    """
    root = Path(hub_root).resolve()

    discovery = _dir_status(root / "businessdiscovery", _authored_ttl)
    sources = _dir_status(root / "integration" / "sources", _authored_ttl)
    source_samples = _source_sample_status(root / "integration" / "sources")
    dbt_transforms = _dir_status(
        root / "integration" / "transforms" / "dbt", _authored_dbt_transform
    )
    shapes = _dir_status(root / "model" / "shapes", _authored_ttl)

    ontologies_dir = root / "model" / "ontologies"
    extensions_dir = root / "model" / "extensions"
    ontology_domains, unreadable_domains = _ontology_domains(ontologies_dir)
    binding_counts, binding_tier_counts = _binding_domains(root / "integration" / "bindings")

    all_domains = sorted(ontology_domains | unreadable_domains | set(binding_counts))
    requested = set(domains) if domains else None
    ontology_only = tuple(
        name for name in all_domains if name in ontology_domains and name not in binding_counts
    )
    binding_only = tuple(
        name
        for name in all_domains
        if name in binding_counts
        and name not in ontology_domains
        and name not in unreadable_domains
    )

    domain_snapshots: list[DomainSnapshot] = []
    for name in all_domains:
        if requested is not None and name not in requested:
            continue
        if name in unreadable_domains:
            ontology = InputStatus.UNREADABLE
        elif name in ontology_domains:
            ontology = InputStatus.PRESENT
        else:
            ontology = InputStatus.MISSING
        binding_count = binding_counts.get(name, 0)
        has_bindings = binding_count > 0
        domain_tiers = binding_tier_counts.get(name, {})
        passthrough_count = domain_tiers.get("passthrough", 0)
        canonical_count = domain_tiers.get("canonical", 0)

        if not run_compile or not has_bindings:
            compile_status: CompileStatus = CompileStatus.NOT_RUN
            diagnostics: tuple[DiagnosticView, ...] = ()
        else:
            compile_status, diagnostics = _check_domain(root, name)

        domain_snapshots.append(
            DomainSnapshot(
                domain=name,
                ontology=ontology,
                has_bindings=has_bindings,
                binding_count=binding_count,
                compile_status=compile_status,
                diagnostics=diagnostics,
                gold_policy=_extension_status(extensions_dir, name, "-gold-ext.ttl"),
                mdm_policy=_extension_status(extensions_dir, name, "-mdm-ext.ttl"),
                passthrough_count=passthrough_count,
                canonical_count=canonical_count,
            )
        )

    return HubInputSnapshot(
        hub_root=str(root),
        discovery=discovery,
        sources=sources,
        dbt_transforms=dbt_transforms,
        shapes=shapes,
        domains=tuple(domain_snapshots),
        ontology_only_domains=ontology_only,
        binding_only_domains=binding_only,
        compile_ran=run_compile,
        emitted_dbt_project=_emitted_dbt_status(root),
        adapter=_configured_adapter(root),
        discovery_conformance=_discovery_conformance_status(root),
        source_samples=source_samples,
        bi_concept_mappings=_bi_concept_mapping_status(root),
        source_domain_coverage=_source_domain_coverage_status(root),
        registered_concepts_unbound=_registered_concepts_unbound(root),
        source_dispositions=_source_disposition_status(root),
    )
