# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused inspection CLI commands."""

import fnmatch
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
    _git_status_snapshot,
    _resolve_ref_models_dir,
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
    click.echo(
        json.dumps(
            loaded.semantic_index.slice(max_classes=max_classes),
            indent=2,
            sort_keys=True,
        )
    )


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
        ref_models_path = _resolve_ref_models_dir(cwd, hub_root)
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
    from ..core.inventory import (
        find_legacy_inventory_files,
        generate_inventory,
        inventory_filename,
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
        ref_path = _resolve_ref_models_dir(cwd, hub_root)

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

    click.echo("📦 Generating materialized inventories")
    written: list[Path] = []

    # Process reference models
    produced_by: dict[str, Path] = {}
    if ref_path and ref_path.is_dir():
        click.echo(f"   Reference models: {ref_path}")
        ref_ttls = iter_reference_inventory_sources(ref_path)
        for ttl_file in ref_ttls:
            try:
                catalog_path = (
                    hub_root / "catalog-v001.xml"
                    if hub_root and (hub_root / "catalog-v001.xml").is_file()
                    else None
                )
                inv = generate_inventory(ttl_file, catalog_path=catalog_path)
                if not inv["classes"]:
                    continue
                stem = ttl_file.stem
                fname = inventory_filename(ttl_file, ref_models_dir=ref_path)
                if fname in produced_by and produced_by[fname] != ttl_file:
                    click.echo(
                        f"   ❌ Inventory name collision: {fname} already written "
                        f"from {produced_by[fname]}; skipping {ttl_file}. "
                        "Report this (DD-054 disambiguation gap).",
                        err=True,
                    )
                    continue
                produced_by[fname] = ttl_file
                yaml_path = out_path / fname
                write_inventory(inv, yaml_path)
                written.append(yaml_path)
                n_classes = len(inv["classes"])
                n_specs = sum(len(c.get("specializations", [])) for c in inv["classes"])
                click.echo(f"   ✅ {stem}: {n_classes} classes, {n_specs} specializations")
            except Exception as e:
                click.echo(f"   ⚠ Failed to process {ttl_file.name}: {e}", err=True)

    # Process domain ontologies
    if ont_path and ont_path.is_dir():
        click.echo(f"   Ontologies: {ont_path}")
        ont_ttls = sorted(ont_path.glob("**/*.ttl"))
        for ttl_file in ont_ttls:
            try:
                catalog_path = (
                    hub_root / "catalog-v001.xml"
                    if hub_root and (hub_root / "catalog-v001.xml").is_file()
                    else None
                )
                inv = generate_inventory(
                    ttl_file,
                    include_specializations=False,
                    catalog_path=catalog_path,
                )
                if not inv["classes"]:
                    continue
                stem = ttl_file.stem
                yaml_path = out_path / inventory_filename(ttl_file)
                write_inventory(inv, yaml_path)
                written.append(yaml_path)
                click.echo(f"   ✅ {stem}: {len(inv['classes'])} classes")
            except Exception as e:
                click.echo(f"   ⚠ Failed to process {ttl_file.name}: {e}", err=True)

    if prune and out_path.is_dir():
        produced = {p.name for p in written}
        for existing in sorted(out_path.glob("*-inventory.yaml")):
            if existing.name not in produced:
                existing.unlink()
                click.echo(f"   🧹 Pruned orphaned inventory: {existing.name}")

    click.echo(f"\n✅ Generated {len(written)} inventory file(s) in {out_path}")


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
        ref_path = _resolve_ref_models_dir(cwd, hub_root)

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
        blocking = scope.is_blocking or (strict and scope.unverifiable)
    else:
        blocking = report.is_blocking or (strict and report.unverifiable)

    if blocking and not warn_only:
        next_step = (
            "`kairos-ontology migrate --hub <hub>` and commit the result"
            if report.migration_required
            else "`kairos-ontology generate-inventory` and commit the result"
        )
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
    help="Path to import-tmdl output (default: integration/discovery/bi/).",
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
    click.echo("🧭 Kairos next-action proposal (advisory — recomputed, not stored)")
    click.echo(f"   Hub: {proposal.hub_root}")
    click.echo(f"   {proposal.summary}")
    click.echo("")
    click.echo("   Authored inputs (presence only — completeness is never inferred):")
    click.echo(f"     discovery:      {snapshot.discovery.value}")
    click.echo(f"     sources:        {snapshot.sources.value}")
    click.echo(f"     dbt transforms: {snapshot.dbt_transforms.value}")
    click.echo(f"     shapes:         {snapshot.shapes.value}")
    click.echo(f"     emitted dbt:    {snapshot.emitted_dbt_project.value}")
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
    from ..core.next_actions import SCHEMA_VERSION, propose_next_actions

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
                "sources": snapshot.sources.value,
                "dbt_transforms": snapshot.dbt_transforms.value,
                "shapes": snapshot.shapes.value,
                "emitted_dbt_project": snapshot.emitted_dbt_project.value,
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

    ref_models_dir = _resolve_ref_models_dir(cwd, hub_root)

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


def _parse_porcelain_paths(status_text: str) -> set[str]:
    """Extract the repo-root-relative path(s) from ``git status --porcelain`` lines.

    Each line is ``XY PATH`` (status code, space, path); a rename line is
    ``XY OLD -> NEW``, and both sides are returned so a rename can't slip past
    an allowlist that only names one side.
    """
    paths: set[str] = set()
    for line in status_text.splitlines():
        if not line:
            continue
        entry = line[3:] if len(line) > 3 else line.lstrip()
        if " -> " in entry:
            old, _, new = entry.partition(" -> ")
            paths.add(old.strip())
            paths.add(new.strip())
        else:
            paths.add(entry.strip())
    return paths


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
def guard_scope_cmd(snapshot: bool, check_since: Path | None, allow_globs: tuple[str, ...]) -> None:
    """Deterministic 'no unexpected file changed' guard for a bounded skill gate.

    Replaces a self-reported "confirm no other file changed" instruction with
    a code-enforced check. No persisted hub state is involved: the snapshot is
    a throwaway file in the OS temp directory, never written into the hub or
    repo, and git's own working-tree status is the only source of truth.

    \b
    --snapshot
        Capture the current working-tree status (tracked and untracked
        changes) and print the token path to stdout. Pass that path to
        --check-since at the end of the bounded work.
    --check-since TOKEN --allow GLOB [--allow GLOB ...]
        Compare current status against the snapshot at TOKEN. Any path that
        changed or newly appeared since the snapshot and does not match at
        least one --allow glob fails the command (non-zero exit, every
        offending path is named). On success, the token file is removed.
    """
    if snapshot and check_since is not None:
        raise click.UsageError("--snapshot and --check-since are mutually exclusive.")
    if not snapshot and check_since is None:
        raise click.UsageError("exactly one of --snapshot or --check-since is required.")
    if snapshot and allow_globs:
        raise click.UsageError("--allow is only valid with --check-since.")

    repo_dir = Path.cwd()

    if snapshot:
        status_text = _git_status_snapshot(repo_dir)
        fd, token_name = tempfile.mkstemp(prefix="kairos-guard-scope-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(status_text)
        click.echo(token_name)
        return

    baseline_paths = _parse_porcelain_paths(check_since.read_text(encoding="utf-8"))
    current_paths = _parse_porcelain_paths(_git_status_snapshot(repo_dir))

    new_paths = current_paths - baseline_paths
    offending = sorted(
        path for path in new_paths if not any(fnmatch.fnmatch(path, glob) for glob in allow_globs)
    )
    if offending:
        click.echo(
            "❌ guard-scope: unexpected file(s) changed outside the allowed scope:", err=True
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
