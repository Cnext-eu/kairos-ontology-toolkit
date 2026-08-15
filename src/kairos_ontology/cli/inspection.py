# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused inspection CLI commands."""

import fnmatch
import hashlib
import json
import os
import tempfile
import click
from pathlib import Path

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _autodetect_analysis_dir,
    _format_refmodels_fetch_provenance,
    _git_head_sha,
    _git_ignored_snapshot,
    _git_repo_root,
    _git_status_snapshot,
    resolve_refmodels_dir,
    _resolve_semantic_input,
    _warn_if_no_skill_context,
)


def _format_refmodels_version(ref_models_dir: Path) -> str:
    """Return a non-blocking reference-model VERSION status for CLI output."""
    version_path = ref_models_dir / "VERSION"
    if not version_path.exists():
        return "not present (version metadata optional; checking local files)"
    if not version_path.is_file():
        return "unavailable (VERSION path is not a file)"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        return f"unavailable (could not read VERSION: {exc})"
    if not version:
        return "unavailable (VERSION is empty)"
    return version


@click.command(name="resolve-ontology")
@click.argument("ontology")
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--degraded", is_flag=True, default=False)
@click.option("--json-output", "as_json", is_flag=True, default=False)
def resolve_ontology_cmd(ontology, catalog, degraded, as_json):
    """Resolve an ontology closure and show its deterministic manifest."""
    from ..core.ontology_loader import load_ontology

    path, catalog_path = _resolve_semantic_input(ontology, catalog)
    loaded = load_ontology(path, catalog_path=catalog_path, degraded=degraded)
    payload = {
        "schema_version": 1,
        "semantic_profile": loaded.profile.value,
        "closure_hash": loaded.closure_hash,
        "import_complete": loaded.complete,
        "manifest": loaded.manifest_dicts(),
        "diagnostics": [item.to_dict() for item in loaded.diagnostics],
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    click.echo(f"Closure: {loaded.closure_hash}")
    click.echo(f"Profile: {loaded.profile.value}")
    click.echo(f"Import complete: {loaded.complete}")
    for entry in loaded.manifest:
        click.echo(f"  {'  ' * entry.import_depth}{entry.source_identity} [{entry.rdf_format}]")
    for diagnostic in loaded.diagnostics:
        click.echo(f"  {diagnostic.level.upper()}: {diagnostic.message}")


def _compute_class_tokens(loaded, ontology_path: Path, class_uri: str) -> list[str]:
    """Return bindable class tokens for ``class_uri`` (issue #445).

    Matches what ``compile --check`` prints as "usable class tokens": the full URI,
    rdflib-built-in qnames, declared ``@prefix`` aliases from the source Turtle
    closure, and the ``<domain-stem>:<LocalName>`` token.
    """
    from ..core.compiler.kernel import _qnames, declared_prefix_aliases

    from rdflib import URIRef

    graph = loaded.graph
    tokens: set[str] = set()
    tokens.update(_qnames(graph, URIRef(class_uri)))
    tokens.update(declared_prefix_aliases(loaded, ontology_path, class_uri))
    domain_prefix = ontology_path.stem
    local = class_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    tokens.add(f"{domain_prefix}:{local}")
    return sorted(tokens)


@click.command(name="show-class-inventory")
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--domain", default=None, help="Hub domain name when --ontology is omitted.")
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--profile",
    type=click.Choice(["asserted", "rdfs", "kairos-design", "owl-rl"]),
    default="kairos-design",
)
@click.option("--max-classes", type=click.IntRange(min=1), default=None)
def show_class_inventory_cmd(ontology, domain, catalog, profile, max_classes):
    """Print a versioned semantic-index class slice as JSON."""
    from ..core.hub_utils import find_hub_root
    from ..core.ontology_loader import load_ontology

    if ontology:
        path = Path(ontology)
    elif domain:
        hub = find_hub_root(Path.cwd(), require_model=True)
        if hub is None:
            raise click.ClickException("Cannot locate a hub for --domain.")
        path = hub / "model" / "ontologies" / f"{domain}.ttl"
        if not path.is_file():
            raise click.ClickException(f"Domain ontology not found: {path}")
    else:
        raise click.UsageError("Provide --ontology or --domain.")
    loaded = load_ontology(
        path,
        catalog_path=Path(catalog) if catalog else None,
        profile=profile,
    )
    data = loaded.semantic_index.slice(max_classes=max_classes)
    for entry in data["classes"]:
        entry["tokens"] = _compute_class_tokens(loaded, path, entry["uri"])
    click.echo(json.dumps(data, indent=2, sort_keys=True))


@click.command(name="list-class-properties")
@click.argument("class_iri")
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--domain", default=None, help="Hub domain name when --ontology is omitted.")
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
def list_class_properties_cmd(class_iri, ontology, domain, catalog):
    """List direct and inherited class properties, including effective ranges."""
    from ..core.hub_utils import find_hub_root
    from ..core.ontology_loader import load_ontology

    if ontology:
        path = Path(ontology)
    elif domain:
        hub = find_hub_root(Path.cwd(), require_model=True)
        if hub is None:
            raise click.ClickException("Cannot locate a hub for --domain.")
        path = hub / "model" / "ontologies" / f"{domain}.ttl"
    else:
        raise click.UsageError("Provide --ontology or --domain.")
    loaded = load_ontology(
        path,
        catalog_path=Path(catalog) if catalog else None,
        profile="kairos-design",
    )
    cls = loaded.semantic_index.class_by_uri(class_iri)
    if cls is None:
        raise click.ClickException(
            f"Class does not resolve in the scoped domain closure: {class_iri}"
        )
    click.echo(
        json.dumps(
            {
                "schema_version": 1,
                "class_uri": class_iri,
                "tokens": _compute_class_tokens(loaded, path, class_iri),
                "properties": loaded.semantic_index.class_properties(class_iri),
            },
            indent=2,
            sort_keys=True,
        )
    )


_FIT_REPORT_ADVISORY = "fit-report is advisory input to design, not a completeness check."


def _render_fit_report_text(result) -> None:
    click.echo(f"🔎 fit-report — {_FIT_REPORT_ADVISORY}")
    click.echo(f"   Class: {result.class_name} ({result.class_uri})")
    evidence = result.evidence_kind
    if evidence == "binding":
        click.echo(f"   Evidence: binding {result.evidence_path}")
    elif evidence == "source-alignment":
        click.echo(
            f"   Evidence: propose-alignment {result.evidence_path} "
            f"(source: {result.source_system}.{result.source_table})"
        )
    else:
        click.echo("   Evidence: none")
        if result.source_system and result.notes:
            # Issue #397: --source's "Evidence: none" is indistinguishable from a real
            # negative result unless the reason (usually: no prior propose-alignment
            # run) is right next to it, not just buried in the Notes section below.
            click.echo(f"     ({result.notes[0]})")
    if result.technical_fields:
        purposes = ", ".join(f"{item.name} [{item.purpose}]" for item in result.technical_fields)
        click.echo(
            f"   Technical fields (not ontology properties, DD-139): "
            f"{len(result.technical_fields)} ({purposes})"
        )
    click.echo("")
    click.echo(f"   Populated ({len(result.populated)}):")
    for item in result.populated:
        click.echo(f"     ✓ {item.name} [{item.origin}] ← {item.source}")
    click.echo("")
    click.echo(f"   Unpopulated ({len(result.unpopulated)}):")
    for item in result.unpopulated:
        click.echo(f"     • {item.name} [{item.origin}] ({item.property_uri})")
    if result.orphan_columns:
        click.echo("")
        click.echo(f"   Orphan columns ({len(result.orphan_columns)}):")
        for item in result.orphan_columns:
            reason = f" — {item.reason}" if item.reason else ""
            click.echo(f"     ? {item.column} ({item.data_type}){reason}")
    if result.notes:
        click.echo("")
        click.echo("   Notes:")
        for note in result.notes:
            click.echo(f"     - {note}")


@click.command(name="fit-report")
@click.option(
    "--class",
    "class_token",
    required=True,
    help="Full class IRI or a 'prefix:Local' qname to report on.",
)
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--domain", default=None, help="Hub domain name when --ontology is omitted.")
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--source",
    default=None,
    help="'<system>.<table>' to check against existing propose-alignment evidence.",
)
@click.option(
    "--binding",
    "binding_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Explicit EntityBinding YAML to use as evidence (default: auto-detect the one "
    "binding under integration/bindings/ that already targets --class, if exactly one does).",
)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
def fit_report_cmd(class_token, ontology, domain, catalog, source, binding_path, out_format):
    """Advisory set-difference between a class's full property universe and what is populated.

    fit-report is advisory input to design, not a completeness check (DD-144). It answers,
    deterministically and without any LLM call: of everything an accelerator already models
    for --class, which properties does a binding's fields: (or --source's propose-alignment
    evidence) already populate, which are still empty, and which source columns don't map
    anywhere. Evidence priority: --binding (or an unambiguous auto-detected binding under
    integration/bindings/) first, then --source's propose-alignment output.

    \b
    Examples:
      kairos-ontology fit-report --class acc:TradeParty --domain party
      kairos-ontology fit-report --class acc:TradeParty --source crm.organisations
      kairos-ontology fit-report --class acc:TradeParty --binding integration/bindings/x.binding.yaml --format json
    """
    from ..core.fit_report import FitReportError, run_fit_report
    from ..core.hub_utils import find_hub_root
    from .shared import _autodetect_analysis_dir

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if ontology:
        path = Path(ontology)
    elif domain:
        if hub_root is None:
            raise click.ClickException("Cannot locate a hub for --domain.")
        path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
    else:
        raise click.UsageError("Provide --ontology or --domain.")

    bindings_dir = None
    analysis_dir = None
    if hub_root is not None:
        candidate_bindings_dir = hub_root / "integration" / "bindings"
        if candidate_bindings_dir.is_dir():
            bindings_dir = candidate_bindings_dir
        analysis_dir = _autodetect_analysis_dir(Path.cwd(), hub_root)

    try:
        result = run_fit_report(
            path,
            class_token,
            catalog_path=Path(catalog) if catalog else None,
            binding_path=Path(binding_path) if binding_path else None,
            bindings_dir=bindings_dir,
            source=source,
            analysis_dir=analysis_dir,
        )
    except FitReportError as exc:
        raise click.ClickException(str(exc)) from exc

    if out_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    _render_fit_report_text(result)


def _render_inverse_scan_text(result) -> None:
    click.echo(f"🔎 inverse-scan — {_FIT_REPORT_ADVISORY}")
    click.echo(f"   Class: {result.class_name} ({result.class_uri})")
    click.echo(
        f"   Universe properties: {result.universe_property_count}  |  "
        f"Tables scanned: {result.tables_scanned}  |  "
        f"Source systems: {', '.join(result.source_systems_scanned) or '(none)'}"
    )
    click.echo("")
    if not result.candidates:
        click.echo("   Candidates: none (no exact column-name matches found)")
    else:
        click.echo(f"   Candidates ({len(result.candidates)}):")
        for c in result.candidates:
            click.echo(
                f"     • {c.source_system}.{c.source_table}  "
                f"({len(c.matched_properties)}/{c.total_columns} columns matched)"
            )
            for prop in c.matched_properties:
                click.echo(f"       - {prop}")
    click.echo("")
    click.echo("   Notes:")
    for note in result.notes:
        click.echo(f"     - {note}")


@click.command(name="inverse-scan")
@click.option(
    "--class",
    "class_token",
    required=True,
    help="Full class IRI or a 'prefix:Local' qname to find candidate sources for.",
)
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--domain", default=None, help="Hub domain name when --ontology is omitted.")
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
def inverse_scan_cmd(class_token, ontology, domain, catalog, out_format):
    """Find candidate source tables for a class via deterministic column-name matching.

    The inverse of fit-report: given a class, scan every source table across every source
    system under integration/sources/ and report which tables have columns whose names
    deterministically match the class's datatype or object properties.

    Only the deterministic tier (exact column-name equality) is evaluated. What was NOT
    evaluated — LLM-assisted semantic matching, fuzzy name similarity, value-sample
    inference, or cross-system relationship discovery — is explicitly labelled in the
    output so a short candidate list is never mistaken for a completeness finding.

    \b
    Examples:
      kairos-ontology inverse-scan --class acc:TradeParty --domain party
      kairos-ontology inverse-scan --class acc:TradeParty --domain party --format json
    """
    from ..core.fit_report import FitReportError, run_inverse_scan
    from ..core.hub_utils import find_hub_root

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if ontology:
        path = Path(ontology)
    elif domain:
        if hub_root is None:
            raise click.ClickException("Cannot locate a hub for --domain.")
        path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
    else:
        raise click.UsageError("Provide --ontology or --domain.")

    if hub_root is None:
        raise click.ClickException("Cannot locate a hub root.")

    try:
        result = run_inverse_scan(
            path,
            class_token,
            hub_root,
            catalog_path=Path(catalog) if catalog else None,
        )
    except FitReportError as exc:
        raise click.ClickException(str(exc)) from exc

    if out_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    _render_inverse_scan_text(result)


def _render_plan_sources_text(result) -> None:
    click.echo(f"📐 plan-sources — {result.class_token} ({result.class_uri})")
    click.echo("   DD-133 §3c: raw multi-source conformance requires identical grain/identity")
    click.echo("   type-kinds, identity strategy, and property type set across every binding.")
    click.echo("")
    if not result.bindings:
        click.echo("   Existing bindings: none")
    else:
        click.echo(f"   Existing bindings ({len(result.bindings)}):")
        for fact in result.bindings:
            click.echo(f"     - {fact.name} [{fact.source_ref}] ({fact.source_path})")
            grain = ", ".join(
                f"{col.name}:{col.kind or col.data_type or '?'}" for col in fact.grain
            )
            identity = ", ".join(
                f"{col.name}:{col.kind or col.data_type or '?'}" for col in fact.identity
            )
            click.echo(f"       grain: {grain or '(none)'}")
            click.echo(f"       identity [{fact.identity_strategy}]: {identity or '(none)'}")
            if fact.conformance_group:
                click.echo(
                    f"       conformance: group={fact.conformance_group} "
                    f"precedence={fact.source_precedence} conflict={fact.conflict} "
                    f"union={fact.union_mode}"
                )
    if result.candidate is not None:
        candidate = result.candidate
        click.echo("")
        click.echo(f"   Candidate: {candidate.source_system}.{candidate.source_table}")
        if candidate.key_columns:
            columns = ", ".join(
                f"{col.name}:{col.kind or col.data_type or '?'}" for col in candidate.key_columns
            )
            click.echo(f"     columns: {columns}")
        if candidate.compatible is True:
            click.echo("     ✓ identity type-kinds match — raw conformance is feasible")
        elif candidate.compatible is False:
            click.echo("     ✗ identity type-kinds do NOT match — raw conformance would fail")
        for note in candidate.notes:
            click.echo(f"     - {note}")


@click.command(name="plan-sources")
@click.option(
    "--class",
    "class_token",
    required=True,
    help="Full class IRI or a 'prefix:Local' qname to preview conformance for.",
)
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--domain", default=None, help="Hub domain name when --ontology is omitted.")
@click.option(
    "--source",
    default=None,
    help="Candidate '<system>.<table>' not yet bound, to preview against existing bindings.",
)
@click.option(
    "--key-column",
    "key_columns",
    multiple=True,
    help="Candidate source column that would serve as the identity key. Repeatable, in "
    "sourceKey order. Only meaningful together with --source.",
)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
def plan_sources_cmd(class_token, ontology, domain, source, key_columns, out_format):
    """Preview DD-133 §3c multi-source conformance before authoring bindings (issue #286).

    Reports the grain/identity type-kinds of every existing binding already targeting
    --class, and — when --source (plus --key-column) is given — whether that candidate
    could satisfy the same conformance contract if bound directly. This runs the same
    type-kind comparison `compile` runs, one step earlier: before hand-authoring a second
    (or third...) binding to a class, not after `compile --check` fails.

    \b
    Examples:
      kairos-ontology plan-sources --class acc:TradeParty --domain party
      kairos-ontology plan-sources --class acc:TradeParty --domain party \\
        --source erp.parties --key-column party_id
    """
    from ..core.plan_sources import PlanSourcesError, run_plan_sources
    from ..core.hub_utils import find_hub_root

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if ontology:
        path = Path(ontology)
    elif domain:
        if hub_root is None:
            raise click.ClickException("Cannot locate a hub for --domain.")
        path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
    else:
        raise click.UsageError("Provide --ontology or --domain.")

    if hub_root is None:
        raise click.ClickException("Cannot locate a hub root.")
    bindings_dir = hub_root / "integration" / "bindings"
    sources_dir = hub_root / "integration" / "sources"

    try:
        result = run_plan_sources(
            path,
            class_token,
            hub_root=hub_root,
            bindings_dir=bindings_dir if bindings_dir.is_dir() else None,
            sources_dir=sources_dir,
            source=source,
            key_columns=key_columns,
        )
    except PlanSourcesError as exc:
        raise click.ClickException(str(exc)) from exc

    if out_format == "json":
        from dataclasses import asdict

        click.echo(json.dumps(asdict(result), indent=2, sort_keys=True))
        return
    _render_plan_sources_text(result)


@click.command(name="explain-term")
@click.argument("iri")
@click.option("--ontology", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--profile",
    type=click.Choice(["asserted", "rdfs", "kairos-design", "owl-rl"]),
    default="kairos-design",
)
def explain_term_cmd(iri, ontology, catalog, profile):
    """Explain one full-URI term with semantic and import provenance."""
    from dataclasses import asdict

    from ..core.ontology_loader import load_ontology

    loaded = load_ontology(
        Path(ontology),
        catalog_path=Path(catalog) if catalog else None,
        profile=profile,
    )
    term = loaded.semantic_index.term(iri)
    if term is None:
        raise click.ClickException(f"Term is not present in the closure: {iri}")
    click.echo(
        json.dumps(
            {
                "schema_version": 1,
                "semantic_profile": loaded.profile.value,
                "closure_hash": loaded.closure_hash,
                "import_complete": loaded.complete,
                "term": asdict(term),
            },
            indent=2,
            sort_keys=True,
        )
    )


@click.command("coverage-report")
@click.option(
    "--ontology",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/ontologies/ directory (default: auto-detect from hub).",
)
@click.option(
    "--ref-models",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontology-reference-models/ directory (default: auto-detect).",
)
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ (for evidence tracing).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: ontology-hub-publish/reports/).",
)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["yaml", "markdown", "both"]),
    default="both",
    help="Output format (default: both).",
)
def coverage_report_cmd(ontology, ref_models, sources, output, out_format):
    """Generate ontology-to-reference-model coverage report.

    Measures how well the domain ontology aligns with industry reference models
    using deterministic matching (rdfs:seeAlso, owl:imports, name matching).
    No LLM or API keys required.

    \b
    Examples:
      kairos-ontology coverage-report
      kairos-ontology coverage-report --format markdown
      kairos-ontology coverage-report --ontology path/to/ontologies/ --ref-models path/to/refs/
    """
    from ..core.coverage_report import (
        run_coverage_report,
        write_coverage_yaml,
        write_coverage_markdown,
    )

    # Auto-detect hub paths
    from ..core.hub_utils import find_hub_root, publish_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontology is None:
        if hub_root:
            ont_path = hub_root / "model" / "ontologies"
        else:
            click.echo(
                "❌ Cannot find model/ontologies/ directory. Use --ontology to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        ont_path = Path(ontology)

    if ref_models is None:
        ref_models_path = resolve_refmodels_dir(cwd, hub_root)
        if ref_models_path is None:
            click.echo(
                "❌ Cannot find ontology-reference-models/ directory. Use --ref-models to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        ref_models_path = Path(ref_models)

    sources_path = None
    if sources:
        sources_path = Path(sources)
    elif hub_root and (hub_root / "integration" / "sources").is_dir():
        sources_path = hub_root / "integration" / "sources"

    if output is None:
        if hub_root:
            output_path = publish_root(hub_root) / "reports"
        else:
            output_path = Path("ontology-hub-publish/reports")
    else:
        output_path = Path(output)

    click.echo("📊 Generating coverage report")
    click.echo(f"   Ontology: {ont_path}")
    click.echo(f"   Reference models: {ref_models_path}")
    click.echo()

    try:
        report = run_coverage_report(
            ontology_dir=ont_path,
            ref_models_dir=ref_models_path,
            sources_dir=sources_path,
            catalog_path=(
                hub_root / "catalog-v001.xml"
                if hub_root and (hub_root / "catalog-v001.xml").is_file()
                else None
            ),
        )

        output_files = []
        if out_format in ("yaml", "both"):
            yaml_path = write_coverage_yaml(report, output_path)
            output_files.append(yaml_path)
        if out_format in ("markdown", "both"):
            md_path = write_coverage_markdown(report, output_path)
            output_files.append(md_path)

        click.echo("\n✅ Coverage report generated!")
        click.echo(
            f"   Classes: {report.aligned_classes}/{report.total_classes} "
            f"({report.class_coverage_pct}%)"
        )
        click.echo(
            f"   Properties: {report.aligned_properties}/{report.total_properties} "
            f"({report.property_coverage_pct}%)"
        )
        click.echo()
        for f in output_files:
            click.echo(f"   📄 {f}")

    except EnvironmentError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)


@click.command(name="field-mapping-report")
@click.option(
    "--ontologies",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/ontologies/ directory (default: auto-detect from hub).",
)
@click.option(
    "--bindings",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/bindings/ directory of v5 EntityBindings (default: auto-detect).",
)
@click.option(
    "--sources",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/sources/ directory, for sample values (default: auto-detect).",
)
@click.option(
    "--source-system",
    required=True,
    help="Source system to derive the mapping from (e.g. 'cargowise'), matched against the "
    "first dot-segment of each binding's source.relation.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Restrict to specific domain(s) (repeatable). Default: every domain ontology found.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output .xlsx path (default: ontology-hub-publish/reports/field-mapping-<source-system>.xlsx).",
)
def field_mapping_report_cmd(ontologies, bindings, sources, source_system, domains, output):
    """Generate a field-mapping Excel report: ontology fields x one source system.

    One worksheet per domain, listing every declared scalar (owl:DatatypeProperty) field
    with its ontology-authored description and IRI, cross-referenced against the
    EntityBindings that map the given --source-system onto it -- embedding the mapped
    source column and a real sample value when source vocabulary/sample data exists for it.

    Object properties / relationship joins are out of scope for this report; only
    fields:-declared scalar mappings are shown.

    \b
    Examples:
      kairos-ontology field-mapping-report --source-system cargowise
      kairos-ontology field-mapping-report --source-system cargowise --domain party
    """
    from ..core.field_mapping_report import run_field_mapping_report, write_field_mapping_workbook
    from ..core.hub_utils import find_hub_root, publish_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontologies is None:
        if hub_root:
            ontologies_path = hub_root / "model" / "ontologies"
        else:
            click.echo(
                "❌ Cannot find model/ontologies/ directory. Use --ontologies to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        ontologies_path = Path(ontologies)

    if bindings is None:
        if hub_root:
            bindings_dir = hub_root / "integration" / "bindings"
        else:
            click.echo(
                "❌ Cannot find integration/bindings/ directory. Use --bindings to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        bindings_dir = Path(bindings)

    if sources is None:
        if hub_root:
            sources_dir = hub_root / "integration" / "sources"
        else:
            click.echo(
                "❌ Cannot find integration/sources/ directory. Use --sources to specify.",
                err=True,
            )
            raise SystemExit(1)
    else:
        sources_dir = Path(sources)

    if output is None:
        report_dir = (
            publish_root(hub_root) / "reports" if hub_root else Path("ontology-hub-publish/reports")
        )
        output_path = report_dir / f"field-mapping-{source_system}.xlsx"
    else:
        output_path = Path(output)

    click.echo("📄 Generating field-mapping report")
    click.echo(f"   Ontologies:    {ontologies_path}")
    click.echo(f"   Bindings:      {bindings_dir}")
    click.echo(f"   Sources:       {sources_dir}")
    click.echo(f"   Source system: {source_system}")
    click.echo(f"   Output:        {output_path}")
    click.echo()

    report = run_field_mapping_report(
        ontologies_path=ontologies_path,
        bindings_dir=bindings_dir,
        sources_dir=sources_dir,
        hub_root=hub_root or ontologies_path.parent.parent,
        source_system=source_system,
        domains=tuple(domains),
    )

    try:
        write_field_mapping_workbook(report, output_path)
    except ImportError as e:
        click.echo(f"\n❌ {e}", err=True)
        raise SystemExit(1)

    total_fields = sum(len(rows) for rows in report.rows_by_domain.values())
    mapped_fields = sum(
        1 for rows in report.rows_by_domain.values() for row in rows if row.source_columns
    )
    click.echo(f"✅ Field-mapping report written: {output_path}")
    click.echo(
        f"   {len(report.rows_by_domain)} domain(s), {total_fields} field(s), "
        f"{mapped_fields} mapped to '{source_system}'"
    )
    for note in report.notes:
        click.echo(f"   ⚠ {note}")


@click.command(name="generate-inventory")
@click.option(
    "--ontology-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/ontologies/ directory (default: auto-detect from hub).",
)
@click.option(
    "--ref-models-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontology-reference-models/ directory (default: auto-detect).",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: referencemodels-unpacked/).",
)
@click.option(
    "--prune/--no-prune",
    default=True,
    help="Remove orphaned inventory files no longer produced by any "
    "source (default: prune). Retired stem-named files require migrate.",
)
def generate_inventory_cmd(ontology_dir, ref_models_dir, output_dir, prune):
    """Generate materialized YAML inventories for ontologies and reference models.

    Produces one YAML file per domain/reference model containing classes, properties,
    and specialization trees (DD-044).  Inventories are consumed by analyse-sources,
    propose-alignment, and coverage-report as a cached alternative to re-parsing TTL.

    Reference-model modules are namespaced by their owning model (DD-054), e.g.
    ``bsp-party-inventory.yaml``, so same-named modules from different models no
    longer overwrite each other.

    Files are written to referencemodels-unpacked/ and should be committed to git.

    \\b
    Examples:
      kairos-ontology generate-inventory
      kairos-ontology generate-inventory --output-dir referencemodels-unpacked/
      kairos-ontology generate-inventory --ref-models-dir path/to/refs/
    """
    from ..core.command_outcome import (
        REASON_COLLISION,
        REASON_EMPTY,
        REASON_EXCEPTION,
        REASON_EXCLUDED,
        CommandOutcome,
        CommandOutcomeDecline,
        CommandOutcomeTarget,
    )
    from ..core.inventory import (
        check_inventories,
        find_legacy_inventory_files,
        generate_inventory,
        inventory_filename,
        is_pattern_template_source,
        iter_reference_inventory_sources,
        legacy_inventory_error,
        write_inventory,
    )
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    # Resolve ontology directory
    if ontology_dir:
        ont_path = Path(ontology_dir)
    elif hub_root:
        ont_path = hub_root / "model" / "ontologies"
    else:
        ont_path = None

    # Resolve reference models directory
    if ref_models_dir:
        ref_path = Path(ref_models_dir)
    else:
        ref_path = resolve_refmodels_dir(cwd, hub_root)

    if not ont_path and not ref_path:
        click.echo(
            "❌ No ontology or reference model directories found. "
            "Use --ontology-dir or --ref-models-dir.",
            err=True,
        )
        raise SystemExit(1)

    # Resolve output directory
    if output_dir:
        out_path = Path(output_dir)
    elif hub_root:
        out_path = hub_root / "referencemodels-unpacked"
    else:
        out_path = Path("referencemodels-unpacked")

    legacy_inventories = find_legacy_inventory_files(
        ref_models_dir=ref_path,
        inventory_dir=out_path,
        ontology_dir=ont_path,
    )
    if legacy_inventories:
        click.echo(
            "❌ Legacy inventory format detected; generation will not overwrite it.", err=True
        )
        for finding in legacy_inventories:
            click.echo(f"   - {legacy_inventory_error(finding)}", err=True)
        raise SystemExit(1)

    catalog_path = (
        hub_root / "catalog-v001.xml"
        if hub_root and (hub_root / "catalog-v001.xml").is_file()
        else None
    )

    click.echo("📦 Generating materialized inventories")
    written: list[Path] = []
    writes = 0
    unchanged = 0
    failed: list[CommandOutcomeDecline] = []
    skipped: list[CommandOutcomeDecline] = []
    targets: list[CommandOutcomeTarget] = []

    # Process reference models
    ref_resolved = bool(ref_path and ref_path.is_dir())
    produced_by: dict[str, Path] = {}
    if ref_resolved:
        click.echo(f"   Reference models: {ref_path}")
        ref_ttls = iter_reference_inventory_sources(ref_path)
        ref_produced = 0
        ref_failed = 0
        for ttl_file in ref_ttls:
            stem = ttl_file.stem
            # Filename derivation is pure path arithmetic (no parsing), so the
            # collision check runs before generation is even attempted — a colliding
            # source is a failure regardless of whether it would have parsed cleanly.
            fname = inventory_filename(ttl_file, ref_models_dir=ref_path)
            if fname in produced_by and produced_by[fname] != ttl_file:
                detail = (
                    f"inventory name collision: {fname} already written from "
                    f"{produced_by[fname]}; skipping {ttl_file}. "
                    "Report this (DD-054 disambiguation gap)."
                )
                click.echo(f"   ❌ Inventory name collision: {fname} — {detail}", err=True)
                failed.append(CommandOutcomeDecline(str(ttl_file), REASON_COLLISION, detail))
                ref_failed += 1
                continue

            try:
                inv = generate_inventory(ttl_file, catalog_path=catalog_path, relative_to=ref_path)
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                # Advisory, not `❌`: DD-153's ownership rule (fail only for what the
                # hub author owns and can fix) — a parse exception is frequently a
                # vendored `ontology-reference-models/` source the author cannot
                # edit, so this alone must never print a `❌` that a plain (non-
                # strict, non-total-failure) run would then contradict by exiting 0.
                click.echo(f"   ⚠ Failed to parse {ttl_file.name}: {detail}", err=True)
                failed.append(CommandOutcomeDecline(str(ttl_file), REASON_EXCEPTION, detail))
                ref_failed += 1
                continue

            if not inv["classes"]:
                skipped.append(
                    CommandOutcomeDecline(str(ttl_file), REASON_EMPTY, "source yields no classes.")
                )
                continue

            produced_by[fname] = ttl_file
            yaml_path = out_path / fname
            try:
                wrote = write_inventory(inv, yaml_path)
            except OSError as e:
                detail = f"{type(e).__name__}: {e}"
                # Advisory, not `❌` — same ownership rationale as the parse-failure
                # branch above.
                click.echo(
                    f"   ⚠ Failed to write inventory for {ttl_file.name}: {detail}", err=True
                )
                failed.append(CommandOutcomeDecline(str(ttl_file), REASON_EXCEPTION, detail))
                ref_failed += 1
                del produced_by[fname]
                continue
            # An unchanged file still counts as produced (DD-153/DD-154) — the
            # artifact exists and is current; only the write was elided.
            written.append(yaml_path)
            ref_produced += 1
            n_classes = len(inv["classes"])
            if wrote:
                writes += 1
                n_specs = sum(len(c.get("specializations", [])) for c in inv["classes"])
                click.echo(f"   ✅ {stem}: {n_classes} classes, {n_specs} specializations")
            else:
                unchanged += 1
                click.echo(f"   ⏭ {stem}: up to date ({n_classes} classes)")

        targets.append(
            CommandOutcomeTarget(
                "reference-models",
                attempted=len(ref_ttls),
                produced=ref_produced,
                failed=ref_failed,
            )
        )

        # Pattern-library template stubs (blueprints/patterns/*/template.ttl) never
        # reach ref_ttls at all — iter_reference_inventory_sources excludes them
        # (issue #406) — but they are still worth naming explicitly as "skipped by
        # design" rather than leaving them silently unaccounted for.
        excluded_patterns = [
            ttl
            for ttl in sorted(ref_path.glob("**/*.ttl"))
            if is_pattern_template_source(ttl, ref_models_dir=ref_path)
        ]
        for ttl_file in excluded_patterns:
            skipped.append(
                CommandOutcomeDecline(
                    str(ttl_file),
                    REASON_EXCLUDED,
                    "pattern-library template stub (placeholder namespace, no "
                    "owl:versionInfo) — not a real reference-model source.",
                )
            )

    # Process domain ontologies
    ont_resolved = bool(ont_path and ont_path.is_dir())
    if ont_resolved:
        click.echo(f"   Ontologies: {ont_path}")
        ont_ttls = sorted(ont_path.glob("**/*.ttl"))
        ont_produced = 0
        ont_failed = 0
        for ttl_file in ont_ttls:
            try:
                inv = generate_inventory(
                    ttl_file,
                    include_specializations=False,
                    catalog_path=catalog_path,
                    relative_to=hub_root,
                )
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                # Advisory, not `❌` — same ownership rationale as the reference-model
                # branch above.
                click.echo(f"   ⚠ Failed to parse {ttl_file.name}: {detail}", err=True)
                failed.append(CommandOutcomeDecline(str(ttl_file), REASON_EXCEPTION, detail))
                ont_failed += 1
                continue

            if not inv["classes"]:
                skipped.append(
                    CommandOutcomeDecline(str(ttl_file), REASON_EMPTY, "source yields no classes.")
                )
                continue

            stem = ttl_file.stem
            yaml_path = out_path / inventory_filename(ttl_file)
            try:
                wrote = write_inventory(inv, yaml_path)
            except OSError as e:
                detail = f"{type(e).__name__}: {e}"
                # Advisory, not `❌` — same ownership rationale as the reference-model
                # branch above.
                click.echo(
                    f"   ⚠ Failed to write inventory for {ttl_file.name}: {detail}", err=True
                )
                failed.append(CommandOutcomeDecline(str(ttl_file), REASON_EXCEPTION, detail))
                ont_failed += 1
                continue
            # Unchanged still counts as produced (DD-153/DD-154).
            written.append(yaml_path)
            ont_produced += 1
            if wrote:
                writes += 1
                click.echo(f"   ✅ {stem}: {len(inv['classes'])} classes")
            else:
                unchanged += 1
                click.echo(f"   ⏭ {stem}: up to date ({len(inv['classes'])} classes)")

        targets.append(
            CommandOutcomeTarget(
                "ontologies",
                attempted=len(ont_ttls),
                produced=ont_produced,
                failed=ont_failed,
            )
        )

    if prune and out_path.is_dir():
        if not (ont_resolved and ref_resolved):
            if not ont_resolved and not ref_resolved:
                unresolved_scope = "ontology and reference-model"
            elif not ont_resolved:
                unresolved_scope = "ontology"
            else:
                unresolved_scope = "reference-model"
            click.echo(
                f"   ⏭  Skipping prune: the {unresolved_scope} scope was not resolved "
                "this run. Pruning requires both scopes reconciled, so a committed "
                "inventory belonging to the unresolved scope is never mistaken for "
                "orphaned. Pass --ontology-dir/--ref-models-dir explicitly, or rerun "
                "with --no-prune to silence this."
            )
        else:
            # Reuse the checker's own orphan notion (core/inventory.py) rather than a
            # second, independently-maintained "produced this run" set — a source that
            # failed this run is still a live source (it stays out of `report.orphan`
            # via `seen_files`, unconditional of whether it built successfully), so its
            # previously-committed inventory is never deleted out from under it.
            prune_report = check_inventories(
                ontology_dir=ont_path,
                ref_models_dir=ref_path,
                inventory_dir=out_path,
                catalog_path=catalog_path,
            )
            for orphan_name in prune_report.orphan:
                (out_path / orphan_name).unlink()
                click.echo(f"   🧹 Pruned orphaned inventory: {orphan_name}")

    outcome = CommandOutcome(
        command="generate-inventory",
        produced=tuple(str(p) for p in written),
        failed=tuple(failed),
        skipped=tuple(skipped),
        targets=tuple(targets),
    )
    # "generated" counts actual writes only (DD-154) — an idempotent rerun says
    # "0 generated, N unchanged", not "N generated".
    summary = (
        f"{writes} generated, {unchanged} unchanged, "
        f"{len(failed)} failed, {len(skipped)} skipped"
    )
    if outcome.is_blocking:
        # DD-153 invariant: a ❌ line is printed iff the exit code is non-zero.
        click.echo(f"\n❌ {summary} in {out_path}", err=True)
        raise SystemExit(1)
    if outcome.has_warnings:
        # Non-blocking failures/skips still exit 0 (e.g. an exception on a vendored
        # source the author does not own) — surfaced as a warning, not a cross mark,
        # so the ❌⟺exit!=0 invariant holds in both directions.
        click.echo(f"\n⚠ {summary} in {out_path}")
    else:
        click.echo(f"\n✅ {summary} in {out_path}")


@click.command(name="check-inventory")
@click.option(
    "--ontology-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/ontologies/ directory (default: auto-detect from hub).",
)
@click.option(
    "--ref-models-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontology-reference-models/ directory (default: auto-detect).",
)
@click.option(
    "--inventory-dir",
    type=click.Path(),
    default=None,
    help="Path to referencemodels-unpacked/ directory (default: auto-detect).",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack whose data-domains.yaml resolves --domains to "
    "inventory keys (default: [tool.kairos].accelerator, else inferred).",
)
@click.option(
    "--domains",
    "domains_filter",
    default=None,
    help="F5: comma-separated data-domains to scope readiness to "
    "(case-insensitive substring). Repository-wide check still runs and "
    "global failures are shown, but the exit code reflects only the "
    "selected domains"
    "'"
    " inventories.",
)
@click.option(
    "--explain-scope",
    is_flag=True,
    default=False,
    help="F5: print the domain→inventory-file mapping so it is clear which "
    "inventories belong to the selected --domains (and which global "
    "failures are out of scope).",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Also fail when an inventory cannot be verified (no stored hash).",
)
@click.option(
    "--warn-only",
    is_flag=True,
    default=False,
    help="Report problems but always exit 0 (never block).",
)
@click.option(
    "--verbose",
    "--all",
    "verbose",
    is_flag=True,
    default=False,
    help="With --domains, also list every out-of-scope module inventory instead of "
    "collapsing them to a one-line, non-blocking summary.",
)
def check_inventory_cmd(
    ontology_dir,
    ref_models_dir,
    inventory_dir,
    accelerator,
    domains_filter,
    explain_scope,
    strict,
    warn_only,
    verbose,
):
    """Verify that materialized inventories exist and are up to date (DD-047).

    Deterministic pre-flight gate for ``design-domain``: confirms that every source
    TTL has a matching ``referencemodels-unpacked/*-inventory.yaml`` and that the stored
    ``source_sha256`` matches the current file content.  Exits non-zero (blocking)
    when an inventory is **missing** or **stale**, so a modeler never works against
    an out-of-date view of the reference model's specialization tree.

    \\b
    F5 (toolkit-optimizations): ``--domains`` keeps the repository-wide check but
    scopes the blocking decision to the selected data-domains, so an unrelated
    missing/stale inventory no longer blocks the active domain (global failures are
    still printed). ``--explain-scope`` prints which inventories belong to each
    selected domain.

    \\b
    Examples:
      kairos-ontology check-inventory
      kairos-ontology check-inventory --strict
      kairos-ontology check-inventory --warn-only
      kairos-ontology check-inventory --domains booking --explain-scope
    """
    from ..core.inventory import (
        ACCELERATOR_PROFILE,
        DIRECT_PROFILE,
        classify_domain_scope,
        check_inventories,
        resolve_domain_inventory_keys,
        scope_inventory_report,
    )
    from ..core.hub_utils import find_hub_root
    from ..core.reference_modules import resolve_hub_accelerator_detailed

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontology_dir:
        ont_path: Path | None = Path(ontology_dir)
    elif hub_root:
        ont_path = hub_root / "model" / "ontologies"
    else:
        ont_path = None

    if ref_models_dir:
        ref_path: Path | None = Path(ref_models_dir)
    else:
        ref_path = resolve_refmodels_dir(cwd, hub_root)

    if inventory_dir:
        inv_path = Path(inventory_dir)
    elif hub_root:
        inv_path = hub_root / "referencemodels-unpacked"
    else:
        inv_path = Path("referencemodels-unpacked")

    if not ont_path and not ref_path:
        click.echo(
            "❌ No ontology or reference model directories found. "
            "Use --ontology-dir or --ref-models-dir.",
            err=True,
        )
        raise SystemExit(1)

    report = check_inventories(
        ontology_dir=ont_path,
        ref_models_dir=ref_path,
        inventory_dir=inv_path,
        catalog_path=(
            hub_root / "catalog-v001.xml"
            if hub_root and (hub_root / "catalog-v001.xml").is_file()
            else None
        ),
    )

    click.echo("🔎 Checking materialized inventories")
    click.echo(f"   Inventory dir: {inv_path}")
    if ref_path is not None:
        click.echo(f"   Reference models VERSION: {_format_refmodels_version(ref_path)}")
        provenance = _format_refmodels_fetch_provenance(ref_path)
        if provenance:
            click.echo(f"   Reference models provenance: {provenance}")
    # F5: parse the domain filter early so the global missing/stale wall can be
    # collapsed when scoping is active (it is reclassified as out-of-scope below).
    filter_list = None
    if domains_filter:
        filter_list = [d.strip() for d in domains_filter.split(",") if d.strip()]
    collapse_out_of_scope = bool(filter_list) and not verbose

    for stem in report.ok:
        click.echo(f"   ✓ {stem}: up to date")
    if not collapse_out_of_scope:
        for stem in report.missing:
            click.echo(f"   ❌ {stem}: MISSING inventory", err=True)
        for stem in report.stale:
            click.echo(f"   ❌ {stem}: STALE (source changed since generation)", err=True)
    for stem in report.unverifiable:
        click.echo(f"   ⚠ {stem}: cannot verify freshness (no stored hash — regenerate)")
    for stem in report.unbuildable:
        click.echo(
            f"   ⚠ {stem}: cannot build inventory (source TTL fails to parse — "
            "generate-inventory cannot fix this until the source itself is fixed)"
        )
    for name in report.orphan:
        click.echo(f"   ⚠ {name}: orphan inventory (no matching source TTL)")
    for diagnostic in report.migration_required:
        click.echo(f"   ❌ MIGRATION REQUIRED: {diagnostic}", err=True)

    scope = None
    if filter_list:
        # Auto-detect the catalog so import URIs can be resolved to source TTLs.
        catalog_path = None
        if hub_root:
            candidate_cat = hub_root / "catalog-v001.xml"
            if candidate_cat.exists():
                catalog_path = candidate_cat

        try:
            accelerator_resolution = resolve_hub_accelerator_detailed(
                explicit=accelerator,
                hub_root=hub_root,
                ref_models_dir=ref_path,
                domain_hint=filter_list,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        if ref_path is not None:
            click.echo(
                f"   Accelerator:  {accelerator_resolution.accelerator or '(none)'} "
                f"(source: {accelerator_resolution.source})"
            )
            if accelerator_resolution.data_domains_path is not None:
                click.echo(f"   Data domains: {accelerator_resolution.data_domains_path}")

        keys_by_domain, unresolved_by_domain = resolve_domain_inventory_keys(
            filter_list,
            ref_models_dir=ref_path,
            catalog_path=catalog_path,
            accelerator=accelerator_resolution.accelerator,
        )
        scope = scope_inventory_report(report, keys_by_domain, unresolved_by_domain)

        click.echo("\n🎯 Active-domain readiness:")
        for domain in filter_list:
            status, keys = classify_domain_scope(domain, keys_by_domain, report)
            if status == ACCELERATOR_PROFILE:
                label = "matched accelerator profile"
            elif status == DIRECT_PROFILE:
                label = "matched direct inventory"
            else:
                label = "no reference-model profile — no in-scope inventories to check"
            key_list = ", ".join(sorted(keys)) if keys else "(none)"
            click.echo(f"   • {domain}: {label} — inventories: {key_list}")
        out_of_scope = sorted((set(report.missing) | set(report.stale)) - scope.keys)
        if explain_scope:
            for domain in scope.domains:
                keys = sorted(keys_by_domain.get(domain, set()))
                click.echo(f"   • {domain}: {', '.join(keys) if keys else '(no inventories)'}")
            if out_of_scope:
                click.echo(
                    f"   ↪ out-of-scope global failures (not blocking here): "
                    f"{', '.join(out_of_scope)}"
                )
        elif collapse_out_of_scope and out_of_scope:
            click.echo(
                f"   ○ {len(out_of_scope)} out-of-scope module "
                f"{'inventory' if len(out_of_scope) == 1 else 'inventories'} "
                "not checked (not blocking; pass --verbose or --explain-scope to list)."
            )
        for stem in scope.missing:
            click.echo(f"   ❌ {stem}: MISSING (in scope)", err=True)
        for stem in scope.stale:
            click.echo(f"   ❌ {stem}: STALE (in scope)", err=True)
        for uri in scope.unresolved:
            click.echo(f"   ⚠ unresolved import URI (no source TTL in catalog): {uri}")

    # When --domains is given, the exit code follows the scoped readiness so an
    # unrelated missing/stale inventory does not block the active domain (F5). The
    # repository-wide failures above are still shown for visibility.
    if scope is not None:
        blocking = scope.is_blocking or (strict and (scope.unverifiable or scope.unbuildable))
    else:
        blocking = report.is_blocking or (strict and (report.unverifiable or report.unbuildable))

    if blocking and not warn_only:
        unbuildable_in_scope = scope.unbuildable if scope is not None else report.unbuildable
        if report.migration_required:
            next_step = "`kairos-ontology migrate --hub <hub>` and commit the result"
        elif not (report.missing or report.stale) and unbuildable_in_scope:
            # Distinct from the generic "run generate-inventory" remediation below:
            # regenerating cannot fix a source that does not parse (issue #405/#408 —
            # unbuildable is a closure failure, not staleness).
            next_step = (
                "fix the unbuildable source TTL(s) named above (a parse/import error) "
                "— `generate-inventory` cannot produce an inventory for them until the "
                "source itself is fixed"
            )
        else:
            next_step = "`kairos-ontology generate-inventory` and commit the result"
        click.echo(
            f"\n❌ Inventory check failed. Run {next_step} before modeling.",
            err=True,
        )
        raise SystemExit(1)

    if scope is not None and not blocking and report.is_blocking:
        click.echo(
            "\n✅ Active-domain inventories are ready "
            "(unrelated repository-wide failures shown above are out of scope)."
        )
    elif report.is_blocking or report.has_warnings:
        click.echo("\n⚠ Inventory check completed with warnings (not blocking).")
    else:
        click.echo("\n✅ Inventories are present and up to date.")


# ---------------------------------------------------------------------------
# check-ai-config (DD-159)
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "✅",
    "not_configured": "❌",
    "misconfigured": "❌",
    "unreachable": "❌",
    "unprobed": "⚠ ",
}


def _render_ai_config_text(report) -> None:
    click.echo("AI Provider Configuration Check")
    click.echo("=" * 40)
    click.echo("")
    for role_result in report.roles:
        icon = _STATUS_ICONS.get(role_result.status, "? ")
        click.echo(f"  {icon} {role_result.role}: {role_result.status}")
        if role_result.provider:
            click.echo(f"     provider: {role_result.provider}")
        if role_result.model:
            click.echo(f"     model:    {role_result.model}")
        if role_result.endpoint:
            click.echo(f"     endpoint: {role_result.endpoint}")
        if role_result.error:
            click.echo(f"     error:    {role_result.error}")
        if role_result.remediation:
            click.echo(f"     fix:      {role_result.remediation}")
        click.echo("")
    if report.is_blocking:
        click.echo("❌ AI provider check failed — one or more roles are not usable.")
    elif report.has_warnings:
        click.echo("⚠ AI provider check passed (unprobed — run with --probe to verify reachability).")
    else:
        click.echo("✅ AI provider check passed.")


@click.command(name="check-ai-config")
@click.option(
    "--role",
    type=click.Choice(["affinity", "alignment", "all"]),
    default="all",
    help="Which AI role to check (default: all).",
)
@click.option(
    "--model",
    default=None,
    help="Override the model name used for the check.",
)
@click.option(
    "--probe/--no-probe",
    "probe",
    default=True,
    help="Attempt a lightweight reachability probe against the endpoint (default: on).",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=10.0,
    help="Probe timeout in seconds (default: 10).",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Exit non-zero on warnings (unprobed) as well as errors.",
)
@click.option(
    "--warn-only",
    is_flag=True,
    default=False,
    help="Report status but always exit 0.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text -- human-readable). Use --format json for "
    "machine-readable output.",
)
def check_ai_config_cmd(role, model, probe, timeout_s, strict, warn_only, output_format):
    """Check AI provider configuration and optional reachability (DD-159).

    Inspects environment-variable configuration for the AI provider(s) used by
    affinity analysis and alignment proposal. By default probes the endpoint
    with a lightweight authenticated call. Prints environment variable NAMES
    only — never values. No api_key appears in any output format.

    Exit 0 when all requested roles are ok (or warn-only).
    Exit 1 when any role is not_configured / misconfigured / unreachable,
    or when --strict and any role is unprobed.
    """
    from kairos_ontology.core.ai_preflight import (
        preflight_all_roles,
        preflight_ai_provider,
        ROLE_AFFINITY as _AFF,
        ROLE_ALIGNMENT as _ALN,
    )

    if role == "all":
        report = preflight_all_roles(
            model=model, probe=probe, timeout_s=timeout_s,
            roles=(_AFF, _ALN),
        )
    else:
        single = preflight_ai_provider(
            role, model=model, probe=probe, timeout_s=timeout_s,
        )
        from kairos_ontology.core.ai_preflight import AIPreflightReport
        report = AIPreflightReport(roles=(single,))

    if output_format == "json":
        import json as _json
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        _render_ai_config_text(report)

    if warn_only:
        return

    exit_code = 0
    if report.is_blocking:
        exit_code = 1
    elif strict and report.has_warnings:
        exit_code = 1

    if exit_code:
        raise SystemExit(exit_code)


def _render_domain_coverage_text(report) -> None:
    click.echo(f"   Accelerator: {report.accelerator or '(none)'}")
    click.echo("")
    if not report.rows:
        click.echo("   No domains found (no blueprint, authored ontology, or binding evidence).")
        return

    def _cell(value) -> str:
        if value is None:
            return "n/a"
        return "yes" if value else "no"

    header = ("Domain", "In Blueprint", "Modeled", "EntityBinding", "_master.ttl import")
    rows = [
        (
            row.domain,
            _cell(row.in_blueprint),
            _cell(row.modeled),
            _cell(row.bound),
            _cell(row.imported),
        )
        for row in report.rows
    ]
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]

    def _format_row(cells) -> str:
        return "   " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    click.echo(_format_row(header))
    click.echo("   " + "-+-".join("-" * w for w in widths))
    for row in rows:
        click.echo(_format_row(row))

    gap_lines = []
    for row in report.rows:
        issues = []
        if row.in_blueprint is False:
            issues.append("not in accelerator blueprint")
        if not row.modeled:
            issues.append("not modeled")
        if not row.bound:
            issues.append("no EntityBinding")
        if row.modeled and not row.imported:
            issues.append("not imported by _master.ttl")
        if issues:
            gap_lines.append(f"   - {row.domain}: {', '.join(issues)}")
    if gap_lines:
        click.echo("")
        click.echo("   Gaps (advisory — does not fail this command):")
        for line in gap_lines:
            click.echo(line)


def _render_domain_explain_text(explain: dict) -> None:
    """Render the ``--explain <domain>`` ownership block (issue #418, DD-157).

    Mirrors analyse-sources' OWNS:/DOES NOT OWN: prompt block — the one place these
    boundaries were previously rendered, but only inside an LLM prompt no author saw.
    """
    domain = explain["domain"]
    if not explain["found"]:
        if explain["valid_domains"]:
            click.echo(
                f"ℹ Unknown domain '{domain}'. Valid blueprint domains: "
                + ", ".join(explain["valid_domains"])
            )
        else:
            click.echo(
                "ℹ Domain ownership metadata is unavailable — no accelerator blueprint "
                "(data-domains.yaml) is resolvable on this hub. Fetch reference models "
                "or install an accelerator pack first; nothing to explain."
            )
        return
    click.echo(f"🔎 Domain ownership — {domain} ({explain.get('name') or domain})")
    if explain.get("group"):
        click.echo(f"   Group: {explain['group']}")
    click.echo(f"   OWNS: {explain.get('owns') or '(not stated in the blueprint)'}")
    click.echo(
        f"   DOES NOT OWN: {explain.get('does_not_own') or '(not stated in the blueprint)'}"
    )
    imports = explain.get("imports") or []
    if imports:
        click.echo("   Blueprint imports (managed modules):")
        for imp in imports:
            label = imp.get("module") or imp.get("profile") or imp.get("module_id") or ""
            uri = imp.get("uri") or ""
            if label and uri:
                click.echo(f"     - {label} — {uri}")
            else:
                click.echo(f"     - {label or uri}")
    else:
        click.echo("   Blueprint imports (managed modules): (none)")


def _render_class_ownership_text(owns: dict) -> None:
    """Render the ``--owns <ClassName>`` reverse-lookup block (issue #418, DD-157)."""
    class_name = owns["class_name"]
    if not owns["inventories_present"]:
        click.echo(
            "ℹ No materialized inventories found under referencemodels-unpacked/ — run "
            "`kairos-ontology generate-inventory` first, then retry the ownership lookup."
        )
        return
    matches = owns["matches"]
    if not matches:
        click.echo(
            f"ℹ Class '{class_name}' was not found in any materialized inventory "
            "(referencemodels-unpacked/*-inventory.yaml)."
        )
        return
    click.echo(f"🔎 Ownership lookup — class '{class_name}' ({len(matches)} match(es)):")
    for match in matches:
        click.echo(f"   • {match['class_name']} — {match['class_uri']}")
        click.echo(f"     asserted by: {match['source_identity'] or '(unknown)'}")
        if match["module_id"] is None:
            click.echo("     managed module: (not asserted by a managed reference module)")
        else:
            click.echo(f"     managed module: {match['module_id']}")
            if match["domains"]:
                click.echo(f"     owning domain(s): {', '.join(match['domains'])}")
            else:
                click.echo(
                    "     owning domain(s): (module is assigned to no domain in the "
                    "blueprint)"
                )


def _render_class_ownership_batch_text(batch: dict) -> None:
    """Render the ``--owns A,B,C`` batch reverse-lookup block (issue #439)."""
    class_names = batch["class_names"]
    if not batch["inventories_present"]:
        click.echo(
            "ℹ No materialized inventories found under referencemodels-unpacked/ — run "
            "`kairos-ontology generate-inventory` first, then retry the ownership lookup."
        )
        return
    matches = batch["matches"]
    label = ", ".join(class_names)
    if not matches:
        click.echo(
            f"ℹ None of the requested classes ({label}) were found in any materialized "
            "inventory (referencemodels-unpacked/*-inventory.yaml)."
        )
        return
    click.echo(f"🔎 Ownership lookup — {len(class_names)} class(es): {label} "
               f"({len(matches)} match(es)):")
    for match in matches:
        click.echo(f"   • {match['class_name']} — {match['class_uri']}")
        click.echo(f"     asserted by: {match['source_identity'] or '(unknown)'}")
        if match["module_id"] is None:
            click.echo("     managed module: (not asserted by a managed reference module)")
        else:
            click.echo(f"     managed module: {match['module_id']}")
            if match["domains"]:
                click.echo(f"     owning domain(s): {', '.join(match['domains'])}")
            else:
                click.echo(
                    "     owning domain(s): (module is assigned to no domain in the "
                    "blueprint)"
                )


@click.command(name="domain-coverage")
@click.option(
    "--ontology-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to model/ontologies/ directory (default: auto-detect from hub).",
)
@click.option(
    "--ref-models-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontology-reference-models/ directory (default: auto-detect).",
)
@click.option(
    "--bindings-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to integration/bindings/ directory (default: auto-detect from hub).",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack whose data-domains.yaml supplies the blueprint domain "
    "list (default: [tool.kairos].accelerator, else inferred).",
)
@click.option(
    "--explain",
    "explain_domain",
    default=None,
    metavar="<domain>",
    help="Print one blueprint domain's ownership boundaries (owns / does_not_own) and "
    "its blueprint module imports (issue #418).",
)
@click.option(
    "--owns",
    "owns_classes",
    multiple=True,
    default=(),
    metavar="<ClassName>",
    help="Reverse-lookup which blueprint domain(s) own a class name, via the "
    "materialized referencemodels-unpacked/ inventories (issue #418). "
    "Case-insensitive; ownership can be plural. Accepts comma-separated names "
    "(--owns A,B,C) and/or repeated (--owns A --owns B) for batch lookup (issue #439).",
)
@click.option(
    "--json-output",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit a JSON object with schema_version, accelerator, and a 'domains' array "
    "(one row per domain). The key is 'domains' not 'coverage_table'.",
)
def domain_coverage_cmd(
    ontology_dir, ref_models_dir, bindings_dir, accelerator, explain_domain, owns_classes, as_json
):
    """Advisory domain-coverage table: blueprint x modeled x bound x _master.ttl import.

    Reports, per data domain, whether it is listed in the resolved accelerator's
    blueprint (data-domains.yaml), has an authored domain ontology TTL, has at
    least one EntityBinding, and is a live owl:imports in _master.ttl. A domain
    that is fully modeled, bound, and validated can still be unreachable from the
    hub's single ontology entry point if _master.ttl never imports it (issue #393)
    -- this surfaces that gap deterministically, with no LLM call. The table
    covers the UNION of blueprint-listed domains and authored-ontology stems, so a
    custom domain outside any blueprint is flagged rather than silently dropped.

    With --explain <domain> and/or --owns <ClassName> (issue #418, DD-157) the text
    output shows only the requested ownership section(s); --json-output always
    includes the full coverage table plus "explain"/"owns" payloads when requested.
    --owns accepts comma-separated names and/or repeated flags for batch lookup
    (issue #439); the single-name case keeps the "owns" JSON key, two or more names
    use the additive "owns_batch" key. On a hub without reference models these print
    an informational notice.

    Advisory only: always exits 0, even when gaps are found, the domain is unknown,
    or ownership metadata is unavailable. There is no --strict mode (deliberately
    deferred).

    \b
    Examples:
      kairos-ontology domain-coverage
      kairos-ontology domain-coverage --json-output
      kairos-ontology domain-coverage --accelerator logistics
      kairos-ontology domain-coverage --explain consignment
      kairos-ontology domain-coverage --owns TransportOrder
      kairos-ontology domain-coverage --owns TransportOrder,Party,Site
      kairos-ontology domain-coverage --owns TransportOrder --owns Party
    """
    from ..core.domain_coverage import (
        build_domain_coverage_report,
        load_domain_ownership,
        lookup_class_ownership,
        lookup_class_ownership_batch,
    )
    from ..core.hub_utils import find_hub_root
    from ..core.reference_modules import resolve_hub_accelerator_detailed

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)

    if ontology_dir:
        ont_path: Path = Path(ontology_dir)
    elif hub_root:
        ont_path = hub_root / "model" / "ontologies"
    else:
        raise click.ClickException(
            "Cannot locate a hub (model/ontologies/ not found). Use --ontology-dir."
        )

    if ref_models_dir:
        ref_path: Path | None = Path(ref_models_dir)
    else:
        ref_path = resolve_refmodels_dir(cwd, hub_root)

    if bindings_dir:
        bind_path = Path(bindings_dir)
    elif hub_root:
        bind_path = hub_root / "integration" / "bindings"
    else:
        bind_path = ont_path.parent.parent / "integration" / "bindings"

    master_path = ont_path / "_master.ttl"

    try:
        accelerator_resolution = resolve_hub_accelerator_detailed(
            explicit=accelerator,
            hub_root=hub_root,
            ref_models_dir=ref_path,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    no_accelerator = accelerator_resolution.accelerator is None
    owns_only = bool(owns_classes) and explain_domain is None
    if no_accelerator and not as_json and not owns_only:
        click.echo(
            "ℹ No accelerator pack installed — reporting modeled/bound/imported "
            "status without a blueprint column."
        )

    # Distinguish "accelerator resolved but its data-domains.yaml is missing"
    # from "no domains authored yet" (issue #467).
    _accelerator_data_domains_missing = False
    if accelerator_resolution.accelerator and ref_path and Path(ref_path).is_dir():
        dd_glob = (
            Path(ref_path)
            / f"accelerator-packs/{accelerator_resolution.accelerator}/client-hub-blueprint/data-domains.yaml"
        )
        if not dd_glob.is_file():
            _accelerator_data_domains_missing = True
            if not as_json and not owns_only:
                click.echo(
                    f"⚠ Accelerator '{accelerator_resolution.accelerator}' is configured but "
                    f"its data-domains.yaml was not found at {dd_glob}. "
                    "The blueprint column will be empty — check reference-models installation.",
                    err=True,
                )
    elif accelerator_resolution.accelerator and (not ref_path or not Path(ref_path).is_dir()):
        _accelerator_data_domains_missing = True
        if not as_json and not owns_only:
            click.echo(
                f"⚠ Accelerator '{accelerator_resolution.accelerator}' is configured but "
                "no reference-models directory was found. "
                "The blueprint column will be empty — install reference models or pass --ref-models-dir.",
                err=True,
            )

    # Skip the full coverage-report build when only --owns is passed (issue #439);
    # the coverage table stays available via --explain or the default bare command.
    report = None
    if not owns_only or as_json:
        report = build_domain_coverage_report(
            ontologies_dir=ont_path,
            bindings_dir=bind_path,
            master_path=master_path,
            ref_models_dir=ref_path,
            accelerator=accelerator_resolution.accelerator,
        )

    explain_payload = None
    if explain_domain:
        ownership = load_domain_ownership(
            ref_models_dir=ref_path, accelerator=accelerator_resolution.accelerator
        )
        entry = ownership.get(explain_domain)
        explain_payload = {
            "domain": explain_domain,
            "found": entry is not None,
            "valid_domains": sorted(ownership),
        }
        if entry is not None:
            explain_payload.update(
                {
                    "name": entry.get("name", explain_domain),
                    "group": entry.get("group", ""),
                    "owns": entry.get("owns", ""),
                    "does_not_own": entry.get("does_not_own", ""),
                    "imports": entry.get("imports", []),
                }
            )

    owns_payload = None
    owns_batch_payload = None
    if owns_classes:
        # Flatten comma-separated values and repeated --owns flags into one set.
        flat_names: list[str] = []
        for item in owns_classes:
            flat_names.extend(part.strip() for part in item.split(",") if part.strip())
        unique_names = list(dict.fromkeys(flat_names))  # preserve order, deduplicate

        if hub_root:
            inventory_dir = hub_root / "referencemodels-unpacked"
        else:
            inventory_dir = ont_path.parent.parent / "referencemodels-unpacked"

        if len(unique_names) == 1:
            owns_payload = lookup_class_ownership(
                class_name=unique_names[0],
                inventory_dir=inventory_dir,
                ref_models_dir=ref_path,
                accelerator=accelerator_resolution.accelerator,
            ).to_dict()
        else:
            owns_batch_payload = lookup_class_ownership_batch(
                class_names=set(unique_names),
                inventory_dir=inventory_dir,
                ref_models_dir=ref_path,
                accelerator=accelerator_resolution.accelerator,
            ).to_dict()

    if as_json:
        payload = report.to_dict() if report is not None else {"schema_version": 2}
        if explain_payload is not None:
            payload["explain"] = explain_payload
        if owns_payload is not None:
            payload["owns"] = owns_payload
        if owns_batch_payload is not None:
            payload["owns_batch"] = owns_batch_payload
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    if explain_payload is not None:
        _render_domain_explain_text(explain_payload)
    if owns_payload is not None:
        _render_class_ownership_text(owns_payload)
    if owns_batch_payload is not None:
        _render_class_ownership_batch_text(owns_batch_payload)
    if explain_payload is not None or owns_payload is not None or owns_batch_payload is not None:
        # Focused ownership query: the full coverage table stays available without
        # the flags (and always in --json-output). Advisory only — exit 0.
        return
    _render_domain_coverage_text(report)


@click.command(name="draft-model-report")
@click.option(
    "--analysis-dir",
    type=click.Path(),
    default=None,
    help="Path to _analysis/ directory with affinity reports (default: auto-detect).",
)
@click.option(
    "--mappings",
    type=click.Path(),
    default=None,
    help="Path to model/mappings/ directory with SKOS mappings (default: auto-detect).",
)
@click.option(
    "--tmdl-dir",
    type=click.Path(),
    default=None,
    help="Path to import-tmdl output (default: <hub root>/integration/discovery/bi/).",
)
@click.option(
    "--glossary-dir",
    type=click.Path(),
    default=None,
    help="Path to business-discovery glossary TTL directory (default: businessdiscovery/).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: model/planning/draft-model/).",
)
@click.option(
    "--domains",
    "domains_filter",
    default=None,
    help="Comma-separated domain names to include (case-insensitive substring match).",
)
@click.option(
    "--contract",
    type=click.Path(),
    default=None,
    help="Planning-only data-product contract YAML to scope the report.",
)
@click.option(
    "--data-product",
    default=None,
    help="Data product name; loads model/planning/data-products/<name>/contract.yaml.",
)
def draft_model_report_cmd(
    analysis_dir,
    mappings,
    tmdl_dir,
    glossary_dir,
    output,
    domains_filter,
    contract,
    data_product,
):
    """Create advisory draft domain-model evidence packs and a cross-domain ERD.

    The report combines source, mapping, TMDL, and glossary evidence without
    writing ontology TTL or acting as projection authority.
    """
    from ..core.draft_model_report import build_draft_model_report, write_draft_model_report
    from ..core.hub_utils import find_hub_root

    _warn_if_no_skill_context("draft-model-report")

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd)
    base = hub_root if hub_root else cwd

    analysis_path = Path(analysis_dir) if analysis_dir else _autodetect_analysis_dir(cwd, hub_root)
    mappings_path = Path(mappings) if mappings else base / "model" / "mappings"
    if tmdl_dir:
        tmdl_path = Path(tmdl_dir)
    else:
        tmdl_path = base / "integration" / "discovery" / "bi"
        if not tmdl_path.is_dir():
            legacy_tmdl_path = base / "integration" / "sources" / "powerbi"
            if legacy_tmdl_path.is_dir():
                tmdl_path = legacy_tmdl_path
    glossary_path = Path(glossary_dir) if glossary_dir else base / "businessdiscovery"
    contract_path = Path(contract) if contract else None
    if data_product and not contract_path:
        contract_path = (
            base / "model" / "planning" / "data-products" / data_product / "contract.yaml"
        )
    if contract_path and not contract_path.exists():
        raise click.ClickException(f"Data-product contract not found: {contract_path}")
    if output:
        output_path = Path(output)
    elif contract_path:
        output_path = contract_path.parent
    else:
        output_path = base / "model" / "planning" / "draft-model"
    filters = [f for f in (domains_filter.split(",") if domains_filter else []) if f.strip()]

    click.echo("🧭 Building advisory draft model report")
    click.echo(f"   Affinity: {analysis_path if analysis_path else '(none)'}")
    click.echo(f"   Mappings: {mappings_path if mappings_path.is_dir() else '(none)'}")
    click.echo(f"   TMDL:     {tmdl_path if tmdl_path.is_dir() else '(none)'}")
    click.echo(f"   Glossary: {glossary_path if glossary_path.exists() else '(none)'}")
    if contract_path:
        click.echo(f"   Product:  {contract_path}")

    try:
        report = build_draft_model_report(
            analysis_dir=analysis_path,
            mappings_dir=mappings_path if mappings_path.is_dir() else None,
            tmdl_dir=tmdl_path if tmdl_path.is_dir() else None,
            glossary_dir=glossary_path if glossary_path.exists() else None,
            domains_filter=filters,
            data_product_contract_path=contract_path,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    artifacts = write_draft_model_report(report, output_path)

    click.echo(f"   ✓ summary: {artifacts.summary_yaml}")
    click.echo(f"   ✓ report:  {artifacts.markdown}")
    click.echo(f"   ✓ ERD:     {artifacts.mermaid}")
    if report.get("artifact") == "data-product-draft-model-report":
        click.echo(
            "✅ Data-product vertical-slice plan for "
            f"{report['product']} across {report['summary']['domains']} domain(s)."
        )
    else:
        click.echo(f"✅ Draft model evidence packs for {report['summary']['domains']} domain(s).")


_NEXT_ADVISORY = (
    "advisory: recomputed every run, never stored, never authority (DD-137). "
    "A passing compile check is not a downstream runtime/release guarantee."
)


def _next_action_dict(action) -> dict:
    return {
        "kind": action.kind,
        "status": action.status.value,
        "skill": action.skill,
        "domain": action.domain,
        "target": action.target,
        "priority": action.priority,
        "blocking": action.blocking,
        "command": action.command,
        "rationale": action.rationale,
    }


def _render_next_text(proposal, snapshot) -> None:
    from ..core.next_actions import InputStatus, SourceSampleStatus, discovery_gate_satisfied

    click.echo("🧭 Kairos next-action proposal (advisory — recomputed, not stored)")
    click.echo(f"   Hub: {proposal.hub_root}")
    click.echo(f"   {proposal.summary}")
    click.echo("")
    click.echo("   Authored inputs (presence only — completeness is never inferred):")
    discovery_state = snapshot.discovery.value
    if snapshot.discovery is InputStatus.MISSING and discovery_gate_satisfied(snapshot):
        discovery_state += " (compile/validate gate satisfied via conformance artifact — DD-148)"
    click.echo(f"     discovery:      {discovery_state}")
    sources_state = snapshot.sources.value
    sample_status = snapshot.source_samples.status
    if sample_status is SourceSampleStatus.NONE:
        sources_state += f" (no sample evidence in {snapshot.source_samples.tables_total} table(s))"
    elif sample_status in (SourceSampleStatus.PARTIAL, SourceSampleStatus.FULL):
        sources_state += (
            f" (samples: {snapshot.source_samples.tables_with_samples}/"
            f"{snapshot.source_samples.tables_total} tables)"
        )
    click.echo(f"     sources:        {sources_state}")
    click.echo(f"     dbt transforms: {snapshot.dbt_transforms.value}")
    click.echo(f"     shapes:         {snapshot.shapes.value}")
    click.echo(f"     emitted dbt:    {snapshot.emitted_dbt_project.value}")
    click.echo(f"     inventory:      {snapshot.inventory_status.value}")
    if snapshot.bi_concept_mappings.tables_total:
        click.echo(
            f"     bi worksheets:  {snapshot.bi_concept_mappings.tables_unfilled}/"
            f"{snapshot.bi_concept_mappings.tables_total} concept-mapping table(s) unfilled"
        )
    if not proposal.actions:
        return
    click.echo("")
    click.echo("   Next actions:")
    for action in proposal.actions:
        scope = f" [{action.domain}]" if action.domain else ""
        click.echo(f"     • [{action.status.value}] {action.kind}{scope} → skill: {action.skill}")
        click.echo(f"         {action.rationale}")
        click.echo(f"         run: {action.command}")


@click.command(name="next")
@click.option("--domain", "domains", multiple=True, help="Restrict to one or more domains.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (JSON is emitted clean on stdout).",
)
@click.option(
    "--no-compile",
    "no_compile",
    is_flag=True,
    default=False,
    help="Skip the canonical compile check; downstream readiness is reported indeterminate.",
)
def next_action_cmd(domains, output_format, no_compile):
    """Propose the next stateless action(s) from authored hub inputs (advisory, DD-137)."""
    from ..core.hub_utils import find_hub_root
    from ..core.hub_inspection import gather_hub_input_snapshot
    from ..core.next_actions import SCHEMA_VERSION, discovery_gate_satisfied, propose_next_actions

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        if output_format == "json":
            click.echo(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "error": "hub-not-found",
                        "message": "no Kairos hub (model/ + integration/) found from cwd",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            click.echo("❌ No Kairos hub found from the current directory.", err=True)
        raise click.exceptions.Exit(2)

    snapshot = gather_hub_input_snapshot(
        hub_root, domains=list(domains) or None, run_compile=not no_compile
    )
    proposal = propose_next_actions(snapshot)

    if output_format == "json":
        click.echo(_NEXT_ADVISORY, err=True)
        payload = {
            "schema_version": proposal.schema_version,
            "hub_root": Path(proposal.hub_root).as_posix(),
            "summary": proposal.summary,
            "compile_ran": snapshot.compile_ran,
            "inputs": {
                "discovery": snapshot.discovery.value,
                "discovery_conformance": snapshot.discovery_conformance.value,
                "discovery_gate_satisfied": discovery_gate_satisfied(snapshot),
                "sources": snapshot.sources.value,
                "source_samples": {
                    "status": snapshot.source_samples.status.value,
                    "tables_with_samples": snapshot.source_samples.tables_with_samples,
                    "tables_total": snapshot.source_samples.tables_total,
                },
                "dbt_transforms": snapshot.dbt_transforms.value,
                "shapes": snapshot.shapes.value,
                "emitted_dbt_project": snapshot.emitted_dbt_project.value,
                "inventory_status": snapshot.inventory_status.value,
                "bi_concept_mappings": {
                    "tables_total": snapshot.bi_concept_mappings.tables_total,
                    "tables_unfilled": snapshot.bi_concept_mappings.tables_unfilled,
                },
            },
            "actions": [_next_action_dict(action) for action in proposal.actions],
        }
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    _render_next_text(proposal, snapshot)


def _render_design_landscape_text(result) -> None:
    click.echo(f"🗺  design-landscape — {result.advisory}")
    click.echo(f"   Accelerator: {result.accelerator or '(none)'}")
    click.echo(f"   Domain: {result.domain or '(all activated modules)'}")
    click.echo("")
    if not result.classes:
        click.echo(
            "   No in-scope classes found (no source table, discovery, or binding "
            "evidence references any activated accelerator class)."
        )
    for entry in result.classes:
        rank = f" (rank {entry.rank})" if entry.rank is not None else ""
        click.echo(f"   • {entry.class_name} [{entry.classification}]{rank}")
        click.echo(f"     {entry.class_uri}")
        click.echo(
            f"     Sources: {entry.source_count} table(s) | "
            f"Properties: {entry.populated_property_count} populated / "
            f"{entry.property_universe_size} total"
        )
        if entry.discovery:
            confirmed = "confirmed" if entry.discovery.confirmed else "not confirmed"
            click.echo(
                f"     Discovery: outcome={entry.discovery.outcome} tier={entry.discovery.tier} "
                f"({confirmed})"
            )
        if entry.bi_weight:
            click.echo(
                f"     BI weight (ADVISORY ONLY, never fact): {len(entry.bi_weight)} reference(s)"
            )
        click.echo(f"     Bound: {entry.bound} ({len(entry.bindings)} binding(s))")
        click.echo("")
    if result.gaps:
        click.echo("   Gaps / degraded inputs:")
        for gap in result.gaps:
            click.echo(f"     - {gap}")


@click.command(name="design-landscape")
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack id (default: [tool.kairos].accelerator, else inferred).",
)
@click.option(
    "--domain",
    default=None,
    help="Restrict to one hub data domain's activated accelerator module(s) "
    "(default: every module profile configured for the resolved accelerator).",
)
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
def design_landscape_cmd(accelerator, domain, out_format):
    """Read-only synthesis report: which accelerator classes to design next.

    Joins already-existing evidence signals **by accelerator class** so an author can see,
    before doing any design work, which classes have real multi-source coverage and
    confirmed business demand versus which have none:

    \b
    1. Source coverage    - fit-report generalized across every propose-alignment table.
    2. Discovery demand    - the committed discovery-conformance artifact (DD-090).
    3. BI/report weight    - import-tmdl's Concept Mapping output (ADVISORY ONLY, never
                             fact -- see the structurally separate bi_weight field).
    4. Current binding state - existing EntityBindings' target.class / metadata.tier.

    Deterministic aggregation only: no LLM calls, no raw TTL reads (DD-103). Classifies
    each in-scope class into canonical-candidate, passthrough-candidate,
    demanded-but-unbound, bound-but-undemanded, or no-evidence.

    \b
    Examples:
      kairos-ontology design-landscape
      kairos-ontology design-landscape --domain party
      kairos-ontology design-landscape --accelerator acme --format json
    """
    from ..core.design_landscape import DesignLandscapeError, run_design_landscape
    from ..core.hub_utils import find_hub_root

    cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=True)
    if hub_root is None:
        raise click.ClickException("Cannot locate a hub (model/ontologies/ not found).")

    ref_models_dir = resolve_refmodels_dir(cwd, hub_root)

    try:
        result = run_design_landscape(
            hub_root,
            ref_models_dir=ref_models_dir,
            accelerator=accelerator,
            domain=domain,
        )
    except DesignLandscapeError as exc:
        raise click.ClickException(str(exc)) from exc

    if out_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    _render_design_landscape_text(result)


_GUARD_TOKEN_FORMAT = "kairos-guard-scope/1"

# Fingerprint sentinels for paths that have no hashable worktree content.
_FP_ABSENT = "<absent>"  # deleted, or the vanished side of a rename
_FP_DIR = "<directory>"  # e.g. an embedded git repo, reported as "?? nested/"
_FP_UNREADABLE = "<unreadable>"


def _parse_porcelain_entries(status_text: str) -> dict[str, str]:
    """Map every repo-root-relative path in a ``-z`` porcelain stream to its status code.

    The stream is a sequence of NUL-terminated fields, **not** lines. A plain
    entry is ``XY<space>PATH``: two status characters (index column, worktree
    column) then a space, then the raw unquoted path. A rename or copy — ``X``
    in ``RC`` — is followed by one *extra* field holding the bare **old** path.

    Note the ordering, which is the reverse of the default (non-``-z``) format:
    ``-z`` emits ``R  NEW`` then ``OLD``, where the default emits the single
    line ``R  OLD -> NEW``. Both sides are recorded, under the same status
    code, so a rename cannot slip past an allowlist that names only one of
    them.
    """
    entries: dict[str, str] = {}
    fields = [field for field in status_text.split("\0") if field]
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if len(field) < 4:
            continue  # not "XY PATH" — malformed, and there is no path to guard
        code, path = field[:2], field[3:]
        entries[path] = code
        if code[0] in ("R", "C") and index < len(fields):
            entries[fields[index]] = code  # the old path, its own NUL-terminated field
            index += 1
    return entries


def _worktree_fingerprint(target: Path) -> str:
    """Return a content hash for *target*, or a sentinel when there is nothing to hash.

    Sentinels stand in for the entries a hash cannot describe: a deleted path
    (``D`` in either status column, and the old side of a rename) has no
    content, and a directory entry — an embedded git repository surfaces as
    ``?? nested/`` — is not a file. Returning a sentinel rather than raising is
    what lets ``--check-since`` still render a verdict on such a tree.

    Read in chunks: a status entry may name a file of any size, and the guard
    must not hold one in memory to hash it.
    """
    try:
        if target.is_dir():
            return _FP_DIR
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return _FP_ABSENT
    except (OSError, ValueError):
        # ValueError covers UnicodeEncodeError on a surrogate-escaped path.
        return _FP_UNREADABLE


def _guard_scope_state(repo_dir: Path, repo_root: Path) -> dict[str, list[str]]:
    """Snapshot every path git currently reports, as ``{path: [status_code, fingerprint]}``.

    Both halves are recorded because neither subsumes the other. ``git add`` on
    an already-dirty file moves ``" M"`` to ``"M "`` while the worktree bytes —
    and therefore the hash — stay identical; conversely a rewrite that leaves
    the file dirty keeps the status code and changes only the hash.

    Only paths git already names are hashed, so the cost tracks the size of the
    dirty set, not of the repository.
    """
    entries = _parse_porcelain_entries(_git_status_snapshot(repo_dir))
    return {path: [code, _worktree_fingerprint(repo_root / path)] for path, code in entries.items()}


def _guard_scope_ignored_state(repo_root: Path, roots: tuple[str, ...]) -> dict[str, list[str]]:
    """Snapshot every gitignored file under *roots*, keyed the same way as
    :func:`_guard_scope_state` so the two dicts merge into one uniformly diffable
    fingerprint map. *roots* are the ``--ignored-root`` paths opted in at
    ``--snapshot`` time (repo-root-relative); an empty tuple means nothing is
    scanned — this is only ever called when there is at least one root.
    """
    entries = _parse_porcelain_entries(_git_ignored_snapshot(repo_root, roots))
    return {path: [code, _worktree_fingerprint(repo_root / path)] for path, code in entries.items()}


def _read_guard_token(token_path: Path) -> tuple[str, dict[str, list[str]], tuple[str, ...]]:
    """Load a guard-scope token, hard-failing on any format this build cannot read.

    The token carries an explicit format marker on its first line and is
    rejected outright when that marker is missing or unknown. Refusing is the
    only safe response: a token this build cannot parse would otherwise be read
    as an empty or garbled baseline, and a guard that misreads its baseline
    reports a *pass*.

    ``ignored_roots`` defaults to an empty tuple when absent from the token,
    so a token written before ``--ignored-root`` existed still parses and
    behaves exactly as it did before (no gitignored-path visibility, same as
    always).
    """
    raw = token_path.read_text(encoding="utf-8")
    marker, _, payload = raw.partition("\n")
    if marker.strip() != _GUARD_TOKEN_FORMAT:
        raise click.ClickException(
            f"Unrecognised guard-scope token format in {token_path} "
            f"(expected first line {_GUARD_TOKEN_FORMAT!r}). Tokens are not portable "
            f"across toolkit versions — take a fresh --snapshot with this build."
        )
    try:
        token = json.loads(payload)
        head = token["head"]
        entries = token["entries"]
        ignored_roots = token.get("ignored_roots", [])
        if (
            not isinstance(head, str)
            or not isinstance(entries, dict)
            or not isinstance(ignored_roots, list)
            or not all(isinstance(root, str) for root in ignored_roots)
        ):
            raise ValueError("unexpected token shape")
    except (ValueError, KeyError, TypeError) as exc:
        raise click.ClickException(
            f"Corrupt guard-scope token {token_path}: {exc}. Take a fresh --snapshot."
        ) from exc
    return (
        head,
        {path: list(value) for path, value in entries.items()},
        tuple(ignored_roots),
    )


@click.command(name="guard-scope")
@click.option(
    "--snapshot",
    is_flag=True,
    help="Capture the current git working-tree status to a token file and print its path.",
)
@click.option(
    "--check-since",
    "check_since",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Compare current git status against the snapshot at this token path.",
)
@click.option(
    "--allow",
    "allow_globs",
    multiple=True,
    help="Glob (relative to the git repo root) allowed to have changed since the "
    "snapshot. Repeatable. Only valid with --check-since.",
)
@click.option(
    "--ignored-root",
    "ignored_roots",
    multiple=True,
    help="Path (relative to the git repo root) of a gitignored tree to also "
    "fingerprint, opt-in and bounded. Repeatable. Only valid with --snapshot — "
    "the resolved root list is stored inside the token itself, and --check-since "
    "reads it back from there, so the two calls can never disagree on scope.",
)
def guard_scope_cmd(
    snapshot: bool,
    check_since: Path | None,
    allow_globs: tuple[str, ...],
    ignored_roots: tuple[str, ...],
) -> None:
    """Deterministic 'no unexpected file changed' guard for a bounded skill gate.

    Replaces a self-reported "confirm no other file changed" instruction with
    a code-enforced check. No persisted hub state is involved: the snapshot is
    a throwaway file in the OS temp directory, never written into the hub or
    repo, and git's own working-tree status is the only source of truth.

    \b
    --snapshot [--ignored-root PATH ...]
        Capture the current working-tree status (tracked and untracked
        changes) and print the token path to stdout. Pass that path to
        --check-since at the end of the bounded work. Each --ignored-root
        (repo-root-relative, repeatable) additionally fingerprints every
        gitignored file under that path, so a write there is no longer
        invisible; the resolved root list travels inside the token itself.
    --check-since TOKEN --allow GLOB [--allow GLOB ...]
        Compare current status against the snapshot at TOKEN. Any path whose
        content or git status differs from the snapshot — including one that
        was already dirty when the snapshot was taken, and one that has since
        disappeared from git's output — fails the command unless it matches at
        least one --allow glob (non-zero exit, every offending path is named).
        A commit moving HEAD inside the window also fails. On success, the
        token file is removed. If the token was taken with --ignored-root,
        those same roots are re-scanned here automatically (no --ignored-root
        flag is accepted on this side — the token is the single source of scope).

    Scope of the guarantee: the guard sees exactly what git reports, plus any
    path passed via --ignored-root at snapshot time. It remains blind to
    writes into any other gitignored path — a passing result does not attest
    to those.
    """
    if snapshot and check_since is not None:
        raise click.UsageError("--snapshot and --check-since are mutually exclusive.")
    if not snapshot and check_since is None:
        raise click.UsageError("exactly one of --snapshot or --check-since is required.")
    if snapshot and allow_globs:
        raise click.UsageError("--allow is only valid with --check-since.")
    if ignored_roots and not snapshot:
        raise click.UsageError(
            "--ignored-root is only valid with --snapshot; --check-since reads the "
            "ignored roots back from the token itself."
        )

    repo_dir = Path.cwd()
    repo_root = _git_repo_root(repo_dir)

    if snapshot:
        entries = _guard_scope_state(repo_dir, repo_root)
        if ignored_roots:
            entries.update(_guard_scope_ignored_state(repo_root, ignored_roots))
        token = {
            "head": _git_head_sha(repo_dir),
            "entries": entries,
            "ignored_roots": list(ignored_roots),
        }
        fd, token_name = tempfile.mkstemp(prefix="kairos-guard-scope-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # Marker first, so a token from a newer toolkit is *recognised* as
            # unreadable by an older one rather than silently misparsed.
            # ensure_ascii keeps any surrogate-escaped path writable as UTF-8.
            fh.write(f"{_GUARD_TOKEN_FORMAT}\n")
            fh.write(json.dumps(token, ensure_ascii=True, sort_keys=True))
        click.echo(token_name)
        return

    baseline_head, baseline, token_ignored_roots = _read_guard_token(check_since)
    current_head = _git_head_sha(repo_dir)
    current = _guard_scope_state(repo_dir, repo_root)
    if token_ignored_roots:
        current.update(_guard_scope_ignored_state(repo_root, token_ignored_roots))

    # Compare in both directions: a path that *left* git's output — an
    # already-dirty untracked file that was deleted, or a dirty tracked file
    # flipping " M" to " D" — is a change the forward direction cannot see.
    offending = sorted(
        path
        for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
        and not any(fnmatch.fnmatch(path, glob) for glob in allow_globs)
    )
    head_moved = baseline_head != current_head
    if offending or head_moved:
        click.echo(
            "❌ guard-scope: unexpected change(s) outside the allowed scope:",
            err=True,
        )
        if head_moved:
            click.echo(
                f"   HEAD moved since the snapshot: "
                f"{baseline_head or '(unborn)'} → {current_head or '(unborn)'}",
                err=True,
            )
        for path in offending:
            click.echo(f"   {path}", err=True)
        raise click.ClickException(
            "Scope guard failed — restrict changes to the allowed paths, or pass "
            "--allow for each additional path that legitimately changed."
        )

    try:
        check_since.unlink()
    except OSError:
        pass
    click.echo("✓ guard-scope passed — no unexpected file changes.")
