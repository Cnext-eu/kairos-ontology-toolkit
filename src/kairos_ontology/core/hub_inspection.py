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
from .next_actions import (
    CompileStatus,
    DiagnosticView,
    DiscoveryConformanceStatus,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
)

# Domain-ontology filename rule, mirrored from projector._is_domain_ontology to keep this
# I/O module lightweight (no heavy projector/rdflib import). Kept in sync deliberately.
_NON_DOMAIN_PREFIXES = ("_",)
_NON_DOMAIN_SUFFIXES = ("-silver-ext", "-ext")


def _is_domain_ontology_stem(stem: str) -> bool:
    if any(stem.startswith(prefix) for prefix in _NON_DOMAIN_PREFIXES):
        return False
    if any(stem.endswith(suffix) for suffix in _NON_DOMAIN_SUFFIXES):
        return False
    return True


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


def _authored_ttl(path: Path) -> bool:
    return path.suffix == ".ttl" and not path.name.endswith(".template")


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


def _configured_adapter(root: Path) -> str:
    """Return the supported adapter from kairos.yaml, or '' when absent/unsupported."""
    import yaml

    try:
        config = yaml.safe_load((root / "kairos.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    adapter = config.get("adapter", "") if isinstance(config, dict) else ""
    return str(adapter) if adapter in ("fabric", "databricks") else ""


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
    dbt_transforms = _dir_status(
        root / "integration" / "transforms" / "dbt", lambda p: p.suffix == ".sql"
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
    )
